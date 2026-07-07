"""
build_lineup_segments.py

Scrapes ESPN play-by-play for all UCLA Bruins games, reconstructs exact
on-court lineup segments, and stores them in `lineup_segments`.

Each segment = one continuous stretch with the same 5 UCLA players on the floor.
Stores full counting stats for that segment so the app can compute:
  OffRtg, DefRtg, eFG%, 3P%, TOV%, OReb%, FT rate, etc.

Run once; idempotent (skips already-processed games).
"""

import sqlite3
import requests
import time

DB_PATH = "scouting_hub.db"
UCLA_TEAM_ID = "26"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

MADE_FT_TYPE = "MadeFreeThrow"
SHOT_TYPES   = {"JumpShot", "LayUpShot", "DunkShot", "TipShot", "HookShot", "FloatingJumpShot"}
TOV_TYPES    = {"Lost Ball Turnover", "Bad Pass Turnover", "Turnover"}


def init_table(conn):
    conn.execute("DROP TABLE IF EXISTS lineup_segments")
    conn.execute("""
        CREATE TABLE lineup_segments (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id       TEXT,
            game_date     TEXT,
            opponent      TEXT,
            period        INTEGER,
            clock_start   TEXT,
            clock_end     TEXT,
            seconds       REAL,
            p1 TEXT, p2 TEXT, p3 TEXT, p4 TEXT, p5 TEXT,
            -- UCLA offense in this segment
            team_fgm      INTEGER DEFAULT 0,
            team_fga      INTEGER DEFAULT 0,
            team_fg3m     INTEGER DEFAULT 0,
            team_fg3a     INTEGER DEFAULT 0,
            team_ftm      INTEGER DEFAULT 0,
            team_fta      INTEGER DEFAULT 0,
            team_orb      INTEGER DEFAULT 0,
            team_drb      INTEGER DEFAULT 0,
            team_tov      INTEGER DEFAULT 0,
            team_pts      INTEGER DEFAULT 0,
            -- Opponent offense in this segment
            opp_fgm       INTEGER DEFAULT 0,
            opp_fga       INTEGER DEFAULT 0,
            opp_fg3m      INTEGER DEFAULT 0,
            opp_fg3a      INTEGER DEFAULT 0,
            opp_ftm       INTEGER DEFAULT 0,
            opp_fta       INTEGER DEFAULT 0,
            opp_orb       INTEGER DEFAULT 0,
            opp_drb       INTEGER DEFAULT 0,
            opp_tov       INTEGER DEFAULT 0,
            opp_pts       INTEGER DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ls_game ON lineup_segments(game_id)")
    conn.commit()


def clock_to_seconds(clock_str: str, period: int) -> float:
    try:
        parts = clock_str.strip().split(":")
        mins, secs = int(parts[0]), float(parts[1])
        if period <= 2:
            return (period - 1) * 1200.0 + (1200.0 - mins * 60 - secs)
        else:
            ot = period - 2
            return 2400.0 + (ot - 1) * 300.0 + (300.0 - mins * 60 - secs)
    except Exception:
        return 0.0


def period_end_seconds(period: int) -> float:
    if period <= 2:
        return period * 1200.0
    return 2400.0 + (period - 2) * 300.0


def fetch_game_ids(dates: list) -> dict:
    """
    Match DB game dates to ESPN event IDs.
    Uses team schedule endpoint (more reliable than scoreboard date lookup).
    ESPN timestamps are UTC so may be +1 day vs local game date — we check both.
    Falls back to scoreboard for tournament games not in the regular-season schedule.
    """
    from datetime import datetime, timedelta

    # Pull the full UCLA schedule
    result = {}
    schedule = {}
    try:
        resp = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/{UCLA_TEAM_ID}/schedule",
            params={"season": "2026"}, headers=HEADERS, timeout=10,
        )
        for ev in resp.json().get("events", []):
            espn_date = ev.get("date", "")[:10]
            schedule[espn_date] = ev["id"]
    except Exception as e:
        print(f"  schedule fetch error: {e}")

    for db_date in dates:
        if db_date in schedule:
            result[db_date] = schedule[db_date]
            continue
        # Try local date + 1 day (UTC offset)
        next_day = (datetime.strptime(db_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        if next_day in schedule:
            result[db_date] = schedule[next_day]
            continue
        # Fallback: scoreboard (catches tournament/neutral-site games)
        try:
            resp = requests.get(
                "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
                params={"dates": db_date.replace("-", ""), "limit": 200},
                headers=HEADERS, timeout=10,
            )
            for ev in resp.json().get("events", []):
                ids = [c["team"]["id"] for c in ev["competitions"][0]["competitors"]]
                if UCLA_TEAM_ID in ids:
                    result[db_date] = ev["id"]
                    break
        except Exception:
            pass
        time.sleep(0.3)

    return result


def empty_counts():
    return dict(fgm=0, fga=0, fg3m=0, fg3a=0, ftm=0, fta=0, orb=0, drb=0, tov=0, pts=0)


def parse_game(event_id: str, game_date: str) -> list:
    try:
        resp = requests.get(
            "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary",
            params={"event": event_id}, headers=HEADERS, timeout=15,
        )
        data = resp.json()
    except Exception as e:
        print(f"  fetch error {event_id}: {e}")
        return []

    plays = data.get("plays", [])
    if not plays:
        return []

    # Athlete ID → name
    id_to_name = {}
    boxscore = data.get("boxscore", {})
    for grp in boxscore.get("players", []):
        for sg in grp.get("statistics", []):
            for ath in sg.get("athletes", []):
                id_to_name[ath["athlete"]["id"]] = ath["athlete"]["displayName"]

    # Opponent name
    opponent = "Unknown"
    for comp in data.get("header", {}).get("competitions", [{}]):
        for c in comp.get("competitors", []):
            if c.get("team", {}).get("id") != UCLA_TEAM_ID:
                opponent = c.get("team", {}).get("displayName", "Unknown")

    # Starters
    current_lineup = set()
    for grp in boxscore.get("players", []):
        if grp.get("team", {}).get("id") != UCLA_TEAM_ID:
            continue
        for sg in grp.get("statistics", []):
            for ath in sg.get("athletes", []):
                if ath.get("starter"):
                    name = id_to_name.get(ath["athlete"]["id"])
                    if name:
                        current_lineup.add(name)

    if not current_lineup:
        print(f"  no starters found for {event_id}")
        return []

    # UCLA home/away
    ucla_is_home = True
    for comp in data.get("header", {}).get("competitions", [{}]):
        for c in comp.get("competitors", []):
            if c.get("team", {}).get("id") == UCLA_TEAM_ID:
                ucla_is_home = (c.get("homeAway") == "home")

    # Segment state
    seg_start_clock  = "20:00"
    seg_start_period = 1
    seg_start_team_pts = 0
    seg_start_opp_pts  = 0
    seg_counts = {"team": empty_counts(), "opp": empty_counts()}
    current_period = 1

    segments = []

    def make_segment(end_clock, end_period, lineup, team_pts_now, opp_pts_now, counts):
        start_sec = clock_to_seconds(seg_start_clock, seg_start_period)
        if end_period > seg_start_period:
            end_sec = period_end_seconds(seg_start_period)
        else:
            end_sec = clock_to_seconds(end_clock, end_period)
        duration = end_sec - start_sec
        if duration < 0.5:
            return None
        players = sorted(lineup) + [None] * 5
        t = counts["team"]
        o = counts["opp"]
        return dict(
            game_id=event_id, game_date=game_date, opponent=opponent,
            period=seg_start_period, clock_start=seg_start_clock, clock_end=end_clock,
            seconds=round(duration, 1),
            p1=players[0], p2=players[1], p3=players[2], p4=players[3], p5=players[4],
            team_fgm=t["fgm"], team_fga=t["fga"], team_fg3m=t["fg3m"], team_fg3a=t["fg3a"],
            team_ftm=t["ftm"], team_fta=t["fta"], team_orb=t["orb"], team_drb=t["drb"],
            team_tov=t["tov"], team_pts=team_pts_now - seg_start_team_pts,
            opp_fgm=o["fgm"],  opp_fga=o["fga"],  opp_fg3m=o["fg3m"],  opp_fg3a=o["fg3a"],
            opp_ftm=o["ftm"],  opp_fta=o["fta"],  opp_orb=o["orb"],  opp_drb=o["drb"],
            opp_tov=o["tov"],  opp_pts=opp_pts_now - seg_start_opp_pts,
        )

    def reset_seg(clock, period, team_pts, opp_pts):
        nonlocal seg_start_clock, seg_start_period, seg_start_team_pts, seg_start_opp_pts, seg_counts
        seg_start_clock  = clock
        seg_start_period = period
        seg_start_team_pts = team_pts
        seg_start_opp_pts  = opp_pts
        seg_counts = {"team": empty_counts(), "opp": empty_counts()}

    for play in plays:
        ptype  = play.get("type", {}).get("text", "")
        period = play.get("period", {}).get("number", current_period)
        clock  = play.get("clock", {}).get("displayValue", "0:00")
        team_id = play.get("team", {}).get("id", "")

        away_pts = play.get("awayScore", 0) or 0
        home_pts = play.get("homeScore", 0) or 0
        team_pts = home_pts if ucla_is_home else away_pts
        opp_pts  = away_pts if ucla_is_home else home_pts

        # Period change — close segment at boundary
        if period != current_period:
            seg = make_segment("0:00", current_period, current_lineup, team_pts, opp_pts, seg_counts)
            if seg:
                segments.append(seg)
            reset_seg("20:00" if period <= 2 else "5:00", period, team_pts, opp_pts)
            current_period = period

        is_ucla = (team_id == UCLA_TEAM_ID)
        side    = "team" if is_ucla else "opp"

        # Substitution — close segment and update lineup
        if ptype == "Substitution":
            if team_id == UCLA_TEAM_ID:
                seg = make_segment(clock, period, current_lineup, team_pts, opp_pts, seg_counts)
                if seg:
                    segments.append(seg)
                text = play.get("text", "").lower()
                parts = play.get("participants", [])
                if parts:
                    aid  = parts[0].get("athlete", {}).get("id")
                    name = id_to_name.get(aid)
                    if name:
                        if "subbing out" in text or "out for" in text:
                            current_lineup.discard(name)
                        else:
                            current_lineup.add(name)
                reset_seg(clock, period, team_pts, opp_pts)
            continue

        c = seg_counts[side]

        # Field goals
        if play.get("shootingPlay") and ptype != MADE_FT_TYPE:
            pts_att = play.get("pointsAttempted", 2) or 2
            is_three = (pts_att == 3)
            made = play.get("scoringPlay", False)
            c["fga"] += 1
            if is_three:
                c["fg3a"] += 1
                if made:
                    c["fg3m"] += 1
            if made:
                c["fgm"] += 1

        # Free throws
        elif ptype == MADE_FT_TYPE:
            c["ftm"] += 1
            c["fta"] += 1
        elif "MissedFreeThrow" in ptype or "Missed Free Throw" in ptype:
            c["fta"] += 1

        # Turnovers
        elif any(t in ptype for t in ("Turnover", "Lost Ball", "Bad Pass")):
            c["tov"] += 1

        # Rebounds
        elif "Offensive Rebound" in ptype:
            c["orb"] += 1
        elif "Defensive Rebound" in ptype:
            c["drb"] += 1

    # Close final segment
    if plays:
        last   = plays[-1]
        lp     = last.get("period", {}).get("number", current_period)
        lc     = last.get("clock", {}).get("displayValue", "0:00")
        la_pts = last.get("awayScore", 0) or 0
        lh_pts = last.get("homeScore", 0) or 0
        lt_pts = lh_pts if ucla_is_home else la_pts
        lo_pts = la_pts if ucla_is_home else lh_pts
        seg = make_segment("0:00", lp, current_lineup, lt_pts, lo_pts, seg_counts)
        if seg:
            segments.append(seg)

    return segments


def main():
    conn = sqlite3.connect(DB_PATH)
    init_table(conn)

    dates = [
        r[0] for r in conn.execute(
            "SELECT DISTINCT game_date FROM player_game_logs WHERE team_name='UCLA Bruins' ORDER BY game_date"
        ).fetchall()
    ]
    print(f"Found {len(dates)} UCLA game dates")

    print("Fetching ESPN game IDs...")
    date_to_event = fetch_game_ids(dates)
    print(f"Matched {len(date_to_event)}/{len(dates)} games to ESPN events")

    total = 0
    for date, eid in sorted(date_to_event.items()):
        print(f"  {date} ({eid})...", end=" ", flush=True)
        segs = parse_game(eid, date)
        print(f"{len(segs)} segments")
        if segs:
            conn.executemany("""
                INSERT INTO lineup_segments
                (game_id,game_date,opponent,period,clock_start,clock_end,seconds,
                 p1,p2,p3,p4,p5,
                 team_fgm,team_fga,team_fg3m,team_fg3a,team_ftm,team_fta,
                 team_orb,team_drb,team_tov,team_pts,
                 opp_fgm,opp_fga,opp_fg3m,opp_fg3a,opp_ftm,opp_fta,
                 opp_orb,opp_drb,opp_tov,opp_pts)
                VALUES
                (:game_id,:game_date,:opponent,:period,:clock_start,:clock_end,:seconds,
                 :p1,:p2,:p3,:p4,:p5,
                 :team_fgm,:team_fga,:team_fg3m,:team_fg3a,:team_ftm,:team_fta,
                 :team_orb,:team_drb,:team_tov,:team_pts,
                 :opp_fgm,:opp_fga,:opp_fg3m,:opp_fg3a,:opp_ftm,:opp_fta,
                 :opp_orb,:opp_drb,:opp_tov,:opp_pts)
            """, segs)
            conn.commit()
            total += len(segs)
        time.sleep(0.5)

    print(f"\nDone — {total} segments across {len(date_to_event)} games.")
    conn.close()


if __name__ == "__main__":
    main()
