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
echo "[1/5] Installing Python dependencies..."
pip3 install -r requirements.txt -q
echo "      Done."
echo ""

# 2. Transfer portal (no auth needed)
echo "[2/5] Building transfer portal data..."
python3 build_transfer_portal.py
echo ""

# 3. KenPom SOS rankings
echo "[3/5] Fetching KenPom strength of schedule rankings..."
python3 build_kenpom_sos.py
echo ""

# 4. Game logs — ESPN PBP (~5-10 min, incremental)
echo "[4/5] Building game logs from ESPN (~5-10 min)..."
python3 build_game_logs.py
echo ""

# 5. Lineup segments — ESPN PBP (~3-5 min, incremental)
echo "[5/5] Building 5-man lineup segments from ESPN (~3-5 min)..."
python3 build_lineup_segments.py
echo ""

echo "================================================"
echo "  Setup complete! Run the app with:"
echo "  streamlit run app.py"
echo "================================================"
echo ""
echo "  NOTE: Synergy data (build_synergy_*.py) requires Synergy access."
