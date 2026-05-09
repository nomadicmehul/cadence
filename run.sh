#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "→ Creating virtualenv (.venv)..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "→ Installing dependencies..."
pip install -q -r requirements.txt

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
  cp .env.example .env
  echo "→ Created .env (edit it to add your ANTHROPIC_API_KEY, or set it in Settings later)."
fi

echo
python app.py
