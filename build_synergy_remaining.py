"""Pull events for the 65 players missing from synergy_events."""
import sqlite3, requests, time, json

API_KEY   = "tUAjOnpEjl9MMZFRXEL4Yh2qQotBxcPhaoIpu3O0"
BASE_URL  = "https://api.sportradar.com/synergy/basketball/ncaamb"
SEASON_ID = "6085b5d0e6c2413bc4ba9122"
SEASON_NAME = "2021-22"
DB_PATH   = "scouting_hub.db"
HEADERS   = {"x-api-key": API_KEY}

def get(url, params=None):
    while True:
        try:
            r = requests.get(url, headers=HEADERS, params=params, timeout=20)
            if r.status_code == 429:
                print("  Rate limited, sleeping 60s...")
                time.sleep(60)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"  Error: {e}, retrying in 15s...")
            time.sleep(15)

def paginate(url, params=None):
    params = params or {}
    skip, take, results = 0, 100, []
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
        time.sleep(3)
    return results

conn = sqlite3.connect(DB_PATH)

# Get missing players
missing = conn.execute('''
    SELECT DISTINCT p.player_id, p.player_name
    FROM synergy_playtypes p
    LEFT JOIN synergy_events e ON p.player_id = e.player_id
    WHERE e.player_id IS NULL
''').fetchall()

print(f"Pulling events for {len(missing)} missing players...")
total_events = 0

for i, (player_id, player_name) in enumerate(missing):
    url = f"{BASE_URL}/seasons/{SEASON_ID}/players/{player_id}/events"
    records = paginate(url)
    rows = []
    for item in records:
        d = item.get("data", {})
        tags = [p["name"] for p in d.get("plays", [])]
        play_tags = json.dumps(tags)
        off = d.get("offense", {})
        dfn = d.get("defense", {})
        dp  = d.get("dPlayer", {})
        fg_made = 1 if any("Made" in t or "Score" in t for t in tags) else 0
        pts = 3 if any("3Pts" in t or "3pt" in t.lower() for t in tags) else (2 if fg_made else 0)
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
            fg_made, pts, play_tags,
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
    print(f"  {i+1}/{len(missing)} {player_name}: {len(rows)} events | total: {total_events:,}")
    time.sleep(3)

print(f"\nDone. {total_events:,} new events added.")
final = conn.execute("SELECT COUNT(*) FROM synergy_events").fetchone()[0]
print(f"Total synergy_events: {final:,}")
conn.close()
