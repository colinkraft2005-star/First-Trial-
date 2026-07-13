"""
Scrape Synergy Basketball NCAAMB API and store play type data in scouting_hub.db.
Pulls all 9 play types for every player in the available season (2021-22 trial).
Also pulls per-possession events with shot coordinates and play tags.
"""

import sqlite3
import requests
import time
import json

API_KEY   = "tUAjOnpEjl9MMZFRXEL4Yh2qQotBxcPhaoIpu3O0"
BASE_URL  = "https://api.sportradar.com/synergy/basketball/ncaamb"
SEASON_ID = "6085b5d0e6c2413bc4ba9122"  # 2021-22
SEASON_NAME = "2021-22"
DB_PATH   = "scouting_hub.db"

PLAY_TYPES = [
    "PandRBallHandler",
    "PandRRollMan",
    "Iso",
    "PostUp",
    "SpotUp",
    "Cut",
    "OffScreen",
    "HandOff",
    "Transition",
]

HEADERS = {"x-api-key": API_KEY}


def get(url, params=None, retries=3):
    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=15)
            if r.status_code == 429:
                print("  Rate limited, sleeping 30s...")
                time.sleep(30)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i == retries - 1:
                print(f"  ERROR: {e}")
                return None
            time.sleep(2)
    return None


def paginate(url, params=None):
    params = params or {}
    skip, take = 0, 100
    results = []
    while True:
        params.update({"skip": skip, "take": take})
        data = get(url, params)
        if not data:
            break
        batch = data.get("data", [])
        results.extend(batch)
        total = data.get("meta", {}).get("pagination", {}).get("totalRecords", 0)
        skip += take
        if skip >= total:
            break
        time.sleep(0.3)
    return results


def setup_db(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS synergy_playtypes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season TEXT NOT NULL,
            play_type TEXT NOT NULL,
            player_id TEXT NOT NULL,
            player_name TEXT NOT NULL,
            team_name TEXT,
            team_abbr TEXT,
            conference TEXT,
            gp INTEGER,
            possessions INTEGER,
            time_percent REAL,
            points INTEGER,
            ppp REAL,
            ppp_rank INTEGER,
            fg_made INTEGER,
            fg_miss INTEGER,
            fg_att INTEGER,
            fg_pct REAL,
            fg_pct_eff REAL,
            shot2_made INTEGER,
            shot2_miss INTEGER,
            shot2_att INTEGER,
            shot2_pct REAL,
            shot3_made INTEGER,
            shot3_miss INTEGER,
            shot3_att INTEGER,
            shot3_pct REAL,
            ft_made INTEGER,
            ft_miss INTEGER,
            ft_att INTEGER,
            ft_pct REAL,
            plus_one INTEGER,
            shot_foul INTEGER,
            score INTEGER,
            turnover INTEGER,
            UNIQUE(season, play_type, player_id)
        );

        CREATE TABLE IF NOT EXISTS synergy_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season TEXT NOT NULL,
            player_id TEXT NOT NULL,
            player_name TEXT NOT NULL,
            event_id TEXT UNIQUE,
            game_quarter INTEGER,
            clock INTEGER,
            shot_x REAL,
            shot_y REAL,
            pick_and_roll INTEGER,
            foul_shot INTEGER,
            hard_double INTEGER,
            zone INTEGER,
            short_clock INTEGER,
            press INTEGER,
            sob INTEGER,
            eob INTEGER,
            ato INTEGER,
            is_home INTEGER,
            ft_made INTEGER,
            ft_att INTEGER,
            fg_made INTEGER,
            points INTEGER,
            play_tags TEXT,
            offense_team TEXT,
            defense_team TEXT,
            d_player_name TEXT,
            d_player_id TEXT
        );

        CREATE TABLE IF NOT EXISTS synergy_players (
            player_id TEXT PRIMARY KEY,
            player_name TEXT,
            team_name TEXT,
            team_abbr TEXT,
            team_id TEXT,
            season TEXT
        );
    """)
    conn.commit()


def scrape_playtypes(conn):
    url = f"{BASE_URL}/seasons/{SEASON_ID}/events/reports/playerplaytypestats"
    for pt in PLAY_TYPES:
        print(f"  Scraping play type: {pt}...")
        records = paginate(url, {"playType": pt})
        rows = []
        for item in records:
            d = item.get("data", {})
            s = d.get("stats", {})
            p = d.get("player", {})
            t = d.get("team", {})
            rows.append((
                SEASON_NAME, pt,
                p.get("id", ""), p.get("name", ""),
                t.get("fullName", ""), t.get("abbr", ""),
                t.get("division", {}).get("name", ""),
                s.get("gp"), s.get("possessions"), s.get("timePercent"),
                s.get("points"), s.get("ppp"), s.get("pppRank"),
                s.get("fgMade"), s.get("fgMiss"), s.get("fgAttempt"), s.get("fgPercent"), s.get("fgPercentEffective"),
                s.get("shot2Made"), s.get("shot2Miss"), s.get("shot2Attempt"), s.get("shot2Percent"),
                s.get("shot3Made"), s.get("shot3Miss"), s.get("shot3Attempt"), s.get("shot3Percent"),
                s.get("ftMade"), s.get("ftMiss"), s.get("ftAttempt"), s.get("ftPercent"),
                s.get("plusOne"), s.get("shotFoul"), s.get("score"), s.get("turnover"),
            ))
        conn.executemany("""
            INSERT OR REPLACE INTO synergy_playtypes
            (season, play_type, player_id, player_name, team_name, team_abbr, conference,
             gp, possessions, time_percent, points, ppp, ppp_rank,
             fg_made, fg_miss, fg_att, fg_pct, fg_pct_eff,
             shot2_made, shot2_miss, shot2_att, shot2_pct,
             shot3_made, shot3_miss, shot3_att, shot3_pct,
             ft_made, ft_miss, ft_att, ft_pct,
             plus_one, shot_foul, score, turnover)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, rows)
        conn.commit()
        print(f"    -> {len(rows)} players saved")
        time.sleep(0.5)


def scrape_players(conn):
    print("  Scraping player roster...")
    url = f"{BASE_URL}/playercareers"
    # Just get players from the play type data we already have
    rows = conn.execute(
        "SELECT DISTINCT player_id, player_name, team_name, team_abbr FROM synergy_playtypes WHERE season=?",
        (SEASON_NAME,)
    ).fetchall()
    conn.executemany("""
        INSERT OR IGNORE INTO synergy_players (player_id, player_name, team_name, team_abbr, season)
        VALUES (?,?,?,?,?)
    """, [(r[0], r[1], r[2], r[3], SEASON_NAME) for r in rows])
    conn.commit()
    print(f"    -> {len(rows)} players indexed")


def scrape_events(conn, skip_ids=None):
    print("  Scraping per-possession events...")
    skip_ids = skip_ids or set()
    # Get all unique players
    players = conn.execute(
        "SELECT DISTINCT player_id, player_name FROM synergy_playtypes WHERE season=?",
        (SEASON_NAME,)
    ).fetchall()
    players = [(pid, pname) for pid, pname in players if pid not in skip_ids]

    total_events = 0
    for i, (player_id, player_name) in enumerate(players):
        url = f"{BASE_URL}/seasons/{SEASON_ID}/players/{player_id}/events"
        records = paginate(url)
        rows = []
        for item in records:
            d = item.get("data", {})
            play_tags = json.dumps([p["name"] for p in d.get("plays", [])])
            off = d.get("offense", {})
            dfn = d.get("defense", {})
            dp  = d.get("dPlayer", {})
            op  = d.get("oPlayer", {})
            # determine made/points from play tags
            tags = [p["name"] for p in d.get("plays", [])]
            fg_made = 1 if any("Made" in t or "Score" in t for t in tags) else 0
            pts = 3 if any("3Pts" in t or "3pt" in t.lower() for t in tags) else (2 if fg_made else 0)
            rows.append((
                SEASON_NAME, player_id, player_name,
                d.get("id"),
                d.get("gameQuarter"), d.get("clock"),
                d.get("shotX"), d.get("shotY"),
                int(d.get("pickAndRoll", False)),
                int(d.get("foulShot", False)),
                int(d.get("hardDouble", False)),
                int(d.get("zone", False)),
                int(d.get("shortClock", False)),
                int(d.get("press", False)),
                int(d.get("sob", False)),
                int(d.get("eob", False)),
                int(d.get("ato", False)),
                int(d.get("isHome", False)),
                d.get("ftMade", 0), d.get("ftAttempt", 0),
                fg_made, pts,
                play_tags,
                off.get("name"), dfn.get("name"),
                dp.get("name"), dp.get("id"),
            ))
        if rows:
            conn.executemany("""
                INSERT OR IGNORE INTO synergy_events
                (season, player_id, player_name, event_id, game_quarter, clock,
                 shot_x, shot_y, pick_and_roll, foul_shot, hard_double, zone,
                 short_clock, press, sob, eob, ato, is_home,
                 ft_made, ft_att, fg_made, points, play_tags,
                 offense_team, defense_team, d_player_name, d_player_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, rows)
            conn.commit()
        total_events += len(rows)
        if (i + 1) % 20 == 0:
            print(f"    {i+1}/{len(players)} players | {total_events:,} events so far")
        time.sleep(1.5)
    print(f"    -> {total_events:,} total events saved")


if __name__ == "__main__":
    print("Connecting to DB...")
    conn = sqlite3.connect(DB_PATH)
    setup_db(conn)

    # Skip players already scraped
    already_done = set(r[0] for r in conn.execute(
        "SELECT DISTINCT player_id FROM synergy_events"
    ).fetchall())
    print(f"\n1. Scraping per-possession events — {len(already_done)} already done, resuming...")
    scrape_events(conn, skip_ids=already_done)

    # Summary
    pt_count = conn.execute("SELECT COUNT(*) FROM synergy_playtypes").fetchone()[0]
    ev_count = conn.execute("SELECT COUNT(*) FROM synergy_events").fetchone()[0]
    pl_count = conn.execute("SELECT COUNT(*) FROM synergy_players").fetchone()[0]
    print(f"\nDone.")
    print(f"  synergy_playtypes: {pt_count:,} rows")
    print(f"  synergy_events:    {ev_count:,} rows")
    print(f"  synergy_players:   {pl_count:,} rows")

    conn.close()
