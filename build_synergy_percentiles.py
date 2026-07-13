"""
Build precomputed Synergy play type percentile benchmarks per position group.
Stores sorted value lists in synergy_percentiles table for fast lookup.
Minimum possession threshold filters out tiny sample sizes.
"""

import sqlite3
import json

DB_PATH = "scouting_hub.db"

# Minimum possessions to qualify for percentile ranking
MIN_POSS = {
    "PandRBallHandler": 20,
    "PandRRollMan":     10,
    "Iso":              10,
    "PostUp":           10,
    "SpotUp":           20,
    "Cut":              10,
    "OffScreen":        8,
    "HandOff":          6,
    "Transition":       15,
}

# Stats to rank — (column, higher_is_better)
STATS = [
    ("ppp",          True),
    ("fg_pct",       True),
    ("fg_pct_eff",   True),
    ("shot2_pct",    True),
    ("shot3_pct",    True),
    ("ft_pct",       True),
    ("possessions",  True),
    ("time_percent", True),
    ("turnover",     False),  # lower is better
]

POSITION_GROUPS = ["Guard", "Wing", "Big"]

conn = sqlite3.connect(DB_PATH)

conn.execute("DROP TABLE IF EXISTS synergy_percentiles")
conn.execute("""
    CREATE TABLE synergy_percentiles (
        play_type       TEXT NOT NULL,
        position_group  TEXT NOT NULL,
        stat            TEXT NOT NULL,
        sorted_values   TEXT NOT NULL,  -- JSON array, ascending
        player_count    INTEGER,
        PRIMARY KEY (play_type, position_group, stat)
    )
""")
conn.commit()

rows_inserted = 0
for play_type, min_p in MIN_POSS.items():
    for pos_group in POSITION_GROUPS:
        # Pull qualifying players
        players = conn.execute("""
            SELECT s.player_name, s.ppp, s.fg_pct, s.fg_pct_eff,
                   s.shot2_pct, s.shot3_pct, s.ft_pct,
                   s.possessions, s.time_percent, s.turnover
            FROM synergy_playtypes s
            JOIN player_positions p ON s.player_name = p.player_name
            WHERE s.play_type = ?
              AND p.position_group = ?
              AND s.possessions >= ?
        """, (play_type, pos_group, min_p)).fetchall()

        if len(players) < 5:
            print(f"  SKIP {play_type}/{pos_group}: only {len(players)} qualifying players")
            continue

        cols = ["ppp","fg_pct","fg_pct_eff","shot2_pct","shot3_pct",
                "ft_pct","possessions","time_percent","turnover"]

        for i, (col, higher_better) in enumerate(STATS):
            if col == "turnover":
                # Store turnover rate (tov / possessions) instead of raw count
                vals = []
                for r in players:
                    tov = r[i+1]
                    poss = r[cols.index("possessions") + 1]
                    if tov is not None and poss and poss > 0:
                        vals.append(tov / poss)
            else:
                vals = [r[i+1] for r in players if r[i+1] is not None]
            vals.sort()  # ascending
            conn.execute("""
                INSERT OR REPLACE INTO synergy_percentiles
                (play_type, position_group, stat, sorted_values, player_count)
                VALUES (?,?,?,?,?)
            """, (play_type, pos_group, col, json.dumps(vals), len(vals)))
            rows_inserted += 1

conn.commit()

# Summary
print(f"\nInserted {rows_inserted} percentile benchmark rows")
print("\nSample — PandRBallHandler PPP by position:")
for row in conn.execute("""
    SELECT position_group, player_count,
           json_extract(sorted_values, '$[0]') as min_val,
           json_extract(sorted_values, '$[#-1]') as max_val
    FROM synergy_percentiles
    WHERE play_type='PandRBallHandler' AND stat='ppp'
""").fetchall():
    import json as _json
    vals = _json.loads(conn.execute(
        "SELECT sorted_values FROM synergy_percentiles WHERE play_type='PandRBallHandler' AND stat='ppp' AND position_group=?",
        (row[0],)
    ).fetchone()[0])
    median = vals[len(vals)//2]
    print(f"  {row[0]}: n={row[1]}, min={vals[0]:.3f}, median={median:.3f}, max={vals[-1]:.3f}")

conn.close()
print("\nDone.")
