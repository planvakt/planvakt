"""
Day 8 Matchmaker: Fetch gold leads not yet emailed, score against investment criteria with Gemini,
send Resend email when score > 80, then mark email_sent = True.
"""

import os
import json
import html
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from supabase import create_client
from google import genai
from google.genai import types
import resend

from utils import generate_content_with_retry

# --- SETUP ---
_root = Path(__file__).resolve().parent.parent
load_dotenv(_root / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL") or os.getenv("TEIGVIS_EMAIL")  # Your email to receive alerts
RESEND_FROM = os.getenv("RESEND_FROM")  # e.g. "TeigVis <onboarding@resend.dev>" or your verified domain
LOGO_URL = os.getenv("TEIGVIS_LOGO_URL") or os.getenv("LOGO_URL")  # Optional: URL to logo image for email

# Investment criteria for matching (set in .env as INVESTMENT_CRITERIA or edit default)
INVESTMENT_CRITERIA = os.getenv(
    "INVESTMENT_CRITERIA",
    "New housing projects, land development, or property splitting in Asker",
)

MODEL_NAME = "gemini-2.5-flash"
MATCH_THRESHOLD = 80


def get_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def ai_match_check(lead: dict) -> tuple[int | None, str | None, str | None, str]:
    """Use Gemini 2.5 Flash to score lead vs criteria. Returns (score, reason_nb, analysis_norwegian, lokasjon) or (None, None, None, "").
    All text in the response MUST be in Norwegian (Bokmål). Also extracts address/property identifier for Maps."""
    client = genai.Client(api_key=GEMINI_API_KEY)
    title = lead.get("title") or "Untitled"
    analysis = lead.get("ai_summary") or lead.get("ai_analysis") or "Ingen sammendrag."

    prompt = f"""Du er en investeringsrådgiver. Svara KUN på norsk (Bokmål).

INVESTMENTSKRITERIER:
{INVESTMENT_CRITERIA}

SAKE TITTEL: {title}

ORIGINAL ANALYSE/SAMMENDRAG (kan være på engelsk eller norsk):
{analysis}

OPPGAVE:
1. Vurder hvor godt saken matcher kriteriene (0–100). Gi et heltall.
2. Skriv en kort begrunnelse (1–3 setninger) for matchen. Skriv ALLTID på profesjonell norsk (Bokmål).
3. Lever et «sammendrag av saken» på norsk (Bokmål). Hvis originalanalysen er på engelsk, OVERSETT den til norsk. Hvis den allerede er på norsk, omskriv/oppsummer kort på god norsk. Ingen engelsk i svaret.
4. Identifiser konkret adresse eller eiendomsbetegnelse fra analysen (f.eks. "Storgata 1, Asker" eller "Gnr 10, Bnr 5 i Asker"). Hvis ingen finnes, bruk tom streng "".

Returner KUN et JSON-objekt med nøyaktig disse nøklene:
- "match_score" (tall 0–100)
- "match_reason" (streng, på norsk)
- "sammendrag_norsk" (streng, hele analysen/sammendraget på norsk)
- "lokasjon" (streng: adresse eller gnr/bnr i Asker, eller "" hvis ukjent)

Eksempel: {{"match_score": 85, "match_reason": "Ny boligutbygging i Asker.", "sammendrag_norsk": "Saken gjelder reguleringsplan...", "lokasjon": "Gnr 12, Bnr 45 i Asker"}}
"""

    try:
        res = generate_content_with_retry(
            client,
            MODEL_NAME,
            prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        data = json.loads((res.text or "").strip())
        score = data.get("match_score")
        reason = (data.get("match_reason") or "").strip()
        sammendrag = (data.get("sammendrag_norsk") or "").strip()
        lokasjon = (data.get("lokasjon") or "").strip()
        if score is not None and 0 <= score <= 100:
            return int(score), reason or "Ingen begrunnelse.", sammendrag or "Sammendrag ikke tilgjengelig.", lokasjon
        return None, None, None, ""
    except Exception as e:
        print(f"⚠️ AI match check failed for lead {lead.get('id')}: {e}")
        return None, None, None, ""


def _email_title_from_lead(lead: dict) -> str:
    """H1 title priority: 1) Gateadresse, 2) Gnr X, Bnr Y, Kommune, 3) Saksittel."""
    addr = (lead.get("property_address") or "").strip()
    if addr:
        return addr
    gnr, bnr = lead.get("gnr"), lead.get("bnr")
    kommune = (lead.get("kommune") or "").strip()
    if gnr is not None and bnr is not None:
        part = f"Gnr {gnr}, Bnr {bnr}"
        return f"{part}, {kommune}" if kommune else part
    return lead.get("title") or "Untitled"


def _maps_query_from_lead(lead: dict, ai_lokasjon: str = "") -> str:
    """Location for Google Maps: property_address, else Gnr/Bnr + Kommune, else AI lokasjon."""
    addr = (lead.get("property_address") or "").strip()
    if addr:
        return addr
    gnr, bnr = lead.get("gnr"), lead.get("bnr")
    kommune = (lead.get("kommune") or "").strip()
    if gnr is not None and bnr is not None:
        part = f"Gnr {gnr}, Bnr {bnr}"
        return f"{part}, {kommune}" if kommune else part
    return (ai_lokasjon or "").strip()


def send_teigvis_email(lead: dict, score: int, reason_norwegian: str, analysis_norwegian: str, lokasjon: str = "") -> bool:
    """Send email via Resend. Light theme, professional Norwegian. Returns True if sent successfully."""
    if not RESEND_API_KEY or not NOTIFY_EMAIL or not RESEND_FROM:
        print("⚠️ Missing RESEND_API_KEY, NOTIFY_EMAIL, or RESEND_FROM in environment.")
        return False
    resend.api_key = RESEND_API_KEY

    lead_url = lead.get("url") or "#"
    email_h1_title = _email_title_from_lead(lead)
    maps_query = _maps_query_from_lead(lead, lokasjon)
    address_found = maps_query or "Ikke angitt"
    maps_url = f"https://www.google.com/maps/search/?api=1&query={quote(maps_query)}" if maps_query else ""
    maps_button_html = f'<a href="{html.escape(maps_url)}" style="background-color: #f0f2f5; color: #333333; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block; border: 1px solid #dcdcdc; margin-left: 10px; margin-bottom: 10px;" target="_blank">Se i Google Maps</a>' if maps_url else ""

    applicant_name = (lead.get("applicant_name") or "").strip() or "Ikke angitt"
    org_nr = (lead.get("org_nr") or "").strip()
    proff_q = org_nr or applicant_name if applicant_name != "Ikke angitt" else ""
    proff_url = f"https://www.proff.no/bransjesøk?q={quote(proff_q)}" if proff_q else ""
    proff_section_html = f'<p style="margin-top: 12px;"><a href="{html.escape(proff_url)}" style="background-color: #f0f2f5; color: #333333; padding: 10px 20px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block; border: 1px solid #dcdcdc;" target="_blank">Sjekk selskap på Proff.no</a></p>' if proff_url else ""

    subject = f"TeigVis Match: {email_h1_title[:40]}{'...' if len(email_h1_title) > 40 else ''}"

    html_body = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(subject)}</title>
  <style>
    .button-primary {{ background-color: #007bff; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block; }}
    .button-secondary {{ background-color: #f0f2f5; color: #333333; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block; border: 1px solid #dcdcdc; }}
    .info-box {{ background-color: #f9f9f9; border: 1px solid #e0e0e0; padding: 20px; border-radius: 8px; margin-bottom: 25px; }}
    .label {{ font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #666666; margin-bottom: 5px; font-weight: 600; }}
  </style>
</head>
<body style="margin: 0; padding: 20px; background-color: #f4f4f4; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;">
  <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; padding: 40px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.05);">

    <h1 style="color: #1a1a1a; margin-top: 0; line-height: 1.2;">{html.escape(email_h1_title)}</h1>

    <div style="background-color: #f9f9f9; border: 1px solid #e0e0e0; padding: 20px; border-radius: 8px; margin-bottom: 25px;">
      <div style="font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #666666; margin-bottom: 8px; font-weight: 600;">Søker</div>
      <p style="margin: 0 0 6px 0; font-size: 16px; color: #333333;">{html.escape(applicant_name)}</p>
      <p style="margin: 0; font-size: 16px; color: #333333;">Org.nr: {html.escape(org_nr or "—")}</p>
      {proff_section_html}
    </div>

    <div style="background-color: #eef6fc; border: 1px solid #d0e3f0; padding: 20px; border-radius: 8px; margin-bottom: 25px;">
      <div style="font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #007bff; margin-bottom: 5px; font-weight: 600;">Hvorfor dette er en match (Score: {score}/100)</div>
      <p style="margin: 0; font-size: 16px; color: #2c3e50;">{html.escape(reason_norwegian)}</p>
    </div>

    <div style="background-color: #f9f9f9; border: 1px solid #e0e0e0; padding: 20px; border-radius: 8px; margin-bottom: 25px;">
      <div style="font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #666666; margin-bottom: 5px; font-weight: 600;">Lokasjon</div>
      <p style="margin: 0; font-size: 16px; font-weight: 500; color: #333333;">{html.escape(address_found)}</p>
    </div>

    <h3 style="color: #1a1a1a; border-bottom: 2px solid #f4f4f4; padding-bottom: 15px; margin-top: 35px;">Dypdykk og Analyse</h3>
    <p style="font-size: 15px; line-height: 1.6; color: #444444; white-space: pre-wrap;">{html.escape(analysis_norwegian)}</p>

    <div style="margin-top: 40px; text-align: center;">
      <a href="{html.escape(lead_url)}" style="background-color: #007bff; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block; margin-right: 10px; margin-bottom: 10px;">Åpne saksdokumentet</a>{maps_button_html}
    </div>

    <p style="margin-top: 50px; font-size: 12px; color: #999999; text-align: center; border-top: 1px solid #eee; padding-top: 20px;">
      Dette varselet ble sendt automatisk av TeigVis basert på dine kriterier.
    </p>
  </div>
</body>
</html>
"""

    try:
        params = {
            "from": RESEND_FROM,
            "to": [NOTIFY_EMAIL],
            "subject": subject,
            "html": html_body.strip(),
        }
        resend.Emails.send(params)
        return True
    except Exception as e:
        print(f"⚠️ Resend send failed: {e}")
        return False


def run_matchmaker():
    print("\n🚀 Day 8 Matchmaker: gold leads → AI match → email if score > 80\n")

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ Missing SUPABASE_URL or SUPABASE_SERVICE_KEY in environment.")
        return
    if not GEMINI_API_KEY:
        print("❌ Missing GEMINI_API_KEY (or GOOGLE_API_KEY) in environment.")
        return

    supabase = get_supabase()

    # 1. Fetch leads where email_sent is FALSE and is_gold is TRUE
    print("🔍 Fetching leads where email_sent = FALSE and is_gold = TRUE...")
    try:
        r = supabase.table("leads").select("*").eq("email_sent", False).eq("is_gold", True).execute()
        leads = r.data or []
    except Exception as e:
        print(f"❌ Supabase error: {e}")
        return

    if not leads:
        print("📭 No gold leads pending email.")
        return
    print(f"✅ Found {len(leads)} lead(s) to evaluate.\n")

    criteria_preview = INVESTMENT_CRITERIA[:60] + "..." if len(INVESTMENT_CRITERIA) > 60 else INVESTMENT_CRITERIA
    print(f"📋 Criteria: {criteria_preview}\n")

    emails_sent = 0
    for lead in leads:
        lead_id = lead.get("id")
        title = lead.get("title") or "Untitled"
        print(f"  Evaluating: {title[:50]}...")

        score, reason, analysis_nb, lokasjon = ai_match_check(lead)
        if score is None:
            continue
        print(f"    Score: {score} — {reason[:60]}...")

        if score <= MATCH_THRESHOLD:
            print(f"    Score <= {MATCH_THRESHOLD}, skipping email.")
            continue

        if send_teigvis_email(lead, score, reason, analysis_nb or "", lokasjon or ""):
            try:
                supabase.table("leads").update({"email_sent": True}).eq("id", lead_id).execute()
                emails_sent += 1
                print(f"    ✅ Email sent and email_sent set to TRUE.")
            except Exception as e:
                print(f"    ⚠️ Email sent but DB update failed: {e}")
        else:
            print(f"    ⚠️ Email not sent; email_sent left FALSE.")

    print(f"\n✅ Matchmaker finished. Emails sent: {emails_sent}.")


if __name__ == "__main__":
    run_matchmaker()
