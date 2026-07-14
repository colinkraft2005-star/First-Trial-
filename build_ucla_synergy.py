"""
Pull Synergy 2021-22 play type data for UCLA players only and store in scouting_hub.db.
Finds UCLA's team ID, pulls the roster, then scrapes play types + events for each player.
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
HEADERS   = {"x-api-key": API_KEY}

PLAY_TYPES = [
    "PandRBallHandler", "PandRRollMan", "Iso", "PostUp",
    "SpotUp", "Cut", "OffScreen", "HandOff", "Transition",
]

def get(url, params=None, retries=5):
    params = params or {}
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=20)
            if r.status_code == 429:
                wait = 60 * (attempt + 1)
                print(f"  Rate limited, sleeping {wait}s...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"  Error: {e}, retrying in 15s...")
            time.sleep(15)
    return {}

def paginate(url, params=None):
    params = params or {}
    skip, take, results = 0, 100, []
    while True:
        params.update({"skip": skip, "take": take})
        data = get(url, params)
        batch = data.get("data", [])
        results.extend(batch)
        total = data.get("meta", {}).get("pagination", {}).get("totalRecords", 0)
        skip += take
        if skip >= total or not batch:
            break
        time.sleep(2)
    return results

# ── Setup DB tables ────────────────────────────────────────────────────────────
conn = sqlite3.connect(DB_PATH)

conn.execute("""
    CREATE TABLE IF NOT EXISTS synergy_playtypes (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        season        TEXT,
        play_type     TEXT,
        player_id     TEXT,
        player_name   TEXT,
        team_name     TEXT,
        team_abbr     TEXT,
        conference    TEXT,
        gp            INTEGER,
        possessions   INTEGER,
        time_percent  REAL,
        points        INTEGER,
        ppp           REAL,
        ppp_rank      INTEGER,
        fg_made       INTEGER,
        fg_miss       INTEGER,
        fg_att        INTEGER,
        fg_pct        REAL,
        fg_pct_eff    REAL,
        shot2_made    INTEGER,
        shot2_miss    INTEGER,
        shot2_att     INTEGER,
        shot2_pct     REAL,
        shot3_made    INTEGER,
        shot3_miss    INTEGER,
        shot3_att     INTEGER,
        shot3_pct     REAL,
        ft_made       INTEGER,
        ft_miss       INTEGER,
        ft_att        INTEGER,
        ft_pct        REAL,
        plus_one      INTEGER,
        shot_foul     INTEGER,
        score         INTEGER,
        turnover      INTEGER,
        UNIQUE(season, play_type, player_id)
    )
""")

conn.execute("""
    CREATE TABLE IF NOT EXISTS synergy_events (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        season        TEXT,
        player_id     TEXT NOT NULL,
        player_name   TEXT NOT NULL,
        event_id      TEXT,
        game_quarter  INTEGER,
        clock         TEXT,
        shot_x        REAL,
        shot_y        REAL,
        pick_and_roll INTEGER,
        foul_shot     INTEGER,
        hard_double   INTEGER,
        zone          INTEGER,
        short_clock   INTEGER,
        press         INTEGER,
        sob           INTEGER,
        eob           INTEGER,
        ato           INTEGER,
        is_home       INTEGER,
        ft_made       INTEGER,
        ft_att        INTEGER,
        fg_made       INTEGER,
        points        INTEGER,
        play_tags     TEXT,
        offense_team  TEXT,
        defense_team  TEXT,
        d_player_name TEXT,
        d_player_id   TEXT,
        UNIQUE(season, player_id, event_id)
    )
""")

conn.execute("""
    CREATE TABLE IF NOT EXISTS player_positions (
        player_name    TEXT PRIMARY KEY,
        position_group TEXT
    )
""")

conn.commit()

# ── Step 1: Find UCLA team ─────────────────────────────────────────────────────
print("Finding UCLA team...")
time.sleep(5)
teams_data = paginate(f"{BASE_URL}/seasons/{SEASON_ID}/teams")
ucla_team = None
for t in teams_data:
    name = t.get("name", "")
    if "ucla" in name.lower() or ("california" in name.lower() and "los angeles" in name.lower()):
        ucla_team = t
        break

if not ucla_team:
    # Try searching by known abbreviation
    for t in teams_data:
        if t.get("abbreviation", "").upper() == "UCLA":
            ucla_team = t
            break

if not ucla_team:
    print(f"Could not find UCLA. Teams found: {[t.get('name') for t in teams_data[:20]]}")
    exit(1)

TEAM_ID = ucla_team.get("id") or ucla_team.get("_id")
print(f"Found UCLA: {ucla_team.get('name')} (id={TEAM_ID})")

# ── Step 2: Get UCLA roster ────────────────────────────────────────────────────
print("\nFetching UCLA roster...")
time.sleep(3)
roster_data = get(f"{BASE_URL}/seasons/{SEASON_ID}/teams/{TEAM_ID}/players")
players = roster_data.get("data", [])
print(f"Found {len(players)} players on UCLA roster")
for p in players:
    print(f"  {p.get('name')} (id={p.get('id') or p.get('_id')})")

# ── Step 3: Pull play types for each player ────────────────────────────────────
print("\nPulling play type stats...")
total_pt_rows = 0

for p in players:
    player_id   = p.get("id") or p.get("_id")
    player_name = p.get("name", "")

    for play_type in PLAY_TYPES:
        url = f"{BASE_URL}/seasons/{SEASON_ID}/players/{player_id}/playTypes/{play_type}"
        data = get(url)
        d = data.get("data", {})
        if not d or not d.get("possessions"):
            time.sleep(1)
            continue

        team      = d.get("team", {})
        stats     = d.get("stats", d)
        shooting  = d.get("shooting", {})
        shot2     = shooting.get("fg2", {})
        shot3     = shooting.get("fg3", {})
        ft        = shooting.get("ft", {})
        fg        = shooting.get("fg", {})

        conn.execute("""
            INSERT OR REPLACE INTO synergy_playtypes
            (season, play_type, player_id, player_name, team_name, team_abbr, conference,
             gp, possessions, time_percent, points, ppp, ppp_rank,
             fg_made, fg_miss, fg_att, fg_pct, fg_pct_eff,
             shot2_made, shot2_miss, shot2_att, shot2_pct,
             shot3_made, shot3_miss, shot3_att, shot3_pct,
             ft_made, ft_miss, ft_att, ft_pct,
             plus_one, shot_foul, score, turnover)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            SEASON_NAME, play_type, player_id, player_name,
            team.get("name", "UCLA"), team.get("abbreviation", "UCLA"),
            team.get("conference", "Pac-12"),
            d.get("gamesPlayed"), d.get("possessions"), d.get("timePercent"),
            d.get("points"), d.get("ppp"), d.get("pppRank"),
            fg.get("made"), fg.get("miss"), fg.get("attempt"), fg.get("pct"), fg.get("pctEff"),
            shot2.get("made"), shot2.get("miss"), shot2.get("attempt"), shot2.get("pct"),
            shot3.get("made"), shot3.get("miss"), shot3.get("attempt"), shot3.get("pct"),
            ft.get("made"), ft.get("miss"), ft.get("attempt"), ft.get("pct"),
            d.get("plusOne"), d.get("shotFoul"), d.get("score"), d.get("turnover"),
        ))
        conn.commit()
        total_pt_rows += 1
        print(f"  {player_name} / {play_type}: {d.get('possessions')} poss, {d.get('ppp', 0):.3f} PPP")
        time.sleep(1.5)

print(f"\nPlay type rows inserted: {total_pt_rows}")

# ── Step 4: Pull events (shot chart) for each player ──────────────────────────
print("\nPulling events...")
total_events = 0

for i, p in enumerate(players):
    player_id   = p.get("id") or p.get("_id")
    player_name = p.get("name", "")

    url = f"{BASE_URL}/seasons/{SEASON_ID}/players/{player_id}/events"
    records = paginate(url)
    rows = []
    for item in records:
        d = item.get("data", {})
        tags = [pl["name"] for pl in d.get("plays", [])]
        fg_made = 1 if any("Made" in t or "Score" in t for t in tags) else 0
        pts = 3 if any("3Pts" in t or "3pt" in t.lower() for t in tags) else (2 if fg_made else 0)
        off = d.get("offense", {})
        dfn = d.get("defense", {})
        dp  = d.get("dPlayer", {})
        rows.append((
            SEASON_NAME, player_id, player_name,
            d.get("id"), d.get("gameQuarter"), d.get("clock"),
            d.get("shotX"), d.get("shotY"),
            int(d.get("pickAndRoll", False)), int(d.get("foulShot", False)),
            int(d.get("hardDouble", False)), int(d.get("zone", False)),
            int(d.get("shortClock", False)), int(d.get("press", False)),
            int(d.get("sob", False)), int(d.get("eob", False)),
            int(d.get("ato", False)), int(d.get("isHome", False)),
            d.get("ftMade", 0), d.get("ftAttempt", 0),
            fg_made, pts, json.dumps(tags),
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
    print(f"  {i+1}/{len(players)} {player_name}: {len(rows)} events")
    time.sleep(3)

# ── Step 5: Add UCLA players to player_positions ───────────────────────────────
print("\nSetting position groups for UCLA players...")

# Manual UCLA 2021-22 position assignments
UCLA_POSITIONS = {
    "Johnny Juzang":     "Wing",
    "Tyger Campbell":    "Guard",
    "Jaylen Clark":      "Wing",
    "Jaime Jaquez Jr.":  "Wing",
    "Jules Bernard":     "Wing",
    "Cody Riley":        "Big",
    "Myles Johnson":     "Big",
    "David Singleton":   "Guard",
    "Kenneth Nwuba":     "Big",
    "Mac Etienne":       "Big",
    "Peyton Watson":     "Wing",
    "Will McClendon":    "Guard",
    "Dylan Andrews":     "Guard",
}

for p in players:
    name = p.get("name", "")
    pos  = UCLA_POSITIONS.get(name)
    if not pos:
        # fallback by position field from API if available
        api_pos = p.get("position", "")
        if api_pos in ("G", "PG", "SG"):
            pos = "Guard"
        elif api_pos in ("C", "PF"):
            pos = "Big"
        else:
            pos = "Wing"
    conn.execute(
        "INSERT OR REPLACE INTO player_positions (player_name, position_group) VALUES (?,?)",
        (name, pos)
    )
    print(f"  {name} → {pos}")

conn.commit()
conn.close()

print(f"\nDone. {total_pt_rows} play type rows, {total_events} events.")
