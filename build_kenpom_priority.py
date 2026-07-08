#!/usr/bin/env python3
"""
build_kenpom_priority.py

Runs Step 3 of build_kenpom_logs.py (the slow per-player game-log scrape)
for P5 conference teams only, first. Everyone else stays with fetched=0,
so a later plain `python3 build_kenpom_logs.py` run will automatically
pick up exactly where this left off and finish the rest of D1 — no data
is redone, nothing is lost, this just re-orders the queue.

Run once Step 1 + Step 2 of build_kenpom_logs.py have already populated
kenpom_team_rankings and kenpom_players (they have, from the earlier
full-D1 run):
    python3 build_kenpom_priority.py
"""

import sqlite3
import requests
import warnings

import build_kenpom_logs
from build_kenpom_logs import (
    DB_PATH, make_opener, login, get_html, parse_player_game_logs,
)

warnings.filterwarnings("ignore")

# Cut the courtesy delay between requests (default 3.5s) to speed this up while
# actively watching it run. Not dropping it to zero / going concurrent — that
# risks tripping KenPom's bot detection and getting the whole account blocked,
# which would be worse than just running slower.
build_kenpom_logs.DELAY = 2.0

P5_CONFS = {"ACC", "B10", "B12", "BE", "SEC"}


def get_p5_espn_ids(conn):
    """Live BartTorvik fetch → CONF per team → match to team_rankings.bart_name → espn_id."""
    url = "https://barttorvik.com/getadvstats.php?year=2026&page=playerstat&json=1"
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://barttorvik.com/"}
    data = requests.get(url, headers=headers, verify=False, timeout=20).json()

    team_conf = {}
    for row in data:
        if len(row) > 2:
            team_conf[str(row[1])] = str(row[2])

    p5_bart_names = {t for t, c in team_conf.items() if c in P5_CONFS}

    rows = conn.execute("SELECT espn_id, bart_name FROM team_rankings").fetchall()
    p5_espn_ids = {espn_id for espn_id, bart_name in rows if bart_name in p5_bart_names}
    return p5_espn_ids


def scrape_scoped(conn, opener, espn_id_allowlist):
    placeholders = ",".join("?" * len(espn_id_allowlist))
    players = conn.execute(f"""
        SELECT kp.kp_id, kp.kp_name, kp.espn_team_id
        FROM kenpom_players kp
        WHERE kp.fetched = 0
          AND kp.espn_team_id IN ({placeholders})
          AND EXISTS (
              SELECT 1 FROM player_game_logs p
              WHERE p.team_espn_id = kp.espn_team_id
          )
        ORDER BY kp.kp_id
    """, list(espn_id_allowlist)).fetchall()

    total = len(players)
    print(f"Priority pass: {total} P5 players to fetch")

    errors = 0
    for idx, (kp_id, kp_name, espn_team_id) in enumerate(players):
        url = f"https://kenpom.com/player.php?p={kp_id}"
        try:
            html = get_html(opener, url)
        except Exception:
            errors += 1
            conn.execute("UPDATE kenpom_players SET fetched = -1 WHERE kp_id = ?", (kp_id,))
            if idx % 50 == 0:
                conn.commit()
            continue

        game_logs = parse_player_game_logs(html)
        for g in game_logs:
            conn.execute("""
                UPDATE player_game_logs
                SET ortg_kp    = ?,
                    usage_kp   = ?,
                    kp_opp_rank = COALESCE(kp_opp_rank, ?)
                WHERE team_espn_id = ?
                  AND game_date    = ?
                  AND (
                      player_name = ?
                      OR LOWER(REPLACE(player_name, "'", "")) =
                         LOWER(REPLACE(?, "'", ""))
                  )
            """, (
                g["ortg_kp"], g["usage_kp"], g["kp_opp_rank"],
                espn_team_id, g["game_date"],
                kp_name, kp_name,
            ))

        conn.execute("UPDATE kenpom_players SET fetched = 1 WHERE kp_id = ?", (kp_id,))

        if (idx + 1) % 50 == 0:
            conn.commit()
            pct = (idx + 1) * 100 // total
            print(f"  {idx+1}/{total} ({pct}%) — {errors} errors")

    conn.commit()
    print(f"\nDone. {total - errors}/{total} P5 players fetched. Errors: {errors}")


def main():
    conn = sqlite3.connect(DB_PATH, timeout=120.0)
    conn.execute("PRAGMA busy_timeout = 120000")
    opener = make_opener()

    print("=== build_kenpom_priority.py (P5 conferences first) ===")
    print("Logging into KenPom...")
    login(opener)

    p5_ids = get_p5_espn_ids(conn)
    print(f"P5 teams matched: {len(p5_ids)}")

    scrape_scoped(conn, opener, p5_ids)

    conn.close()
    print("\n=== Complete — run `python3 build_kenpom_logs.py` again later to finish the rest of D1 ===")


if __name__ == "__main__":
    main()
