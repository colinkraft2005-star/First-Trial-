# UCLA Basketball Analytics

Internal scouting and analytics platform for the UCLA basketball staff.

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/colinkraft2005-star/First-Trial-.git
cd First-Trial-

# 2. Run setup (builds the database — takes ~10-15 min first time)
bash setup.sh

# 3. Launch the app
streamlit run app.py
```

Then open **http://localhost:8501** in your browser.

## What Setup Does

| Step | Script | Time | Notes |
|------|--------|------|-------|
| Install deps | `requirements.txt` | ~1 min | |
| Transfer portal | `build_transfer_portal.py` | ~1 min | Pulls from srating.io |
| Game logs | `build_game_logs.py` | ~5-10 min | ESPN box scores, incremental |
| Lineup segments | `build_lineup_segments.py` | ~3-5 min | ESPN PBP, incremental |

## Re-running After Updates

Setup scripts are **incremental** — they skip games already in the database. Just run `bash setup.sh` again to pick up new games.

## Credentials Required (not in setup.sh)

- **KenPom** — `build_kenpom_logs.py` — requires paid KenPom login
- **Synergy** — `build_synergy_*.py` — requires Synergy Sports access

Contact Matt for credentials.

## App Tabs

| Tab | Description |
|-----|-------------|
| Player Card | Individual player profiles with BartTorvik stats |
| Depth Chart | UCLA roster depth chart with clickable player cards |
| One Pager | Single-page team overview |
| Portal Discovery Engine | Filter 2026 transfer portal by any stat |
| Front Office Target Board | Internal target tracking and notes |
| Big Board Print View | Print-ready player cards |
| Player Card / Ranking System | Full scout grade cards with historical comps |
