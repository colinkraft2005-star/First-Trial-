"""
Match Synergy players to BartTorvik position groups (Guard/Wing/Big)
and insert into player_positions table.
Uses BartTorvik 2021-22 season data to match against Synergy 2021-22 players.
"""

import sqlite3
import requests
import time

DB_PATH = "scouting_hub.db"

POS_TAG_BUCKET = {
    "Scoring PG": "Guard", "Pure PG": "Guard", "Combo G": "Guard",
    "Wing G": "Wing",  "Wing F": "Wing",  "Stretch 4": "Wing",
    "PF/C": "Big",     "C": "Big",
}

def fetch_barttorvik(year=2022):
    url = f"https://barttorvik.com/getadvstats.php?year={year}&page=playerstat&json=1"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://barttorvik.com/"
    }
    for attempt in range(3):
        try:
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            data = r.json()
            print(f"  BartTorvik {year}: {len(data)} players fetched")
            return data
        except Exception as e:
            print(f"  Attempt {attempt+1} failed: {e}")
            time.sleep(3)
    return []

def normalize(name):
    return name.lower().strip().replace(".", "").replace("'", "").replace("-", " ")

conn = sqlite3.connect(DB_PATH)

# Get all Synergy players
synergy_players = conn.execute(
    "SELECT DISTINCT player_id, player_name FROM synergy_playtypes"
).fetchall()
print(f"Synergy players to match: {len(synergy_players)}")

# Fetch BartTorvik 2021-22
print("Fetching BartTorvik 2021-22 data...")
bt_data = fetch_barttorvik(2022)

# Build lookup: normalized_name -> position_group
bt_lookup = {}
for row in bt_data:
    try:
        name = row[0]
        pos_tag = row[64] if len(row) > 64 else ""
        bucket = POS_TAG_BUCKET.get(pos_tag)
        if name and bucket:
            bt_lookup[normalize(name)] = bucket
    except Exception:
        continue

print(f"BartTorvik position lookup: {len(bt_lookup)} players with known positions")

# Match and insert
matched, unmatched = 0, 0
rows = []
for player_id, player_name in synergy_players:
    key = normalize(player_name)
    bucket = bt_lookup.get(key)
    if bucket:
        rows.append((player_name, bucket))
        matched += 1
    else:
        unmatched += 1

conn.executemany("""
    INSERT OR IGNORE INTO player_positions (player_name, position_group)
    VALUES (?, ?)
""", rows)
conn.commit()

print(f"\nMatched: {matched} | Unmatched: {unmatched}")
print(f"\nPosition breakdown:")
for row in conn.execute("""
    SELECT position_group, COUNT(*)
    FROM player_positions
    WHERE player_name IN (SELECT DISTINCT player_name FROM synergy_playtypes)
    GROUP BY position_group
""").fetchall():
    print(f"  {row[0]}: {row[1]} players")

conn.close()
