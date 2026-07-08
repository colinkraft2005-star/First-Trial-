#!/bin/bash
# UCLA Basketball Analytics — one-time setup
# Run from the repo root: bash setup.sh

set -e
cd "$(dirname "$0")"

echo "================================================"
echo "  UCLA Basketball Analytics — Setup"
echo "================================================"
echo ""

# 1. Install dependencies
echo "[1/4] Installing Python dependencies..."
pip3 install -r requirements.txt -q
echo "      Done."
echo ""

# 2. Transfer portal (no auth needed)
echo "[2/4] Building transfer portal data..."
python3 build_transfer_portal.py
echo ""

# 3. Game logs — ESPN PBP (~5-10 min, incremental)
echo "[3/4] Building game logs from ESPN (~5-10 min)..."
python3 build_game_logs.py
echo ""

# 4. Lineup segments — ESPN PBP (~3-5 min, incremental)
echo "[4/4] Building 5-man lineup segments from ESPN (~3-5 min)..."
python3 build_lineup_segments.py
echo ""

echo "================================================"
echo "  Setup complete! Run the app with:"
echo "  streamlit run app.py"
echo "================================================"
echo ""
echo "  NOTE: KenPom enrichment (build_kenpom_logs.py) requires"
echo "  a paid KenPom subscription and is not run automatically."
echo "  Synergy data (build_synergy_*.py) requires Synergy access."
