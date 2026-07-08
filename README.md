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

`scouting_hub.db` is *not* committed to the repo (it's a large binary file, well over GitHub's
100MB limit for a normal push) — everyone builds their own local copy by running `setup.sh`.

## What Setup Does

| Step | Script | Time | Notes |
|------|--------|------|-------|
| Install deps | `requirements.txt` | ~1 min | |
| Transfer portal | `build_transfer_portal.py` | ~1 min | Pulls from srating.io |
| Game logs | `build_game_logs.py` | ~5-10 min (full D1: several hours) | ESPN box scores, incremental |
| Lineup segments | `build_lineup_segments.py` | ~3-5 min | ESPN PBP, incremental |

Both scripts are **incremental** — they skip games already in the database, so re-running
`setup.sh` after an update is fast. For KenPom, run `build_kenpom_priority.py` (P5 conferences
first, resumable) or `build_kenpom_logs.py` (full D1, several hours) — not part of `setup.sh`
since it needs a paid KenPom login.

## Credentials Required (not in setup.sh)

- **KenPom** — `build_kenpom_logs.py` — requires paid KenPom login
- **Synergy** — `build_synergy_*.py` — requires Synergy Sports access

Contact Matt for credentials.

## App Tabs

| Tab | Description |
|-----|-------------|
| Player Card | Any player's full profile — general stats, percentile-ranked BartTorvik/Synergy breakdown, shot chart, and a comp finder weighted by real shot-selection data |
| Depth Chart | UCLA roster depth chart with clickable player cards |
| One Pager | Single-page team overview |
| Portal Discovery Engine | Filter 2026 transfer portal by any stat |
| Front Office Target Board | Internal target tracking and notes |
| Big Board Print View | Print-ready player cards |
