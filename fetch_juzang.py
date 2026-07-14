"""
Find Johnny Juzang's player ID and download his play type data + events.
Runs with built-in rate limit handling.
"""
import requests, sqlite3, json, time

API_KEY   = "tUAjOnpEjl9MMZFRXEL4Yh2qQotBxcPhaoIpu3O0"
BASE_URL  = "https://api.sportradar.com/synergy/basketball/ncaamb"
SEASON_ID = "6085b5d0e6c2413bc4ba9122"
SEASON_NAME = "2021-22"
DB_PATH   = "scouting_hub.db"
HEADERS   = {"x-api-key": API_KEY}

PLAY_TYPES = [
    "PandRBallHandler", "PandRRollMan", "Iso", "PostUp",
    "SpotUp", "Cut", "OffScreen", "HandOff", "Transition",
]

def get(url, params=None):
    params = params or {}
    while True:
        r = requests.get(url, headers=HEADERS, params=params, timeout=20)
        if r.status_code == 429:
            print("  Rate limited, sleeping 60s...")
            time.sleep(60)
            continue
        r.raise_for_status()
        return r.json()

def paginate(url):
    skip, take, results = 0, 100, []
    while True:
        data = get(url, {"skip": skip, "take": take})
        batch = data.get("data", [])
        results.extend(batch)
        total = data.get("meta", {}).get("pagination", {}).get("totalRecords", 0)
        skip += take
        if skip >= total or not batch:
            break
        time.sleep(2)
    return results

# ── Setup tables ───────────────────────────────────────────────────────────────
conn = sqlite3.connect(DB_PATH)
conn.execute("""CREATE TABLE IF NOT EXISTS synergy_playtypes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, season TEXT, play_type TEXT,
    player_id TEXT, player_name TEXT, team_name TEXT, team_abbr TEXT, conference TEXT,
    gp INTEGER, possessions INTEGER, time_percent REAL, points INTEGER,
    ppp REAL, ppp_rank INTEGER, fg_made INTEGER, fg_miss INTEGER, fg_att INTEGER,
    fg_pct REAL, fg_pct_eff REAL, shot2_made INTEGER, shot2_miss INTEGER,
    shot2_att INTEGER, shot2_pct REAL, shot3_made INTEGER, shot3_miss INTEGER,
    shot3_att INTEGER, shot3_pct REAL, ft_made INTEGER, ft_miss INTEGER,
    ft_att INTEGER, ft_pct REAL, plus_one INTEGER, shot_foul INTEGER,
    score INTEGER, turnover INTEGER, UNIQUE(season, play_type, player_id))""")
conn.execute("""CREATE TABLE IF NOT EXISTS synergy_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, season TEXT, player_id TEXT NOT NULL,
    player_name TEXT NOT NULL, event_id TEXT, game_quarter INTEGER, clock TEXT,
    shot_x REAL, shot_y REAL, pick_and_roll INTEGER, foul_shot INTEGER,
    hard_double INTEGER, zone INTEGER, short_clock INTEGER, press INTEGER,
    sob INTEGER, eob INTEGER, ato INTEGER, is_home INTEGER,
    ft_made INTEGER, ft_att INTEGER, fg_made INTEGER, points INTEGER,
    play_tags TEXT, offense_team TEXT, defense_team TEXT,
    d_player_name TEXT, d_player_id TEXT, UNIQUE(season, player_id, event_id))""")
conn.execute("""CREATE TABLE IF NOT EXISTS player_positions (
    player_name TEXT PRIMARY KEY, position_group TEXT)""")
conn.commit()

# ── Step 1: Find Juzang's player ID ───────────────────────────────────────────
print("Searching for Johnny Juzang...")
player_id = None
player_name = None
skip = 0
while player_id is None:
    data = get(f"{BASE_URL}/seasons/{SEASON_ID}/players", {"skip": skip, "take": 100})
    players = data.get("data", [])
    total = data.get("meta", {}).get("pagination", {}).get("totalRecords", 0)
    for p in players:
        if "juzang" in p.get("name", "").lower():
            player_id   = p.get("id") or p.get("_id")
            player_name = p.get("name")
            print(f"Found: {player_name} (id={player_id})")
            break
    if player_id:
        break
    skip += 100
    if skip >= total:
        print(f"Not found after {total} players.")
        break
    print(f"  Checked {skip}/{total}...")
    time.sleep(2)

if not player_id:
    print("Could not find Juzang. Exiting.")
    conn.close()
    exit(1)

# ── Step 2: Play types ─────────────────────────────────────────────────────────
print(f"\nPulling play types for {player_name}...")
for play_type in PLAY_TYPES:
    data = get(f"{BASE_URL}/seasons/{SEASON_ID}/players/{player_id}/playTypes/{play_type}")
    d = data.get("data", {})
    if not d or not d.get("possessions"):
        print(f"  {play_type}: no data")
        time.sleep(1)
        continue
    team     = d.get("team", {})
    shooting = d.get("shooting", {})
    fg       = shooting.get("fg", {})
    shot2    = shooting.get("fg2", {})
    shot3    = shooting.get("fg3", {})
    ft       = shooting.get("ft", {})
    conn.execute("""INSERT OR REPLACE INTO synergy_playtypes
        (season,play_type,player_id,player_name,team_name,team_abbr,conference,
         gp,possessions,time_percent,points,ppp,ppp_rank,
         fg_made,fg_miss,fg_att,fg_pct,fg_pct_eff,
         shot2_made,shot2_miss,shot2_att,shot2_pct,
         shot3_made,shot3_miss,shot3_att,shot3_pct,
         ft_made,ft_miss,ft_att,ft_pct,
         plus_one,shot_foul,score,turnover)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (SEASON_NAME, play_type, player_id, player_name,
         team.get("name","UCLA"), team.get("abbreviation","UCLA"), team.get("conference","Pac-12"),
         d.get("gamesPlayed"), d.get("possessions"), d.get("timePercent"),
         d.get("points"), d.get("ppp"), d.get("pppRank"),
         fg.get("made"), fg.get("miss"), fg.get("attempt"), fg.get("pct"), fg.get("pctEff"),
         shot2.get("made"), shot2.get("miss"), shot2.get("attempt"), shot2.get("pct"),
         shot3.get("made"), shot3.get("miss"), shot3.get("attempt"), shot3.get("pct"),
         ft.get("made"), ft.get("miss"), ft.get("attempt"), ft.get("pct"),
         d.get("plusOne"), d.get("shotFoul"), d.get("score"), d.get("turnover")))
    conn.commit()
    print(f"  {play_type}: {d.get('possessions')} poss, {d.get('ppp',0):.3f} PPP")
    time.sleep(1.5)

# ── Step 3: Events ─────────────────────────────────────────────────────────────
print(f"\nPulling events for {player_name}...")
records = paginate(f"{BASE_URL}/seasons/{SEASON_ID}/players/{player_id}/events")
rows = []
for item in records:
    d = item.get("data", {})
    tags = [pl["name"] for pl in d.get("plays", [])]
    fg_made = 1 if any("Made" in t or "Score" in t for t in tags) else 0
    pts = 3 if any("3Pts" in t or "3pt" in t.lower() for t in tags) else (2 if fg_made else 0)
    off, dfn, dp = d.get("offense",{}), d.get("defense",{}), d.get("dPlayer",{})
    rows.append((SEASON_NAME, player_id, player_name,
        d.get("id"), d.get("gameQuarter"), d.get("clock"),
        d.get("shotX"), d.get("shotY"),
        int(d.get("pickAndRoll",False)), int(d.get("foulShot",False)),
        int(d.get("hardDouble",False)), int(d.get("zone",False)),
        int(d.get("shortClock",False)), int(d.get("press",False)),
        int(d.get("sob",False)), int(d.get("eob",False)),
        int(d.get("ato",False)), int(d.get("isHome",False)),
        d.get("ftMade",0), d.get("ftAttempt",0),
        fg_made, pts, json.dumps(tags),
        off.get("name"), dfn.get("name"), dp.get("name"), dp.get("id")))
if rows:
    conn.executemany("""INSERT OR IGNORE INTO synergy_events
        (season,player_id,player_name,event_id,game_quarter,clock,
         shot_x,shot_y,pick_and_roll,foul_shot,hard_double,zone,
         short_clock,press,sob,eob,ato,is_home,ft_made,ft_att,
         fg_made,points,play_tags,offense_team,defense_team,d_player_name,d_player_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    conn.commit()
print(f"  {len(rows)} events saved")

# ── Step 4: Position ───────────────────────────────────────────────────────────
conn.execute("INSERT OR REPLACE INTO player_positions (player_name, position_group) VALUES (?,?)",
             (player_name, "Wing"))
conn.commit()
conn.close()
print(f"\nDone. {player_name} fully loaded.")
