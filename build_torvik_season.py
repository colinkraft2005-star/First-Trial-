#!/usr/bin/env python3
"""
Build the season-long BartTorvik player stat table (PLAYER/TEAM/CONF/PPG/ORTG/etc,
everything df_all is built from in app.py) into scouting_hub.db as torvik_player_season.

Why this exists: app.py used to call barttorvik.com's getadvstats endpoint live on every
app startup (cached only 1 hour, per-process). That's fine for one person running the app,
but every coach running their own local copy is a separate process with its own cache -
five people opening the app around the same time is five near-simultaneous live hits to
Torvik, which is what triggered the rate limiting. Freezing this into the db (like
team_rankings, player_game_logs, cbb_player_agg already are) means the running app never
has to call Torvik directly - it just reads the local table.

Run once, or re-run whenever you want to refresh the season numbers:
    python3 build_torvik_season.py
"""

import sqlite3
import time
import warnings

import pandas as pd
import requests

warnings.filterwarnings("ignore")

DB_PATH = "scouting_hub.db"


def fetch_barttorvik_safe(top_filter=None, retries=3, delay_between_requests=4):
    base_url = "https://barttorvik.com/getadvstats.php?year=2026&page=playerstat&json=1"
    url = base_url if top_filter is None else f"{base_url}&top={top_filter}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://barttorvik.com/",
    }
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=headers, verify=False, timeout=20)
            if response.text.strip():
                raw_data = response.json()

                def safe_float(row_list, idx):
                    try:
                        if idx < len(row_list) and row_list[idx] is not None and str(row_list[idx]).strip() != "":
                            return float(row_list[idx])
                        return 0.0
                    except (ValueError, TypeError, IndexError):
                        return 0.0

                cleaned_rows = []
                for row in raw_data:
                    if len(row) < 53:
                        continue
                    cleaned_rows.append({
                        "PLAYER":      str(row[0]),
                        "TEAM":        str(row[1]),
                        "CONF":        str(row[2]),
                        "GP":          int(row[3]) if row[3] else 0,
                        "MIN_PCT":     safe_float(row, 4),
                        "MPG":         safe_float(row, 54),
                        "PPG":         safe_float(row, 63) if len(row) > 63 else 0.0,
                        "APG":         safe_float(row, 60) if len(row) > 60 else 0.0,
                        "RPG":         safe_float(row, 59) if len(row) > 59 else 0.0,
                        "ORTG":        safe_float(row, 5),
                        "USG":         safe_float(row, 6),
                        "EFG":         safe_float(row, 7),
                        "TS":          safe_float(row, 8),
                        "OR":          safe_float(row, 9),
                        "DR":          safe_float(row, 10),
                        "AST":         safe_float(row, 11),
                        "TO":          safe_float(row, 12),
                        "BLK":         safe_float(row, 22),
                        "STL":         safe_float(row, 23),
                        "FTR":         safe_float(row, 24),
                        "FT_PCT":      safe_float(row, 15) * 100,
                        "TWO_P":       safe_float(row, 18) * 100,
                        "THREE_P":     safe_float(row, 21) * 100,
                        "THREE_P_100": safe_float(row, 65) if len(row) > 65 else 0.0,
                        "CLASS":       str(row[25]) if len(row) > 25 else "",
                        "HEIGHT":      str(row[26]) if len(row) > 26 else "",
                        "POS_TAG":     str(row[64]) if len(row) > 64 else "",
                        "PRPG":        safe_float(row, 28),
                        "BPM":         safe_float(row, 50),
                        "OBPM":        safe_float(row, 51),
                        "DBPM":        safe_float(row, 52),
                        "SOS":         safe_float(row, 34),
                    })
                return pd.DataFrame(cleaned_rows)
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(delay_between_requests)
    return None


def main():
    print("Fetching season player stats from BartTorvik...")
    df = fetch_barttorvik_safe(top_filter=None)
    if df is None or df.empty:
        print("Fetch failed - torvik_player_season not updated. Try again in a bit.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.execute("DROP TABLE IF EXISTS torvik_player_season")
    df.to_sql("torvik_player_season", conn, index=False)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS torvik_player_season_meta (fetched_at TEXT)"
    )
    conn.execute("DELETE FROM torvik_player_season_meta")
    conn.execute(
        "INSERT INTO torvik_player_season_meta (fetched_at) VALUES (?)",
        (time.strftime("%Y-%m-%d %H:%M:%S"),),
    )
    conn.commit()

    from build_game_logs import reconcile_player_names
    print("Reconciling player name spellings against the refreshed season data...")
    reconcile_player_names(conn)

    conn.close()
    print(f"torvik_player_season: {len(df)} rows written.")


if __name__ == "__main__":
    main()
