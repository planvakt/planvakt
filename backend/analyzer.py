from dotenv import load_dotenv
import os
from typing import Optional, List, Union
# .env i planvakt/ (mappen over backend/) – absolutt sti uavhengig av cwd
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
load_dotenv(os.path.abspath(_env_path))

import io
import json
import requests
from PyPDF2 import PdfReader
from supabase import create_client
from google import genai
from google.genai import types

from utils import generate_content_with_retry

# --- SETUP (klienter opprettes lazy via get_supabase() så env er lastet) ---
api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

_supabase = None

def get_supabase():
    global _supabase
    if _supabase is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
        print(f"DEBUG: URL er {'satt' if url else 'TOM'}, KEY er {'satt' if key else 'TOM'}")
        _supabase = create_client(url, key)
    return _supabase

GATEKEEPER_MODEL = "gemini-2.5-flash"
EXPERT_MODEL = "gemini-2.5-pro"

# --- AUTO-DISCOVERY: find municipality by name (no .env ID) ---
def get_municipality_by_name(name):
    """Search municipalities table for a record where name matches the input (e.g. 'Asker').
    Returns (id, profile_text) or (None, None)."""
    try:
        res = get_supabase().table("municipalities").select("id, profile_text").eq("name", name.strip()).execute()
        if res.data and len(res.data) > 0:
            row = res.data[0]
            return row["id"], (row.get("profile_text") or "")
        return None, None
    except Exception as e:
        print(f"⚠️ Error looking up municipality: {e}")
        return None, None


def get_pdf_text(url, max_pages):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, stream=True, timeout=25)
        f = io.BytesIO(response.content)
        reader = PdfReader(f)
        parts = [reader.pages[i].extract_text() for i in range(min(len(reader.pages), max_pages))]
        return "\n".join(parts) if parts else None
    except Exception:
        return None


def run_full_analysis(url, municipality_name):
    print(f"\n--- Starting analysis for {municipality_name} ---")

    # 1. Auto-discovery: find municipality by name and get profile_text
    m_id, profile_text = get_municipality_by_name(municipality_name)
    if not m_id:
        print(f"❌ Municipality '{municipality_name}' not found in database.")
        return

    if not profile_text:
        profile_text = "General development"

    # 2. Gatekeeper (Flash): first 5 pages — only say JA if relevant to property development
    gatekeeper_text = get_pdf_text(url, max_pages=5)
    if not gatekeeper_text:
        print("❌ Could not extract text from PDF.")
        return

    gatekeeper_prompt = (
        "You are a smart document screener for a property investor. Your job is to decide if a document represents a potential real estate development opportunity.\n\n"
        "When to say JA:\n"
        "If it involves new residential or commercial buildings (nybygg, enebolig, flermannsbolig).\n"
        "If it involves dividing land or creating new plots (deling av eiendom, fradeling).\n"
        "If it involves zoning plans (reguleringsplan, planinitiativ).\n"
        "If it involves changing the use of a building (bruksendring, seksjonering).\n"
        "If it is a pre-conference (forhåndskonferanse) for a potential new project.\n"
        "CRITICAL: If you are in doubt, or if there is ANY potential for value creation, say JA.\n\n"
        "When to say NEI (Strict Blacklist):\n"
        "Minor private upgrades: Frittstående garasje, carport, uthus, bod, gjerde, støttemur, terrasse.\n"
        "Trouble/Rejections: Avslag, avvisning, klage, tilsyn, ulovlighetsoppfølging, varsel om pålegg.\n"
        "Pure Admin: Ansvarsrett, godkjenning av foretak, lokal godkjenning, melding til tinglysing.\n"
        "Infrastructure: Nettstasjon, trafo, rør, graving, kabel.\n"
        "End of project: Ferdigattest, brukstillatelse (the project is already finished, no opportunity left).\n\n"
        "Output format: You must output ONLY the word 'JA' or 'NEI'. No markdown, no punctuation, no other text.\n\n"
        "TEXT:\n" + (gatekeeper_text[:15000] or "")
    )
    gatekeeper_res = generate_content_with_retry(client, GATEKEEPER_MODEL, gatekeeper_prompt)
    status = (gatekeeper_res.text or "").strip().upper()
    print(f"🎯 Gatekeeper: {status}")

    if "JA" != status:
        print("⏭️ Document not relevant to property development. Skipping expert analysis.")
        return

    # 3. Expert (Pro): up to 25 pages, use profile_text for score (1–10) and summary
    print("🧠 Running expert analysis...")
    full_context = get_pdf_text(url, max_pages=25)
    if not full_context:
        full_context = gatekeeper_text

    expert_prompt = (
        f"You are an expert analyst. Use this municipality profile as context.\n\n"
        f"PROFILE:\n{profile_text}\n\n"
        f"Extract from the document and return a single JSON object with EXACTLY these 9 keys (no other keys):\n"
        f"- title: project/case title (string)\n"
        f"- kommune: municipality name (string, e.g. Asker)\n"
        f"- gnr: gårdsnummer as string (e.g. \"12\" or \"\" if not found)\n"
        f"- bnr: bruksnummer as string (e.g. \"45\" or \"\" if not found)\n"
        f"- adresse: full gateadresse if found (string, e.g. Storgata 1, Asker), else \"\"\n"
        f"- soker: tiltakshaver/søker/ansvarlig name (string, or \"\" if not found)\n"
        f"- ai_summary: short reasoning/summary of the case in Norwegian (string, 1–3 sentences)\n"
        f"- ai_category: category of the case (string, e.g. reguleringsplan, byggesak, dispensasjon)\n"
        f"- ai_score: how relevant this is for property development, integer 0–100 (100 = highly relevant)\n\n"
        f"Return ONLY valid JSON with exactly these 9 keys. Use empty string \"\" for missing text fields.\n\n"
        f"TEXT:\n{(full_context[:40000] or '')}"
    )
    expert_res = generate_content_with_retry(
        client,
        EXPERT_MODEL,
        expert_prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    raw = (expert_res.text or "").strip()
    try:
        details = json.loads(raw)
    except json.JSONDecodeError:
        print(f"⚠️ Expert returned invalid JSON, skipping save. Raw: {raw[:200]}...")
        return

    # Normalise gnr/bnr to string
    gnr = details.get("gnr")
    bnr = details.get("bnr")
    if gnr is not None and not isinstance(gnr, str):
        gnr = str(gnr)
    if bnr is not None and not isinstance(bnr, str):
        bnr = str(bnr)
    if gnr is None:
        gnr = ""
    if bnr is None:
        bnr = ""

    # ai_score: integer 0–100
    ai_score_val = details.get("ai_score")
    if ai_score_val is not None and not isinstance(ai_score_val, int):
        try:
            ai_score_val = int(ai_score_val)
        except (TypeError, ValueError):
            ai_score_val = None
    if ai_score_val is None or not (0 <= ai_score_val <= 100):
        ai_score_val = 50

    # 4. Final save: upsert on url (deduplication). Schema: url, title, kommune, gnr, bnr, adresse, soker, ai_summary, ai_category, ai_score, is_gold, email_sent
    payload = {
        "url": url,
        "title": (details.get("title") or "").strip() or None,
        "kommune": (details.get("kommune") or "").strip() or None,
        "gnr": gnr,
        "bnr": bnr,
        "adresse": (details.get("adresse") or "").strip() or None,
        "soker": (details.get("soker") or "").strip() or None,
        "ai_summary": (details.get("ai_summary") or "").strip() or None,
        "ai_category": (details.get("ai_category") or "").strip() or None,
        "ai_score": ai_score_val,
        "is_gold": True,
        "email_sent": False,
    }
    get_supabase().table("leads").upsert(payload, on_conflict="url").execute()
    print(f"✅ Result saved: {details.get('title')}")


# --- RUN ---
if __name__ == "__main__":
    test_url = "https://fnf-nett.no/uttalelser-horinger/wp-content/uploads/sites/19/2023/03/Royken-Naeringspark-felt-D-Brev-til-Asker-kommune.pdf"
    run_full_analysis(test_url, "Asker")
