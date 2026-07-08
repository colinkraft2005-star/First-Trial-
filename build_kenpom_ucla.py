#!/usr/bin/env python3
"""
build_kenpom_ucla.py

Scoped version of build_kenpom_logs.py — only discovers/fetches KenPom
player data for UCLA instead of all 362 D1 teams, so it finishes in
about a minute instead of several hours. Reuses the exact same
login/parsing logic from build_kenpom_logs.py; only Step 2 (player
discovery) is narrowed to one team.

Run once UCLA's rows already exist in player_game_logs
(build_game_logs.py must have processed UCLA's games first):
    python3 build_kenpom_ucla.py
"""

import re
import sqlite3
import urllib.parse

from build_kenpom_logs import (
    DB_PATH, KP_BASE,
    make_opener, login, get_html, strip_tags,
    build_team_rankings, scrape_player_game_logs,
)

TEAM_FILTER = "UCLA"


def discover_player_ids_scoped(conn, opener, team_filter):
    conn.execute("""CREATE TABLE IF NOT EXISTS kenpom_players (
        kp_id        INTEGER PRIMARY KEY,
        kp_name      TEXT,
        kp_team      TEXT,
        espn_team_id TEXT,
        fetched      INTEGER DEFAULT 0
    )""")
    conn.commit()

    kp_teams = conn.execute(
        "SELECT kp_name, espn_id FROM kenpom_team_rankings "
        "WHERE espn_id IS NOT NULL AND kp_name LIKE ?",
        (f"%{team_filter}%",)
    ).fetchall()
    print(f"Step 2 (scoped): matched teams = {kp_teams}")

    total_found = 0
    for kp_name, espn_id in kp_teams:
        team_url = KP_BASE + "/team.php?team=" + urllib.parse.quote_plus(kp_name)
        html = get_html(opener, team_url)

        player_links = re.findall(
            r"href=['\"]player\.php\?p=(\d+)['\"][^>]*><b?>(.*?)</b?>?</a>",
            html, re.I
        )
        player_links += re.findall(
            r"href=['\"]player\.php\?p=(\d+)['\"][^>]*>([^<]{2,40})</a>",
            html, re.I
        )
        seen = set()
        for kp_id, raw_name in player_links:
            kp_id = int(kp_id)
            name = strip_tags(raw_name).strip()
            if kp_id in seen or not name:
                continue
            seen.add(kp_id)
            conn.execute("""INSERT OR IGNORE INTO kenpom_players
                (kp_id, kp_name, kp_team, espn_team_id) VALUES (?,?,?,?)""",
                (kp_id, name, kp_name, espn_id))
            total_found += 1

    conn.commit()
    print(f"  Done. {total_found} UCLA players discovered.")


def main():
    # build_game_logs.py is running concurrently and uses rollback-journal mode, which
    # locks the whole file during writes — give this connection a real retry window
    # (Python's sqlite3 `timeout` kwarg, not just the PRAGMA) instead of failing instantly.
    conn = sqlite3.connect(DB_PATH, timeout=300.0)
    conn.execute("PRAGMA busy_timeout = 300000")
    opener = make_opener()

    print("=== build_kenpom_ucla.py (scoped to UCLA) ===")
    print("Logging into KenPom...")
    login(opener)

    build_team_rankings(conn, opener)          # fast, needed globally (opp-rank quality)
    discover_player_ids_scoped(conn, opener, TEAM_FILTER)
    scrape_player_game_logs(conn, opener)       # only finds UCLA players now

    conn.close()
    print("\n=== Complete ===")


if __name__ == "__main__":
    main()
