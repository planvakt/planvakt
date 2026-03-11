import io, json, os, requests
from pathlib import Path
from dotenv import load_dotenv
from PyPDF2 import PdfReader
from supabase import create_client
from google import genai
from google.genai import types

from utils import generate_content_with_retry

# --- 1. SETUP ---
_root = Path(__file__).resolve().parent.parent
load_dotenv(_root / ".env")

api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

GATEKEEPER_MODEL = "gemini-2.5-flash"
EXPERT_MODEL = "gemini-2.5-pro"

# --- AUTO-DISCOVERY: find municipality by name (no .env ID) ---
def get_municipality_by_name(name):
    """Search municipalities table for a record where name matches the input (e.g. 'Asker').
    Returns (id, profile_text) or (None, None)."""
    try:
        res = supabase.table("municipalities").select("id, profile_text").eq("name", name.strip()).execute()
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
        "You must answer with exactly one word: JA or NEI. "
        "Say JA only if this document is relevant to property development (eiendomsutvikling). "
        "Otherwise say NEI.\n\nTEXT:\n" + (gatekeeper_text[:15000] or "")
    )
    gatekeeper_res = generate_content_with_retry(
        client, GATEKEEPER_MODEL, gatekeeper_prompt,
    )
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
        f"You are an expert analyst. Use this municipality profile as context for scoring and summarising.\n\n"
        f"PROFILE:\n{profile_text}\n\n"
        f"Analyse the document and extract the following. Return a single JSON object with these keys:\n\n"
        f"1. Lokalisering (prioritet):\n"
        f"   - property_address (string eller null): Full gateadresse hvis funnet (f.eks. 'Storgata 1, Asker'). Søk etter adresse først.\n"
        f"   - Hvis ingen adresse: gnr (integer eller null) = gårdsnummer, bnr (integer eller null) = bruksnummer, kommune (string eller null) = kommunenavn.\n"
        f"   - gnr_bnr (string eller null): Formatert som 'Gnr X, Bnr Y' hvis du har gnr/bnr, ellers null.\n"
        f"2. Søker: applicant_name (string eller null) = tiltakshaver/søker/ansvarlig. org_nr (string eller null) = organisasjonsnummer (kun siffer).\n"
        f"3. Analyse: prosjekt_navn (string), score (integer 1–10), beskrivelse (string sammendrag), kategori (string).\n\n"
        f"Returner KUN JSON med nøklene: prosjekt_navn, score, beskrivelse, gnr_bnr, kategori, property_address, gnr, bnr, kommune, applicant_name, org_nr.\n\n"
        f"TEXT:\n{(full_context[:40000] or '')}"
    )
    expert_res = generate_content_with_retry(
        client, EXPERT_MODEL, expert_prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    raw = (expert_res.text or "").strip()
    try:
        details = json.loads(raw)
    except json.JSONDecodeError:
        print(f"⚠️ Expert returned invalid JSON, skipping save. Raw: {raw[:200]}...")
        return

    gnr, bnr = details.get("gnr"), details.get("bnr")
    if gnr is not None and bnr is not None and not details.get("gnr_bnr"):
        details["gnr_bnr"] = f"Gnr {gnr}, Bnr {bnr}"

    # 4. Final save: upsert on url so we don't get duplicate leads
    payload = {
        "url": url,
        "title": details.get("prosjekt_navn"),
        "ai_summary": details.get("beskrivelse"),
        "ai_category": details.get("kategori"),
        "ai_score": details.get("score"),
        "gnr_bnr": details.get("gnr_bnr"),
        "municipality_id": m_id,
        "property_address": details.get("property_address"),
        "gnr": gnr,
        "bnr": bnr,
        "kommune": details.get("kommune"),
        "applicant_name": details.get("applicant_name"),
        "org_nr": details.get("org_nr"),
    }
    supabase.table("leads").upsert(payload, on_conflict="url").execute()
    print(f"✅ Result saved: {details.get('prosjekt_navn')}")


# --- RUN ---
if __name__ == "__main__":
    test_url = "https://fnf-nett.no/uttalelser-horinger/wp-content/uploads/sites/19/2023/03/Royken-Naeringspark-felt-D-Brev-til-Asker-kommune.pdf"
    run_full_analysis(test_url, "Asker")
