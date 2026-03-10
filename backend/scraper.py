"""
Scraper module: Asker municipality 'Plan og bygg' postliste via Playwright.
Final flow: portal → Postliste plan og bygg → Søk → sort by Dokumentdato → extract first 5 rows → AI & DB.
"""

import asyncio
import io
import os
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from PyPDF2 import PdfReader
from supabase import create_client
from google import genai

from analyzer import run_full_analysis
from utils import generate_content_with_retry

# Load .env from project root (parent of backend/) or from backend/
_root = Path(__file__).resolve().parent.parent
load_dotenv(_root / ".env")

# Asker portal (fixed URL for initial navigation and for resolving relative PDF links)
ASKER_PORTAL_BASE = "https://asker-bygg.innsynsportal.no"

# Supabase & Gemini (for AI Bouncer)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
gemini_client = genai.Client(api_key=api_key)
BOUNCER_MODEL = "gemini-2.5-flash"

MAX_ROWS = 20


def url_exists_in_leads(pdf_url: str) -> bool:
    """Check if this PDF URL already exists in the leads table (deduplication)."""
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        res = supabase.table("leads").select("id").eq("url", pdf_url).execute()
        return bool(res.data and len(res.data) > 0)
    except Exception as e:
        print(f"⚠️ Error checking leads: {e}")
        return False


def get_pdf_page1_text(pdf_url: str) -> str | None:
    """Download PDF and extract text from page 1 only."""
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(pdf_url, headers=headers, stream=True, timeout=25)
        f = io.BytesIO(response.content)
        reader = PdfReader(f)
        if len(reader.pages) == 0:
            return None
        return reader.pages[0].extract_text() or None
    except Exception as e:
        print(f"⚠️ Error downloading/extracting PDF: {e}")
        return None


def is_it_gold(page1_text: str) -> bool:
    """Gemini Flash 'is_it_gold' check: return True (JA) only if real estate development potential."""
    if not page1_text:
        return False
    try:
        prompt = (
            "Goal: Identify leads with real estate development potential.\n\n"
            "SAY 'JA' ONLY IF:\n"
            "- It involves new residential or commercial buildings (nybygg).\n"
            "- It involves 'Omregulering' (rezoning) or 'Dispensasjon' (exemptions).\n"
            "- It involves dividing a property (deling av eiendom) or new plots.\n"
            "- It involves large extensions (tilbygg) that significantly increase value.\n"
            "- The title suggests something bigger than just maintenance.\n\n"
            "SAY 'NEI' IF:\n"
            "- It is only about water/sewer (vann og avløp) for existing houses.\n"
            "- It is only about minor maintenance, paint, or solar panels.\n"
            "- It is a very small project like a standard shed (bod), fence (gjerde), or minor interior changes.\n"
            "- It's a standard 'ferdigattest' (completion certificate) for a project that is already finished.\n\n"
            "Output: Always respond with ONLY 'JA' or 'NEI'.\n\n"
            "TEXT (Page 1):\n" + (page1_text[:12000] or "")
        )
        res = generate_content_with_retry(gemini_client, BOUNCER_MODEL, prompt)
        status = (res.text or "").strip().upper()
        return "JA" in status
    except Exception as e:
        print(f"⚠️ Bouncer API error: {e}")
        return False


async def run_asker_plan_og_bygg():
    """Final Asker logic: portal → Postliste plan og bygg → Søk → Dokumentdato → first 5 rows → AI & DB."""
    print(f"📍 Initial navigation: {ASKER_PORTAL_BASE}/")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            # --- Initial Navigation ---
            await page.goto(ASKER_PORTAL_BASE + "/", wait_until="networkidle", timeout=45000)
            await asyncio.sleep(2)

            # --- Step 1 - Enter Portal: click 'Postliste plan- og bygg' (regex allows dash/spaces/casing) ---
            postliste_locator = page.get_by_text(re.compile(r"Postliste plan.*bygg", re.IGNORECASE)).first
            await postliste_locator.wait_for(state="visible", timeout=15000)
            await postliste_locator.click(timeout=15000)
            await page.wait_for_load_state("networkidle", timeout=30000)
            await asyncio.sleep(2)

            # --- Step 2 - Search: click the real submit button (not 'Skjul søkefilter') ---
            await page.locator('button[type="submit"]:has-text("Søk")').first.wait_for(state="visible", timeout=15000)
            await page.locator('button[type="submit"]:has-text("Søk")').first.click(timeout=15000)
            await page.wait_for_selector("table", timeout=15000)
            await page.wait_for_load_state("networkidle", timeout=30000)
            await asyncio.sleep(2)

            # --- Step 3 - Sort: click Dokumentdato (newest first) ---
            await page.locator('button:has-text("Dokumentdato")').first.click(timeout=15000)
            await page.wait_for_load_state("networkidle", timeout=30000)
            await asyncio.sleep(2)

            # --- Step 4 - Extract: up to MAX_ROWS (newest first, already sorted by Dokumentdato) ---
            await page.locator("table tbody tr").first.wait_for(state="visible", timeout=15000)
            await asyncio.sleep(1)

            rows = await page.locator("table tbody tr").all()
            if not rows:
                print("❌ No table rows found.")
                await browser.close()
                return

            top_rows = rows[:MAX_ROWS]
            print(f"📋 Processing up to {len(top_rows)} rows (newest first).")

            for i, row in enumerate(top_rows):
                try:
                    # Only proceed if row has link with text 'Last ned'
                    if (await row.locator('a:has-text("Bestill")').count()) > 0:
                        print(f"  ⏭️ Row {i+1}: Skipped (Bestill).")
                        continue
                    if (await row.locator('a:has-text("Last ned")').count()) == 0:
                        print(f"  ⏭️ Row {i+1}: Skipped (no 'Last ned' link).")
                        continue

                    pdf_url = await row.locator('a:has-text("Last ned")').first.get_attribute("href")
                    if not pdf_url:
                        print(f"  ⏭️ Row {i+1}: Skipped (no href on 'Last ned').")
                        continue

                    # Relative URL fix: combine base URL with relative href (e.g. /file/...)
                    if not pdf_url.startswith("http"):
                        pdf_url = urljoin(ASKER_PORTAL_BASE + "/", pdf_url)

                    # Smart stop: if already in DB, we've reached previously processed docs — stop run
                    if url_exists_in_leads(pdf_url):
                        print("Found already processed document. Stopping scraper.")
                        break

                    # --- Step 5 - AI & Database: bouncer, then full analysis and save ---

                    page1_text = get_pdf_page1_text(pdf_url)
                    if not page1_text:
                        print(f"  ⏭️ Row {i+1}: Could not extract PDF text, skipping.")
                        continue

                    if not is_it_gold(page1_text):
                        print(f"  ⏭️ Row {i+1}: Bouncer said NEI, skipping.")
                        await asyncio.sleep(2)
                        continue

                    print(f"  ✅ Row {i+1}: Gull – running full analysis and saving to Supabase...")
                    try:
                        run_full_analysis(pdf_url, "Asker")
                    except Exception as e:
                        print(f"  ⚠️ Full analysis failed: {e}")

                    await asyncio.sleep(2)

                except Exception as e:
                    print(f"  ⚠️ Error processing row {i+1}: {e}")
                    continue

        finally:
            await browser.close()

    print("✅ Asker Plan og bygg scrape finished.")


def main():
    """Entry point: run the async Asker scraper."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("⚠ Mangler SUPABASE_URL eller SUPABASE_KEY i .env")
        return
    if not api_key:
        print("⚠ Mangler GOOGLE_API_KEY eller GEMINI_API_KEY i .env")
        return
    asyncio.run(run_asker_plan_og_bygg())


if __name__ == "__main__":
    main()
