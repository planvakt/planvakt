import os, json, asyncio
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client
from google import genai
from google.genai import types
from datetime import datetime

from utils import generate_content_with_retry

# --- SETUP ---
_root = Path(__file__).resolve().parent.parent
load_dotenv(_root / ".env")

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

MODEL_NAME = "gemini-2.5-flash"
CONCURRENCY_LIMIT = 5
semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

async def evaluate_match(lead, profile):
    """Kreativ AI-vurdering som leter etter muligheter i stedet for å være streng."""
    async with semaphore:
        prompt = f"""
        Du er en kreativ, offensiv og fremoverlent investeringsrådgiver for en eiendomsutvikler.
        
        DOKUMENT FRA KOMMUNEN:
        Tittel: {lead.get('title', 'Ingen tittel')}
        Sammendrag: {lead.get('ai_summary', 'Ingen sammendrag')}
        Kategori: {lead.get('ai_category', 'Ukjent')}
        
        KUNDENS STRATEGI (MANDAT):
        {profile.get('ai_mandate', 'Generell utvikling')}
        
        OPPGAVE:
        Din jobb er å finne MULIGHETER for kunden, selv der de ikke er åpenbare. Vær velvillig og se etter potensiale!
        
        1. Vurder matchen (0-100). Gi en høyere score (40-100) så lenge det finnes en kreativ vinkel eller en teoretisk mulighet for kunden.
        2. Skriv en DYP OG VERDIFULL ANALYSE (ca. 50-100 ord) til kunden. Ikke gi en kort pitch, men forklar grundig:
           - Nøyaktig HVORFOR dette treffer deres strategi.
           - Hva det konkrete POTENSIALET er (f.eks. omregulering, fortetting, bruksendring).
           - Hvilke NESTE STEG de eventuelt bør ta basert på dokumentet.
        
        Returner KUN et JSON-objekt slik:
        {{"score": 85, "pitch": "Dette prosjektet treffer strategien deres fordi... Potensialet her ligger i..."}}
        """ # <-- DET VAR DISSE SOM MANGLET!
        
        try:
            res = generate_content_with_retry(
                client, MODEL_NAME, prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            data = json.loads(res.text)
            return data, profile['id'], lead['id']
        except Exception as e:
            print(f"⚠️ AI-feil under matching: {e}")
            return None, None, None

async def run_matchmaker():
    print("\n🚀 Starter Matchmaker for Lier, Asker og Oslo...")

    # 1. HENT LEADS
    # Henter leads hvor matched_at er NULL. Vi bryr oss ikke om 'processed' akkurat nå for å sikre at vi finner noe.
    print("🔍 Leter etter ubehandlede leads i databasen...")
    leads_res = supabase.table("leads").select("*").is_("matched_at", "null").execute()
    leads = leads_res.data
    
    if not leads:
        print("📭 Ingen nye leads å matche. (Tips: Alle leads har kanskje 'matched_at' fylt ut).")
        return
    else:
        print(f"✅ Fant {len(leads)} nye leads.")

    # 2. HENT PROFILER
    print("🔍 Leter etter aktive kundeprofiler...")
    profiles_res = supabase.table("search_profiles").select("*").execute()
    profiles = profiles_res.data
    
    if not profiles:
        print("❌ Fant ingen profiler i 'search_profiles'. Sjekk databasen!")
        return
    else:
        print(f"✅ Fant {len(profiles)} kundeprofiler.")

    tasks = []
    
    # 3. KRYSSSJEKK GEOGRAFI
    for lead in leads:
        lead_mun_id = lead.get('municipality_id')
        for profile in profiles:
            target_muns = profile.get('target_municipalities') or []
            
            # Sjekk om leadens kommune er i kundens liste over ønskede kommuner
            if lead_mun_id in target_muns:
                print(f"🌍 Geo-Match! Profil '{profile['name']}' følger denne kommunen. Starter AI-analyse...")
                tasks.append(evaluate_match(lead, profile))
            else:
                print(f"⏭️  Hopper over '{profile['name']}' (Følger ikke kommunen til denne leaden).")

    if not tasks:
        print("ℹ️ Ingen geografiske treff. Kommunen til leaden(e) ligger ikke i noen kunders 'target_municipalities'.")
        return

    # 4. KJØR AI-ANALYSE
    print("🧠 Spør Gemini Flash om dette er gode investeringer...")
    results = await asyncio.gather(*tasks)

    # 5. LAGRE RESULTATER OG OPPDATER LEADS
    matches_saved = 0
    matched_lead_ids = set()

    for data, p_id, l_id in results:
        if data:
            matched_lead_ids.add(l_id) # Husk at vi har behandlet denne leaden
            
            score = data.get('score', 0)
            if score >= 40:
                print(f"🔥 KANON-MATCH ({score}%): Lagrer til database for lead {l_id}...")
                try:
                    supabase.table("matches").insert({
                        "lead_id": l_id,
                        "profile_id": p_id,
                        "match_score": score,
                        "match_reason": data.get('pitch', 'God match.')
                    }).execute()
                    matches_saved += 1
                except Exception as e:
                    print(f"⚠️ Feil ved lagring i matches-tabell: {e}")
            else:
                 print(f"👎 Dårlig match ({score}%). Lagres ikke.")

    # Marker leads som ferdig matchet uansett om det ble en match > 70 eller ikke
    if matched_lead_ids:
         print(f"📝 Oppdaterer {len(matched_lead_ids)} leads som 'ferdig matchet'...")
         for l_id in matched_lead_ids:
             supabase.table("leads").update({"matched_at": datetime.now().isoformat()}).eq("id", l_id).execute()

    print(f"✅ Matchmaking fullført! Lagret {matches_saved} nye matcher.")

if __name__ == "__main__":
    asyncio.run(run_matchmaker())