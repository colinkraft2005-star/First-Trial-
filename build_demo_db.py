#!/usr/bin/env python3
"""
build_demo_db.py
----------------
FAST, SCOPED build for the card-format demo. Instead of crawling all of D1
(~30 min, thousands of games), this fetches only the games for the teams the
demo players are on, and fills the SAME tables the app reads:

    player_game_logs   (FT%, per-game REB/AST, box scores)
    player_positions   (Guard/Wing/Big)
    shot_chart         (shot locations for the hexbin)
    fetched_games      (bookkeeping)

Reuses the exact ESPN parsing logic from build_game_logs.py / build_shot_charts.py.
Run once, then commit scouting_hub.db.

    python3 build_demo_db.py

Takes ~1-2 minutes. Nothing here scrapes Synergy or KenPom.
"""

import json
import ssl
import sqlite3
import time
import urllib.request
import requests
import warnings
from datetime import timedelta, date as date_type

warnings.filterwarnings("ignore")

DB_PATH = "scouting_hub.db"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
SUMMARY = "http://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary"
SCHEDULE = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/{tid}/schedule?season=2026"
ROSTER = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/{tid}/roster?season=2026"
TEAMS = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams?limit=400"

# Teams whose games we need for the four demo cards.
# (UCLA for Perry/Dailey/Booker; add the school of any transfer demo guy.)
DEMO_TEAM_NAMES = [
    "UCLA Bruins",
    "Texas Tech Red Raiders",   # Jaylen Petty
]


# ---------- schema (same tables the real builds create) ----------
def init_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS player_positions (
            player_name TEXT PRIMARY KEY, position_group TEXT);
        CREATE TABLE IF NOT EXISTS player_game_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_name TEXT, team_espn_id TEXT, team_name TEXT,
            opponent_espn_id TEXT, opponent_name TEXT, opp_rank INTEGER DEFAULT 999,
            game_date TEXT, min_played INTEGER DEFAULT 0, pts INTEGER DEFAULT 0,
            reb INTEGER DEFAULT 0, orb INTEGER DEFAULT 0, drb INTEGER DEFAULT 0,
            ast INTEGER DEFAULT 0, tov INTEGER DEFAULT 0, stl INTEGER DEFAULT 0,
            blk INTEGER DEFAULT 0, fg_made INTEGER DEFAULT 0, fg_att INTEGER DEFAULT 0,
            fg3_made INTEGER DEFAULT 0, fg3_att INTEGER DEFAULT 0,
            ft_made INTEGER DEFAULT 0, ft_att INTEGER DEFAULT 0, pf INTEGER DEFAULT 0,
            UNIQUE(player_name, team_espn_id, game_date));
        CREATE TABLE IF NOT EXISTS fetched_games (
            game_id TEXT PRIMARY KEY, fetched INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS shot_chart (
            play_id TEXT PRIMARY KEY, game_id TEXT, game_date TEXT, period INTEGER,
            clock TEXT, wallclock TEXT, athlete_id TEXT, player_name TEXT, team_id TEXT,
            shot_type TEXT, scoring_play INTEGER, points_attempted INTEGER,
            score_value INTEGER, coord_x REAL, coord_y REAL,
            coord_x_norm REAL, coord_y_norm REAL);
    """)
    conn.commit()


def _utc_to_pacific_date(utc_str):
    if not utc_str or 'T' not in utc_str:
        return utc_str[:10] if utc_str else ""
    try:
        date_str, time_str = utc_str.rstrip('Z').split('T')
        if int(time_str[:2]) < 8:
            return str(date_type.fromisoformat(date_str) - timedelta(days=1))
        return date_str
    except Exception:
        return utc_str[:10]


def _parse_ma(s):
    parts = str(s).split("-")
    if len(parts) == 2:
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            pass
    return 0, 0


def _si(s):
    try:
        return int(str(s).split(":")[0])
    except (ValueError, TypeError):
        return 0


def espn_team_ids(target_names):
    d = requests.get(TEAMS, timeout=15).json()
    teams = d.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])
    name_to_id = {t["team"]["displayName"]: t["team"]["id"] for t in teams}
    ids = {}
    for want in target_names:
        for name, tid in name_to_id.items():
            if want.lower() in name.lower():
                ids[name] = tid
                break
    return ids


def fetch_positions(conn, team_ids):
    pos_map = {"G": "Guard", "F": "Wing", "C": "Big"}
    rows = []
    for tid in team_ids:
        try:
            r = requests.get(ROSTER.format(tid=tid), timeout=15)
            if r.status_code == 200:
                for a in r.json().get("athletes", []):
                    name = a.get("displayName", "")
                    abbr = a.get("position", {}).get("abbreviation", "F")
                    if name:
                        rows.append((name, pos_map.get(abbr, "Wing")))
        except Exception:
            pass
        time.sleep(0.12)
    conn.executemany("INSERT OR REPLACE INTO player_positions VALUES (?,?)", rows)
    conn.commit()
    print(f"  positions: {len(rows)}")


def collect_game_ids(team_ids):
    gids = set()
    for tid in team_ids:
        try:
            r = requests.get(SCHEDULE.format(tid=tid), timeout=15)
            if r.status_code == 200:
                for ev in r.json().get("events", []):
                    gids.add(ev["id"])
        except Exception:
            pass
        time.sleep(0.15)
    return gids


def fetch_box_score(game_id):
    r = requests.get(f"{SUMMARY}?event={game_id}", timeout=15)
    if r.status_code != 200:
        return None
    d = r.json()
    game_date = _utc_to_pacific_date(
        d.get("header", {}).get("competitions", [{}])[0].get("date", ""))
    comps = d.get("header", {}).get("competitions", [{}])[0].get("competitors", [])
    id_to_name = {c["team"]["id"]: c["team"]["displayName"] for c in comps}
    team_ids = list(id_to_name.keys())
    rows = []
    for sec in d.get("boxscore", {}).get("players", []):
        team_id = sec.get("team", {}).get("id")
        team_name = sec.get("team", {}).get("displayName", "")
        opp_id = next((t for t in team_ids if t != team_id), None)
        opp_name = id_to_name.get(opp_id, "")
        for g in sec.get("statistics", []):
            idx = {lbl: i for i, lbl in enumerate(g.get("labels", []))}
            for a in g.get("athletes", []):
                stats = a.get("stats", [])
                if not stats:
                    continue
                mp = _si(stats[idx["MIN"]]) if "MIN" in idx else 0
                if mp == 0:
                    continue
                fg_m, fg_a = _parse_ma(stats[idx["FG"]]) if "FG" in idx else (0, 0)
                fg3_m, fg3_a = _parse_ma(stats[idx["3PT"]]) if "3PT" in idx else (0, 0)
                ft_m, ft_a = _parse_ma(stats[idx["FT"]]) if "FT" in idx else (0, 0)
                orb = _si(stats[idx["OREB"]]) if "OREB" in idx else 0
                drb = _si(stats[idx["DREB"]]) if "DREB" in idx else 0
                reb = _si(stats[idx["REB"]]) if "REB" in idx else (orb + drb)
                rows.append((
                    a.get("athlete", {}).get("displayName", ""), team_id, team_name,
                    opp_id, opp_name, 999, game_date, mp,
                    _si(stats[idx["PTS"]]) if "PTS" in idx else 0, reb, orb, drb,
                    _si(stats[idx["AST"]]) if "AST" in idx else 0,
                    _si(stats[idx["TO"]]) if "TO" in idx else 0,
                    _si(stats[idx["STL"]]) if "STL" in idx else 0,
                    _si(stats[idx["BLK"]]) if "BLK" in idx else 0,
                    fg_m, fg_a, fg3_m, fg3_a, ft_m, ft_a,
                    _si(stats[idx["PF"]]) if "PF" in idx else 0))
    return rows or None


def flip_coords(x, y):
    if x is None or y is None:
        return x, y
    if y > 47:
        return round(50 - x, 1), round(94 - y, 1)
    return round(float(x), 1), round(float(y), 1)


def parse_player_name(text):
    if not text:
        return None
    for kw in [" misses ", " makes "]:
        i = text.find(kw)
        if i > 0:
            return text[:i].strip()
    return None


def fetch_shots(game_id):
    req = urllib.request.Request(f"{SUMMARY}?event={game_id}", headers={"User-Agent": UA})
    try:
        raw = urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=10)
        data = json.loads(raw.read().decode("utf-8", "ignore"))
    except Exception:
        return []
    gd = None
    try:
        gd = _utc_to_pacific_date(data["header"]["competitions"][0]["date"])
    except (KeyError, IndexError):
        pass
    out = []
    for p in data.get("plays", []):
        if not p.get("shootingPlay"):
            continue
        c = p.get("coordinate") or {}
        x, y = c.get("x"), c.get("y")
        if x is None or y is None:
            continue
        xn, yn = flip_coords(x, y)
        parts = p.get("participants") or []
        aid = (parts[0].get("athlete") or {}).get("id") if parts else None
        out.append((
            p.get("id"), game_id, gd, (p.get("period") or {}).get("number"),
            (p.get("clock") or {}).get("displayValue"), p.get("wallclock"),
            aid, parse_player_name(p.get("text", "")), (p.get("team") or {}).get("id"),
            (p.get("type") or {}).get("text"), int(bool(p.get("scoringPlay"))),
            p.get("pointsAttempted"), p.get("scoreValue"),
            float(x), float(y), xn, yn))
    return out


def main():
    conn = sqlite3.connect(DB_PATH)
    init_tables(conn)

    print("1/4  resolving demo team IDs...")
    team_map = espn_team_ids(DEMO_TEAM_NAMES)
    team_ids = list(team_map.values())
    print(f"     {team_map}")

    print("2/4  positions...")
    fetch_positions(conn, team_ids)

    print("3/4  collecting demo games...")
    gids = collect_game_ids(team_ids)
    for g in gids:
        conn.execute("INSERT OR IGNORE INTO fetched_games (game_id, fetched) VALUES (?,0)", (g,))
    conn.commit()
    print(f"     {len(gids)} games")

    print("4/4  box scores + shot charts...")
    errors = 0
    for i, gid in enumerate(gids):
        try:
            box = fetch_box_score(gid)
            if box:
                conn.executemany("""
                    INSERT OR REPLACE INTO player_game_logs
                    (player_name, team_espn_id, team_name, opponent_espn_id, opponent_name,
                     opp_rank, game_date, min_played, pts, reb, orb, drb, ast, tov, stl, blk,
                     fg_made, fg_att, fg3_made, fg3_att, ft_made, ft_att, pf)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", box)
            shots = fetch_shots(gid)
            if shots:
                conn.executemany(
                    "INSERT OR IGNORE INTO shot_chart VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", shots)
            conn.execute("UPDATE fetched_games SET fetched=1 WHERE game_id=?", (gid,))
            conn.commit()
        except Exception:
            errors += 1
        time.sleep(0.2)

    pg = conn.execute("SELECT COUNT(*) FROM player_game_logs").fetchone()[0]
    sh = conn.execute("SELECT COUNT(*) FROM shot_chart").fetchone()[0]
    conn.close()
    print(f"\nDone. {pg} player-game rows, {sh} shots. Errors: {errors}")
    print("Commit scouting_hub.db and the demo shows real FT%, REB, and shot charts.")


if __name__ == "__main__":
    main()
