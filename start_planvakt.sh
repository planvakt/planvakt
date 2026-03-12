#!/usr/bin/env bash
# Planvakt: én kommando for venv, install, playwright og skraper.
# Kjør fra prosjektrot: ./start_planvakt.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="venv"
if [ ! -d "$VENV_DIR" ]; then
  echo "📦 Oppretter venv i $VENV_DIR ..."
  python3 -m venv "$VENV_DIR"
fi

echo "🔌 Aktiverer venv ..."
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

echo "📥 Installerer avhengigheter fra requirements.txt ..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "🌐 Installerer Playwright (Chromium) ..."
playwright install chromium

echo "🚀 Starter skraper (backend/scraper.py) ..."
python backend/scraper.py
