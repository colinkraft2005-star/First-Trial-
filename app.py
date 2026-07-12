import streamlit as st
import pandas as pd
import requests
import sqlite3
import urllib.parse
import re
import math
import ssl
import urllib3
import time
import bisect
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Arc, Circle, FancyArrow, Rectangle
from datetime import datetime

P5_CONFS = {"ACC", "B10", "B12", "BE", "SEC"}

# ==========================================
# LOCAL MAC SSL OVERRIDE
# ==========================================
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass

st.set_page_config(layout="wide", page_title="UCLA Basketball", page_icon="🏀")

# ==========================================
# GLOBAL CSS — remove Streamlit whitespace + style header
# ==========================================
st.markdown("""
<style>
/* Kill all Streamlit default chrome and whitespace */
[data-testid="stHeader"] { display: none !important; }
[data-testid="stToolbar"] { display: none !important; }
[data-testid="stDecoration"] { display: none !important; }
section[data-testid="stMain"] > div { padding-top: 0 !important; }
.block-container {
    padding-top: 0 !important;
    padding-left: 3rem !important;
    padding-right: 3rem !important;
    padding-bottom: 2rem !important;
    max-width: 100% !important;
}

/* UCLA header bar — negative margins bleed past block-container padding */
#ucla-header {
    background: #2774AE;
    padding: 10px 3rem;
    display: flex;
    align-items: center;
    gap: 14px;
    width: calc(100% + 6rem);
    box-sizing: border-box;
    margin-left: -3rem;
    margin-right: -3rem;
    position: sticky;
    top: 0;
    z-index: 9999;
    box-shadow: 0 2px 8px rgba(0,0,0,0.25);
}
#ucla-header img { height: 48px; width: auto; }
#ucla-header-title {
    color: white;
    font-size: 20px;
    font-weight: 700;
    letter-spacing: 0.3px;
    white-space: nowrap;
}

/* Tab bar — negative margins bleed past block-container padding */
[data-testid="stTabs"] { margin-top: 0 !important; }
[data-baseweb="tab-list"] {
    background: #2774AE !important;
    padding: 0 3rem !important;
    gap: 0 !important;
    width: calc(100% + 6rem) !important;
    margin-left: -3rem !important;
    border-bottom: none !important;
    box-sizing: border-box !important;
}
[data-baseweb="tab"] {
    color: rgba(255,255,255,0.7) !important;
    font-weight: 600 !important;
    font-size: 13px !important;
    padding: 10px 18px !important;
    border-radius: 0 !important;
    border-bottom: 3px solid transparent !important;
    background: transparent !important;
}
[data-baseweb="tab"]:hover {
    color: white !important;
    background: rgba(0,0,0,0.12) !important;
}
[aria-selected="true"][data-baseweb="tab"] {
    color: #FFD100 !important;
    border-bottom: 3px solid #FFD100 !important;
    background: rgba(0,0,0,0.15) !important;
}
[data-testid="stTabPanel"] {
    padding-top: 1rem !important;
}

/* Collapse spacing between depth chart cards */
[data-testid="stColumn"] .element-container {
    margin-bottom: 0 !important;
    padding-bottom: 0 !important;
}
[data-testid="stColumn"] iframe {
    display: block !important;
    margin: 0 !important;
}
[data-testid="stColumn"] [data-testid="stVerticalBlock"] {
    gap: 4px !important;
}
</style>
""", unsafe_allow_html=True)


# ==========================================
# DATABASE INIT
# ==========================================
def init_db():
    conn = sqlite3.connect('scouting_hub.db')
    cursor = conn.cursor()
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS player_notes
                   (
                       player_name  TEXT PRIMARY KEY,
                       team_name    TEXT,
                       scout_name   TEXT,
                       priority_tier TEXT,
                       position     TEXT,
                       role         TEXT,
                       rumored_nil  TEXT,
                       personal_val TEXT,
                       agent        TEXT,
                       agency       TEXT,
                       photo_url    TEXT,
                       eval_date    TEXT,
                       notes        TEXT,
                       value_tag    TEXT
                   )
                   ''')
    # Migrate player_notes tables created before value_tag existed
    notes_cols = {row[1] for row in cursor.execute("PRAGMA table_info(player_notes)").fetchall()}
    if "value_tag" not in notes_cols:
        cursor.execute("ALTER TABLE player_notes ADD COLUMN value_tag TEXT")
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS roster
                   (
                       id          INTEGER PRIMARY KEY AUTOINCREMENT,
                       player_name TEXT,
                       position    TEXT,
                       depth       INTEGER,
                       descriptor  TEXT,
                       bt_name     TEXT,
                       height      TEXT,
                       class_yr    TEXT
                   )
                   ''')
    # Migrate roster tables created before height/class_yr existed
    roster_cols = {row[1] for row in cursor.execute("PRAGMA table_info(roster)").fetchall()}
    if "height" not in roster_cols:
        cursor.execute("ALTER TABLE roster ADD COLUMN height TEXT")
    if "class_yr" not in roster_cols:
        cursor.execute("ALTER TABLE roster ADD COLUMN class_yr TEXT")
    conn.commit()
    conn.close()


def seed_roster_if_empty():
    """Pre-load the 26-27 UCLA roster on first run only."""
    conn = sqlite3.connect('scouting_hub.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM roster")
    count = cursor.fetchone()[0]
    if count == 0:
        # (player_name, position, depth, descriptor, bt_name)
        # bt_name = exact BartTorvik spelling for stat linking; "" = no stats (freshman/walk-on)
        seed = [
            # PG
            ("Trent Perry",      "PG", 1, "13 PPG / 59.5 TS%",            "Trent Perry"),
            ("Stink Robinson",   "PG", 2, "4.5% STL rate / 43.3% from 3", ""),
            ("Markell Alston",   "PG", 3, "Rs-Fr",                         ""),
            # CG
            ("Jaylen Petty",     "CG", 1, "67 made 3s as FR / 10 PPG on a Top 15 team", "Jaylen Petty"),
            ("Eric Freeny",      "CG", 2, "Glue guy",                      ""),
            ("Gunars Grinvalds", "CG", 3, "Freshman",                      ""),
            # SF (starter OPEN)
            ("OPEN",             "SF", 1, "Starting SF — TBD",             ""),
            ("Brandon Williams", "SF", 2, "Rs-Junior",                     "Brandon Williams"),
            ("JoJo Philon",      "SF", 3, "Freshman",                      ""),
            # PF
            ("Eric Dailey Jr.",  "PF", 1, "12 PPG / 6 RPG",               "Eric Dailey Jr."),
            ("Sergej Macura",    "PF", 2, "Top 15 Rebounder in SEC",      "Sergej Macura"),
            # C
            ("Xavier Booker",    "C",  1, "43.3% 3PT% / 4th best Block rate in B1G", "Xavier Booker"),
            ("Filip Jovic",      "C",  2, "Top 10 O-Rebounder in SEC / 9.5 PPG last two months", "Filip Jovic"),
            ("Javonte Floyd",    "C",  3, "Freshman",                      ""),
        ]
        cursor.executemany(
            "INSERT INTO roster (player_name, position, depth, descriptor, bt_name) VALUES (?, ?, ?, ?, ?)",
            seed
        )
        conn.commit()
    conn.close()


def backfill_roster_bio():
    """Fill in real height / class-year for the 26-27 roster. Idempotent — safe to run every startup."""
    conn = sqlite3.connect('scouting_hub.db')
    cursor = conn.cursor()
    # Source: uclabruins.com roster page + official transfer/signee announcements (2026-27 season)
    bio = {
        "Trent Perry":      ("6'4\"",  "Junior"),
        "Stink Robinson":   ("6'2\"",  "Sophomore"),
        "Markell Alston":   ("6'1\"",  "Redshirt Freshman"),
        "Jaylen Petty":     ("6'1\"",  "Sophomore"),
        "Eric Freeny":      ("6'4\"",  "Redshirt Sophomore"),
        "Gunars Grinvalds": ("6'7\"",  "Freshman"),
        "Brandon Williams": ("6'7\"",  "Redshirt Junior"),
        "JoJo Philon":      ("6'8\"",  "Freshman"),
        "Eric Dailey Jr.":  ("6'8\"",  "Senior"),
        "Sergej Macura":    ("6'9\"",  "Junior"),
        "Xavier Booker":    ("6'11\"", "Senior"),
        "Filip Jovic":      ("6'8\"",  "Sophomore"),
        "Javonte Floyd":    ("6'9\"",  "Freshman"),
    }
    cursor.executemany(
        "UPDATE roster SET height = ?, class_yr = ? WHERE player_name = ?",
        [(ht, cl, name) for name, (ht, cl) in bio.items()]
    )
    conn.commit()
    conn.close()


init_db()
seed_roster_if_empty()
backfill_roster_bio()


# ==========================================
# HEADSHOT FETCHER
# ==========================================
@st.cache_data(ttl=86400)
def fetch_espn_headshot(player_name: str, team_espn_id: str = "") -> str:
    """Fetch player headshot from ESPN search API by player name."""
    if not player_name:
        return ""
    try:
        url = f"https://site.api.espn.com/apis/search/v2?query={urllib.parse.quote(player_name)}&limit=5&type=player"
        r = requests.get(url, timeout=5)
        if r.status_code != 200:
            return ""
        name_lower = player_name.lower().strip()
        for result in r.json().get("results", []):
            for c in result.get("contents", []):
                if c.get("displayName", "").lower().strip() == name_lower:
                    img = c.get("image", {}).get("default", "")
                    if img:
                        # Prefer college basketball image if available
                        athlete_id = img.split("/")[-1].replace(".png", "")
                        college_url = f"https://a.espncdn.com/i/headshots/mens-college-basketball/players/full/{athlete_id}.png"
                        test = requests.get(college_url, timeout=3)
                        if test.status_code == 200 and "image" in test.headers.get("content-type", ""):
                            return college_url
                        return img
    except Exception:
        pass
    return ""


def fetch_sr_headshot_silent(player_name, team_name=""):
    # Legacy stub — ESPN roster lookup is now used instead
    return ""


@st.cache_data(ttl=86400)
def fetch_espn_bio(player_name: str, team_espn_id: str) -> dict:
    """Return weight and position from ESPN roster API, falling back to search API."""
    name_lower = player_name.lower().strip()

    # Try roster API first (has weight + position)
    if team_espn_id:
        try:
            url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/{team_espn_id}/roster"
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                for a in r.json().get("athletes", []):
                    if a.get("displayName", "").lower().strip() == name_lower:
                        return {
                            "weight": a.get("displayWeight", ""),
                            "position": a.get("position", {}).get("displayName", ""),
                        }
        except Exception:
            pass

    # Fall back to search API (has position, no weight)
    try:
        import urllib.parse as _ul
        url = f"https://site.api.espn.com/apis/search/v2?query={_ul.quote(player_name)}&limit=5&type=player"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            for res in r.json().get("results", []):
                for c in res.get("contents", []):
                    if c.get("displayName", "").lower().strip() == name_lower:
                        # Get full athlete record for position
                        uid = c.get("uid", "")  # e.g. s:40~l:41~a:5107782
                        aid = uid.split("~a:")[-1] if "~a:" in uid else ""
                        if aid and "mens-college-basketball" in c.get("defaultLeagueSlug", "") + c.get("description", "").lower():
                            ar = requests.get(
                                f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/athletes/{aid}",
                                timeout=5
                            )
                            if ar.status_code == 200:
                                ath = ar.json().get("athlete", {})
                                return {
                                    "weight": ath.get("displayWeight", ""),
                                    "position": ath.get("position", {}).get("displayName", ""),
                                }
    except Exception:
        pass

    return {}


# ==========================================
# BARTTORVIK FETCH (polite, sequential)
# ==========================================
def fetch_barttorvik_safe(top_filter=None, retries=3, delay_between_requests=4):
    base_url = 'https://barttorvik.com/getadvstats.php?year=2026&page=playerstat&json=1'
    url = base_url if top_filter is None else f"{base_url}&top={top_filter}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://barttorvik.com/"
    }
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=headers, verify=False, timeout=20)
            if response.text.strip():
                raw_data = response.json()

                def safe_float(row_list, idx):
                    try:
                        if idx < len(row_list) and row_list[idx] is not None and str(row_list[idx]).strip() != "":
                            return float(row_list[idx])
                        return 0.0
                    except (ValueError, TypeError, IndexError):
                        return 0.0

                cleaned_rows = []
                for row in raw_data:
                    if len(row) < 53:
                        continue
                    cleaned_rows.append({
                        "PLAYER":      str(row[0]),
                        "TEAM":        str(row[1]),
                        "CONF":        str(row[2]),
                        "GP":          int(row[3]) if row[3] else 0,
                        "MIN_PCT":     safe_float(row, 4),
                        "MPG":         safe_float(row, 54),
                        "PPG":         safe_float(row, 63) if len(row) > 63 else 0.0,
                        "APG":         safe_float(row, 60) if len(row) > 60 else 0.0,
                        "RPG":         safe_float(row, 59) if len(row) > 59 else 0.0,
                        "ORTG":        safe_float(row, 5),
                        "USG":         safe_float(row, 6),
                        "EFG":         safe_float(row, 7),
                        "TS":          safe_float(row, 8),
                        "OR":          safe_float(row, 9),
                        "DR":          safe_float(row, 10),
                        "AST":         safe_float(row, 11),
                        "TO":          safe_float(row, 12),
                        "BLK":         safe_float(row, 22),
                        "STL":         safe_float(row, 23),
                        "FTR":         safe_float(row, 24),
                        "FT_PCT":      safe_float(row, 15) * 100,
                        "TWO_P":       safe_float(row, 18) * 100,
                        "THREE_P":     safe_float(row, 21) * 100,
                        "THREE_P_100": safe_float(row, 65) if len(row) > 65 else 0.0,
                        "CLASS":       str(row[25]) if len(row) > 25 else "",
                        "HEIGHT":      str(row[26]) if len(row) > 26 else "",
                        "POS_TAG":     str(row[64]) if len(row) > 64 else "",
                        "PRPG":        safe_float(row, 28),
                        "BPM":         safe_float(row, 50),
                        "OBPM":        safe_float(row, 51),
                        "DBPM":        safe_float(row, 52),
                        "SOS":         safe_float(row, 34),
                    })
                return pd.DataFrame(cleaned_rows)
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(delay_between_requests)
    return None


@st.cache_data(ttl=3600)
def load_all_data_v6():
    return fetch_barttorvik_safe(top_filter=None)


@st.cache_data(ttl=3600)
def build_team_conf_map(df_all: pd.DataFrame) -> dict:
    """{team_espn_id: CONF} — lets game logs (which only have opponent_espn_id) be matched
    to a conference, via team_rankings (espn_id -> bart_name) -> df_all (TEAM -> CONF)."""
    try:
        conn = sqlite3.connect("scouting_hub.db")
        rankings = pd.read_sql_query("SELECT espn_id, bart_name FROM team_rankings", conn)
        conn.close()
        team_conf = dict(zip(df_all["TEAM"], df_all["CONF"]))
        rankings["CONF"] = rankings["bart_name"].map(team_conf)
        return dict(zip(rankings["espn_id"].astype(str), rankings["CONF"]))
    except Exception:
        return {}


@st.cache_data(ttl=3600)
def load_consistent_boxscore_stats(max_opp_rank=None, conf_ids=None, exclude_conf_ids=False) -> pd.DataFrame:
    """
    Box-score derived per-player stats, optionally filtered by opponent rank and/or
    conference (conf_ids = set of opponent team_espn_ids to include, or exclude if
    exclude_conf_ids=True — used for conference vs. non-conference splits).
    Joins player_game_logs with game_team_stats for rate stats (USG, AST, ORB, DRB, BLK, STL).
    Same formula for All Games / Top 100 / Top 50 — fully comparable currency.
    """
    try:
        conn = sqlite3.connect("scouting_hub.db")
        if max_opp_rank:
            where = f"AND CAST(p.opp_rank AS INTEGER) <= {int(max_opp_rank)} AND CAST(p.opp_rank AS INTEGER) < 999"
        else:
            where = ""
        if conf_ids:
            ids_sql = ",".join("'" + str(i).replace("'", "") + "'" for i in conf_ids)
            op = "NOT IN" if exclude_conf_ids else "IN"
            where += f" AND p.opponent_espn_id {op} ({ids_sql})"
        # ortg_kp/usage_kp only exist once a KenPom build script has run (it ALTER TABLEs them
        # in) — fall back to NULL on fresh installs instead of crashing on "no such column".
        cols = {row[1] for row in conn.execute("PRAGMA table_info(player_game_logs)")}
        if "ortg_kp" in cols and "usage_kp" in cols:
            kp_select = ("ROUND(AVG(CASE WHEN p.ortg_kp IS NOT NULL THEN p.ortg_kp END), 1) AS ORTG_KP,\n"
                         "                ROUND(AVG(CASE WHEN p.usage_kp IS NOT NULL THEN p.usage_kp END), 1) AS USAGE_KP")
        else:
            kp_select = "NULL AS ORTG_KP,\n                NULL AS USAGE_KP"
        df = pd.read_sql_query(f"""
            SELECT
                p.player_name                                                    AS PLAYER,
                p.team_espn_id,
                p.team_name                                                      AS TEAM,
                COUNT(*)                                                         AS GP,
                ROUND(AVG(p.min_played), 1)                                      AS MPG,
                ROUND(AVG(p.pts), 1)                                             AS PPG,
                ROUND(SUM(p.pts)*100.0 /
                    NULLIF(2.0*(SUM(p.fg_att)+0.44*SUM(p.ft_att)), 0), 1)       AS TS,
                ROUND((SUM(p.fg_made)+0.5*SUM(p.fg3_made))*100.0 /
                    NULLIF(SUM(p.fg_att), 0), 1)                                 AS EFG,
                ROUND((SUM(p.fg_made)-SUM(p.fg3_made))*100.0 /
                    NULLIF(SUM(p.fg_att)-SUM(p.fg3_att), 0), 1)                 AS TWO_P,
                ROUND(SUM(p.fg3_made)*100.0 /
                    NULLIF(SUM(p.fg3_att), 0), 1)                                AS THREE_P,
                ROUND(SUM(p.ft_made)*100.0 /
                    NULLIF(SUM(p.ft_att), 0), 1)                                 AS FT_PCT,
                ROUND(SUM(p.ft_att)*100.0 /
                    NULLIF(SUM(p.fg_att), 0), 1)                                 AS FTR,
                ROUND(SUM(p.fg_made)*100.0 /
                    NULLIF(SUM(p.fg_att), 0), 1)                                 AS FG_PCT,
                ROUND(AVG(p.reb), 1)                                             AS RPG,
                ROUND(AVG(p.ast), 1)                                             AS APG,
                ROUND(AVG(p.stl), 1)                                             AS SPG,
                ROUND(AVG(p.blk), 1)                                             AS BPG,
                ROUND(SUM(CASE WHEN t.fga IS NOT NULL THEN p.fg_att + 0.44*p.ft_att + p.tov END)*100.0 /
                    NULLIF(SUM(t.fga)+0.44*SUM(t.fta)+SUM(t.tov), 0), 1)        AS USG,
                ROUND(SUM(p.tov)*100.0 /
                    NULLIF(SUM(p.fg_att)+0.44*SUM(p.ft_att)+SUM(p.tov), 0), 1)  AS TOV_PCT,
                ROUND(CAST(SUM(p.ast) AS REAL) / NULLIF(SUM(p.tov), 0), 2)      AS AST_TO,
                ROUND(SUM(CASE WHEN t.fgm IS NOT NULL THEN p.ast END)*100.0 /
                    NULLIF(
                        (SUM(CASE WHEN t.fgm IS NOT NULL THEN p.min_played END)*1.0 /
                         NULLIF(SUM(CASE WHEN t.fgm IS NOT NULL THEN tm.team_mp END)/5.0, 0))
                        * SUM(t.fgm)
                        - SUM(CASE WHEN t.fgm IS NOT NULL THEN p.fg_made END),
                    0), 1) AS AST_PCT,
                ROUND(SUM(CASE WHEN t.orb IS NOT NULL THEN p.orb END)*100.0 /
                    NULLIF(SUM(t.orb)+SUM(t.opp_drb), 0), 1)                    AS OR_PCT,
                ROUND(SUM(CASE WHEN t.drb IS NOT NULL THEN p.drb END)*100.0 /
                    NULLIF(SUM(t.drb)+SUM(t.opp_orb), 0), 1)                    AS DR_PCT,
                ROUND(SUM(CASE WHEN t.opp_fga IS NOT NULL THEN p.blk END)*100.0 /
                    NULLIF(SUM(t.opp_fga)-SUM(t.opp_fg3a), 0), 1)               AS BLK_PCT,
                ROUND(SUM(CASE WHEN t.possessions IS NOT NULL THEN p.stl END)*100.0 /
                    NULLIF(SUM(t.possessions), 0), 1)                            AS STL_PCT,
                {kp_select}
            FROM player_game_logs p
            LEFT JOIN game_team_stats t
                ON t.team_espn_id = p.team_espn_id AND t.game_date = p.game_date
            LEFT JOIN (
                SELECT team_espn_id, game_date, SUM(min_played) AS team_mp
                FROM player_game_logs
                GROUP BY team_espn_id, game_date
            ) tm ON tm.team_espn_id = p.team_espn_id AND tm.game_date = p.game_date
            WHERE p.min_played >= 1 {where}
            GROUP BY p.player_name, p.team_espn_id
            HAVING COUNT(*) >= 1
        """, conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


def get_pct(val, sorted_vals: list):
    if not sorted_vals or val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    rank = bisect.bisect_left(sorted_vals, val)
    return 100.0 * rank / len(sorted_vals)


def pct_color(pct):
    """Blue (0th pct) → White (50th pct) → Gold (100th pct). Returns (bg_hex, text_hex)."""
    if pct is None:
        return "#EAECF0", "#1A1A1A"
    t = max(0.0, min(100.0, pct)) / 100.0
    if t <= 0.5:
        # Blue (#2774AE) → White (#FFFFFF)
        s = t / 0.5
        r = int(39  + (255 - 39)  * s)
        g = int(116 + (255 - 116) * s)
        b = int(174 + (255 - 174) * s)
    else:
        # White (#FFFFFF) → Gold (#FFD100)
        s = (t - 0.5) / 0.5
        r = int(255 + (255 - 255) * s)
        g = int(255 + (209 - 255) * s)
        b = int(255 + (0   - 255) * s)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    text = "#FFFFFF" if lum < 148 else "#1A1A1A"
    return f"#{r:02x}{g:02x}{b:02x}", text


@st.cache_data(ttl=3600)
def load_quality_game_stats(max_opp_rank: int) -> pd.DataFrame:
    """
    Query the local SQLite game-log DB for per-player averages in games
    where the opponent was ranked <= max_opp_rank (BartTorvik-derived rank).
    Returns empty DataFrame if build_game_logs.py hasn't been run yet.
    """
    try:
        conn = sqlite3.connect("scouting_hub.db")
        df = pd.read_sql_query(
            """
            SELECT
                player_name                                              AS PLAYER,
                team_name                                                AS TEAM,
                COUNT(*)                                                 AS GP,
                ROUND(AVG(pts),  1)                                      AS PPG,
                ROUND(AVG(reb),  1)                                      AS RPG,
                ROUND(AVG(ast),  1)                                      AS APG,
                ROUND(AVG(tov),  1)                                      AS TOV,
                ROUND(AVG(stl),  1)                                      AS STL,
                ROUND(AVG(blk),  1)                                      AS BLK,
                ROUND(
                    CAST(SUM(fg_made)  AS REAL) /
                    NULLIF(SUM(fg_att), 0) * 100, 1)                    AS [FG%],
                ROUND(
                    CAST(SUM(fg3_made) AS REAL) /
                    NULLIF(SUM(fg3_att), 0) * 100, 1)                   AS [3P%],
                ROUND(
                    CAST(SUM(ft_made)  AS REAL) /
                    NULLIF(SUM(ft_att), 0) * 100, 1)                    AS [FT%],
                ROUND(
                    CAST(SUM(pts) AS REAL) /
                    NULLIF(2.0 * (SUM(fg_att) + 0.44 * SUM(ft_att)), 0)
                    * 100, 1)                                            AS [TS%],
                ROUND(
                    (CAST(SUM(fg_made) AS REAL) + 0.5 * SUM(fg3_made)) /
                    NULLIF(SUM(fg_att), 0) * 100, 1)                    AS [EFG%]
            FROM player_game_logs
            WHERE opp_rank <= ?
            GROUP BY player_name, team_name
            HAVING COUNT(*) >= 1
            ORDER BY PPG DESC
            """,
            conn,
            params=(max_opp_rank,),
        )
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


def game_log_db_ready() -> bool:
    """True only after build_game_logs.py has populated both core tables."""
    try:
        conn = sqlite3.connect("scouting_hub.db")
        p = conn.execute("SELECT COUNT(*) FROM player_game_logs").fetchone()[0]
        g = conn.execute("SELECT COUNT(*) FROM game_team_stats").fetchone()[0]
        conn.close()
        return p > 0 and g > 0
    except Exception:
        return False


def get_player_sos(espn_name: str, espn_team: str):
    """
    Return (avg_opp_rank, games_counted) for a player from the game log DB.
    Lower avg_opp_rank = harder schedule.
    """
    try:
        conn = sqlite3.connect("scouting_hub.db")
        row = conn.execute(
            """SELECT ROUND(AVG(opp_rank), 0), COUNT(*)
               FROM player_game_logs
               WHERE player_name = ? AND team_name = ? AND opp_rank < 999""",
            (espn_name, espn_team),
        ).fetchone()
        conn.close()
        if row and row[1] and row[1] > 0:
            return int(row[0]), int(row[1])
    except Exception:
        pass
    return None, None


@st.cache_data(ttl=3600)
def load_player_shots(player_name: str, team_espn_id=None) -> pd.DataFrame:
    """Return shot_chart rows for a player, optionally filtered by team."""
    try:
        conn = sqlite3.connect("scouting_hub.db")
        params = {"name": player_name}
        team_clause = "AND sc.team_id = :team_id" if team_espn_id else ""
        if team_espn_id:
            params["team_id"] = str(team_espn_id)
        df = pd.read_sql_query(
            f"""
            SELECT sc.coord_x_norm AS x, sc.coord_y_norm AS y,
                   sc.scoring_play AS made, sc.shot_type, sc.points_attempted AS pts
            FROM shot_chart sc
            WHERE sc.player_name = :name
              AND sc.shot_type != 'MadeFreeThrow'
              {team_clause}
            """,
            conn, params=params,
        )
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


def _draw_half_court(ax):
    """Draw NCAA half-court lines. Court: x 0-50 ft, y 0-47 ft (half court)."""
    COURT_COLOR = "#1a3a5c"
    LINE_COLOR  = "#e0e0e0"
    LW = 1.4
    BASKET_X, BASKET_Y = 25.0, 5.25   # basket center (5'3" from baseline)
    R3       = 22 + 1.75/12           # three-point arc radius: 22'1.75"
    R_CORNER = 21 + 8/12              # corner 3 horizontal distance: 21'8"
    CORNER_X_L = BASKET_X - R_CORNER  # x=3.333
    CORNER_X_R = BASKET_X + R_CORNER  # x=46.667
    # y where corner straight line meets the arc
    CORNER_Y = BASKET_Y + math.sqrt(R3**2 - (CORNER_X_L - BASKET_X)**2)

    ax.set_facecolor(COURT_COLOR)
    ax.set_xlim(0, 50)
    ax.set_ylim(-2, 47)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_xlim(0, 50)
    ax.set_ylim(-2, 47)
    ax.set_aspect("equal")
    ax.axis("off")

    # Court outline
    ax.add_patch(Rectangle((0, 0), 50, 47, linewidth=LW, edgecolor=LINE_COLOR, facecolor=COURT_COLOR, zorder=1))

    # Paint: 12 ft wide, centered at x=25; 19 ft from baseline to free throw line
    ax.add_patch(Rectangle((19, 0), 12, 19, linewidth=LW, edgecolor=LINE_COLOR, facecolor="#0d2a46", zorder=2))

    # Free throw line
    ax.plot([19, 31], [19, 19], color=LINE_COLOR, linewidth=LW, zorder=3)

    # Free throw circle r=6 ft centered on free throw line at x=25
    th_top = np.linspace(0, np.pi, 120)
    ax.plot(25 + 6*np.cos(th_top), 19 + 6*np.sin(th_top), color=LINE_COLOR, linewidth=LW, zorder=3)
    th_bot = np.linspace(np.pi, 2*np.pi, 120)
    ax.plot(25 + 6*np.cos(th_bot), 19 + 6*np.sin(th_bot), color=LINE_COLOR, linewidth=LW, linestyle="--", zorder=3)

    # Restricted area arc r=4 ft
    th_ra = np.linspace(0, np.pi, 100)
    ax.plot(BASKET_X + 4*np.cos(th_ra), BASKET_Y + 4*np.sin(th_ra), color=LINE_COLOR, linewidth=LW, zorder=3)

    # Backboard (6 ft wide, 4 ft from baseline)
    ax.plot([22, 28], [4.0, 4.0], color=LINE_COLOR, linewidth=2.5, zorder=4)

    # Basket rim
    ax.add_patch(Circle((BASKET_X, BASKET_Y), 0.75, linewidth=LW, edgecolor="#FFA500", facecolor="none", zorder=4))

    # Three-point line: two straight corner segments + arc
    # Corner straight lines from baseline up to where arc begins
    ax.plot([CORNER_X_L, CORNER_X_L], [0, CORNER_Y], color=LINE_COLOR, linewidth=LW, zorder=3)
    ax.plot([CORNER_X_R, CORNER_X_R], [0, CORNER_Y], color=LINE_COLOR, linewidth=LW, zorder=3)
    # Arc from left corner junction to right corner junction (over the top)
    ang_r = math.atan2(CORNER_Y - BASKET_Y, CORNER_X_R - BASKET_X)
    ang_l = math.atan2(CORNER_Y - BASKET_Y, CORNER_X_L - BASKET_X)
    th_3 = np.linspace(ang_r, ang_l, 300)
    ax.plot(BASKET_X + R3*np.cos(th_3), BASKET_Y + R3*np.sin(th_3),
            color=LINE_COLOR, linewidth=LW, zorder=3)


_BX, _BY   = 25.0, 5.25          # basket center
_R3        = 22 + 1.75/12        # arc radius: 22'1.75"
_R_CORNER  = 21 + 8/12          # corner distance: 21'8"
_CXL       = _BX - _R_CORNER    # 3.333
_CXR       = _BX + _R_CORNER    # 46.667
_CY        = _BY + math.sqrt(_R3**2 - (_R_CORNER)**2)  # ~9.83

# Dividing angles (from basket) for mid-range and 3pt zones
# Mid: split into 4 by angles at 45°, 90°(straight up), 135° from baseline
_MID_ANGS  = [math.radians(a) for a in (45, 90, 135)]   # left, top, right dividers

# 3pt above-break split: wing/top boundaries at 65° and 115°
_THREE_ANGS = [math.radians(a) for a in (65, 90, 115)]  # corner/wing, top dividers


def _shot_angle(x, y):
    """Angle from basket, 0=right baseline, 90=straight up, 180=left baseline."""
    return math.degrees(math.atan2(y - _BY, x - _BX)) % 360


def _classify_zone(x, y, pts):
    dist  = math.sqrt((x - _BX)**2 + (y - _BY)**2)
    angle = _shot_angle(x, y)  # 0-360, but shots are 0-180

    # Paint: inside restricted area (r≤4) or inside lane (x 19-31, y≤19) excluding RA
    if dist <= 4.0 or (19 <= x <= 31 and y <= 19):
        return "Paint"

    is_three = (pts == 3) or (dist >= _R3) or (x <= _CXL) or (x >= _CXR)

    if is_three:
        if y <= _CY:  # corner zone (below arc junction)
            return "Corner Left" if x < _BX else "Corner Right"
        # Above-break: split at 65° and 115°
        if angle > 115:
            return "Wing Left"
        elif angle >= 65:
            return "Top"
        else:
            return "Wing Right"
    else:
        # Mid-range: 4 zones split by angles 45°, 90°, 135°
        if angle > 135:
            return "Mid Left"
        elif angle > 90:
            return "Mid Center-Left"
        elif angle > 45:
            return "Mid Center-Right"
        else:
            return "Mid Right"


def _zone_fg_color(pct, zone=None):
    """Cold blue → white → gold, relative to realistic FG% range per zone type."""
    if pct is None:
        return "#444444", "#ffffff"
    # Set realistic low/high bounds per zone so colors are meaningful
    if zone == "Paint":
        lo, hi = 45.0, 75.0
    elif zone in ("Corner Left", "Corner Right"):
        lo, hi = 28.0, 48.0
    elif zone in ("Wing Left", "Wing Right", "Top"):
        lo, hi = 25.0, 42.0
    else:  # mid-range zones
        lo, hi = 30.0, 52.0
    t = max(0.0, min(1.0, (pct - lo) / (hi - lo)))
    if t < 0.5:
        s = t / 0.5
        r = int(30  + (255 - 30)  * s)
        g = int(80  + (255 - 80)  * s)
        b = int(200 + (255 - 200) * s)
    else:
        s = (t - 0.5) / 0.5
        r = int(255)
        g = int(255 + (160 - 255) * s)
        b = int(255 + (0   - 255) * s)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    text = "#ffffff" if lum < 160 else "#111111"
    return f"#{r:02x}{g:02x}{b:02x}", text


def draw_shot_chart(shots_df: pd.DataFrame, title: str = "") -> plt.Figure:
    """Zone-based shot chart: 10 zones color-coded by FG%."""
    shots_df = shots_df[shots_df["y"] >= 0].copy() if not shots_df.empty else shots_df

    fig, ax = plt.subplots(figsize=(6, 5.5))
    fig.patch.set_facecolor("#111827")
    _draw_half_court(ax)

    if shots_df.empty:
        ax.text(25, 24, "No shot data", ha="center", va="center",
                color="white", fontsize=12)
        if title:
            ax.set_title(title, color="white", fontsize=10, pad=6)
        return fig

    # Classify every shot into a zone
    shots_df["zone"] = shots_df.apply(
        lambda r: _classify_zone(r["x"], r["y"], r["pts"]), axis=1
    )

    # Compute FG% per zone
    zone_stats = {}
    for zone, grp in shots_df.groupby("zone"):
        made  = int(grp["made"].sum())
        total = len(grp)
        zone_stats[zone] = {"made": made, "total": total, "pct": made / total * 100}

    # Reuse module-level geometry constants
    BX, BY = _BX, _BY
    R3     = _R3
    CXL, CXR, CY = _CXL, _CXR, _CY

    zone_centers = {
        "Paint":            (25.0,  7.5),
        "Mid Left":         (10.0, 14.0),
        "Mid Center-Left":  (20.5, 23.0),
        "Mid Center-Right": (29.5, 23.0),
        "Mid Right":        (40.0, 14.0),
        "Corner Left":      ( 1.8,  4.5),
        "Corner Right":     (48.2,  4.5),
        "Wing Left":        ( 7.0, 31.0),
        "Top":              (25.0, 38.0),
        "Wing Right":       (43.0, 31.0),
    }

    # Arc angles (right corner junction → left corner junction going CCW)
    _ang_r = math.atan2(CY - BY, CXR - BX)   # ~22.8° right
    _ang_l = math.atan2(CY - BY, CXL - BX)   # ~157.2° left

    def _arc_pts(a_start, a_end, n=200):
        """Arc points between two angles (radians). Positive = CCW."""
        th = np.linspace(a_start, a_end, n)
        return list(zip(BX + R3*np.cos(th), BY + R3*np.sin(th)))

    def _ray_pt(deg, length=60):
        a = math.radians(deg)
        return BX + length*math.cos(a), BY + length*math.sin(a)

    def _zone_patch(zone, bg, alpha=0.78):
        kw = dict(facecolor=bg, alpha=alpha, zorder=2, linewidth=0)

        if zone == "Paint":
            # Semicircle around basket (radius 6.5 ft), closed to baseline
            th = np.linspace(0, math.pi, 120)
            xs = BX + 6.5 * np.cos(th)
            ys = BY + 6.5 * np.sin(th)
            verts = [(xs[0], 0)] + list(zip(xs, ys)) + [(xs[-1], 0)]
            ax.add_patch(plt.Polygon(verts, **kw))

        elif zone == "Corner Left":
            ax.add_patch(Rectangle((0, 0), CXL, CY, **kw))

        elif zone == "Corner Right":
            ax.add_patch(Rectangle((CXR, 0), 50 - CXR, CY, **kw))

        elif zone == "Wing Left":
            # Outside arc, from left corner junction to the 115° ray, out to sideline/top
            a115 = math.radians(115)
            arc = _arc_pts(_ang_l, a115)
            rx, ry = _ray_pt(115)
            # Zone: basket → 115° ray → arc → left corner junction → (0,CY) → (0,47) → back
            # Simpler: fill from basket outward bounded by arc and sideline
            verts = [(BX, BY), _ray_pt(115, 70)] + list(reversed(arc)) + [(CXL, CY), (0, CY), (0, 47), (25, 47)]
            # Actually just fill the region: sideline left + top + 115° line + arc
            verts = [(0, CY), (CXL, CY)] + arc + [_ray_pt(115, 55), (0, 47)]
            ax.add_patch(plt.Polygon(verts, **kw))

        elif zone == "Top":
            # Between 115° and 65° rays, outside arc, bounded by top wall
            a115, a65 = math.radians(115), math.radians(65)
            arc = _arc_pts(a115, a65)
            rx_l, ry_l = _ray_pt(115, 55)
            rx_r, ry_r = _ray_pt(65, 55)
            verts = [(rx_l, ry_l)] + arc + [(rx_r, ry_r), (rx_r, 47), (rx_l, 47)]
            ax.add_patch(plt.Polygon(verts, **kw))

        elif zone == "Wing Right":
            # Outside arc, from 65° ray to right corner junction
            a65 = math.radians(65)
            arc = _arc_pts(a65, _ang_r)
            verts = [_ray_pt(65, 55)] + arc + [(CXR, CY), (50, CY), (50, 47), (25, 47)]
            ax.add_patch(plt.Polygon(verts, **kw))

        elif zone == "Mid Left":
            # Between 135° ray and left arc end, inside arc, above corner zone
            a135 = math.radians(135)
            arc = _arc_pts(_ang_l, a135)
            rx, ry = _ray_pt(135)
            verts = [(CXL, CY)] + arc + [(rx, ry), (BX, BY)]
            ax.add_patch(plt.Polygon(verts, **kw))

        elif zone == "Mid Center-Left":
            # Between 135° and 90° rays, inside arc
            a135, a90 = math.radians(135), math.radians(90)
            arc = _arc_pts(a135, a90)
            verts = [(BX, BY), _ray_pt(135)] + arc + [_ray_pt(90)]
            ax.add_patch(plt.Polygon(verts, **kw))

        elif zone == "Mid Center-Right":
            # Between 90° and 45° rays, inside arc
            a90, a45 = math.radians(90), math.radians(45)
            arc = _arc_pts(a90, a45)
            verts = [(BX, BY), _ray_pt(90)] + arc + [_ray_pt(45)]
            ax.add_patch(plt.Polygon(verts, **kw))

        elif zone == "Mid Right":
            # Between 45° ray and right arc end, inside arc
            a45 = math.radians(45)
            arc = _arc_pts(a45, _ang_r)
            verts = [(BX, BY), _ray_pt(45)] + arc + [(CXR, CY)]
            ax.add_patch(plt.Polygon(verts, **kw))

    for zone, cx_cy in zone_centers.items():
        stats = zone_stats.get(zone)
        if not stats or stats["total"] == 0:
            continue
        bg, fg = _zone_fg_color(stats["pct"], zone)
        _zone_patch(zone, bg)
        cx, cy = cx_cy
        ax.text(cx, cy + 1.2, f"{stats['pct']:.0f}%",
                ha="center", va="center", color=fg,
                fontsize=8, fontweight="bold", zorder=6)
        ax.text(cx, cy - 1.2, f"{stats['made']}/{stats['total']}",
                ha="center", va="center", color=fg,
                fontsize=6.5, zorder=6)

    # Redraw court lines on top of zone fills
    _draw_half_court(ax)

    ax.set_xlim(0, 50)
    ax.set_ylim(-2, 47)
    ax.set_aspect("equal")
    ax.axis("off")

    total = len(shots_df)
    makes = int(shots_df["made"].sum())
    pct   = makes / total * 100 if total else 0
    ax.text(25, -1.5, f"{makes}/{total} FG  ({pct:.1f}%)",
            ha="center", va="top", color="#cccccc", fontsize=7, zorder=7)

    if title:
        ax.set_title(title, color="white", fontsize=9, pad=4)

    plt.tight_layout(pad=0.3)
    return fig


def fmt(val, decimals=1, suffix=""):
    """Format a numeric stat value for display."""
    if val is None or val == 0.0 or (isinstance(val, float) and math.isnan(val)):
        return "—"
    if decimals == 0:
        return f"{int(round(val))}{suffix}"
    return f"{round(float(val), decimals)}{suffix}"


# ==========================================
# PLAYER CARD DATA & HELPERS (Torvik tiles + Synergy + curated portal notes)
# ==========================================

PORTAL_PLAYERS = [
    {"name":"Dillian Shaw","school":"Saint Mary's","pos":"G/Wing","cls":"Fr","height":"6'7\"","tier":"Tier 3","shooting":76,"playmaking":68,"defense":88,"rebounding":64,"tags":["Versatile Defender","3.2 DBPM","Real Shooter","Winning Player"],"projection":"High-major role wing","role":"Two-Way Role Wing","ts":"58.6","usg":"17.0","p3":"42.0","writeup":"High-level role wing who understands team basketball. Strong defender (3.2 DBPM), long, switchable, moves his feet well. Offensively efficient and disciplined. 59% TS, 42% from three on real volume. Projects as a high-major role wing who defends multiple spots, shoots it, and plays within structure."},
    {"name":"Allen Graves","school":"Santa Clara","pos":"PF","cls":"Fr","height":"6'9\"","tier":"Tier 3","shooting":82,"playmaking":62,"defense":68,"rebounding":72,"tags":["Efficient Stretch 4","Screening IQ","Low-Mistake"],"projection":"High-major starting 4","role":"Stretch 4 / Screener","ts":"63.0","usg":"22.0","p3":"40.0","writeup":"Efficient, low-mistake stretch 4 with real feel. 22% usage on 130 ORTG, 40% from 3, almost no turnovers. Generates value through screening, short-roll reads, offensive rebounding, and smart shot selection."},
    {"name":"Rolyns Aligbe","school":"Southern Illinois","pos":"PF","cls":"So","height":"6'9\"","tier":"Tier 3","shooting":68,"playmaking":52,"defense":70,"rebounding":84,"tags":["23% DRB","Lob Threat","High Energy","Capable Shooter"],"projection":"High-major depth big","role":"Athletic Big / Lob Threat","ts":"56.0","usg":"19.0","p3":"42.9","writeup":"Athletic, high-energy forward who generates value through rebounding and activity. Elite defensive rebounder (23% DRB). Solid quick bounce, real lob threat, runs well. Capable shooter (21/49 from three)."},
    {"name":"Tyler Thompson","school":"Montana","pos":"Wing","cls":"RS Fr","height":"6'6\"","tier":"Tier 3","shooting":90,"playmaking":44,"defense":56,"rebounding":52,"tags":["Lethal Shooter","Movement Shooter","Role Clarity","Ball Fake Shooter"],"projection":"High-major role shooter","role":"Movement Shooter","ts":"62.0","usg":"13.0","p3":"42.0","writeup":"Lethal movement shooter. 42% from three on 130+ attempts, taking 5.5 threes per game while barely touching the paint. Ball fake, side-step, quick release. Projects as a high-major role wing."},
    {"name":"Andrija Bukumirovic","school":"UT Martin","pos":"Wing/F","cls":"Jr","height":"6'6\"","tier":"Tier 3","shooting":72,"playmaking":60,"defense":72,"rebounding":70,"tags":["Swiss Army Knife","High Motor","Spot-Up Shooter","Two-Way"],"projection":"High mid-major starter","role":"Swiss Army Knife Wing","ts":"60.0","usg":"19.0","p3":"38.0","writeup":"Versatile stretch forward who impacts the game without needing the ball. Always ready to shoot off the catch. Rebounds at a high level, brings real defensive value. True swiss-army knife forward."},
    {"name":"Oswin Erhunmwunse","school":"Providence","pos":"PF/C","cls":"So","height":"6'10\"","tier":"Tier 4","shooting":30,"playmaking":42,"defense":72,"rebounding":84,"tags":["Elite Wedger","Drop Defender","10% Block Rate","Rim Finisher"],"projection":"High-major scheme fit big","role":"Drop Center / Rim Presence","ts":"68.0","usg":"18.0","p3":"0","writeup":"Massive interior presence. 10% block rate, 72% on close 2s. Elite wedge on the offensive glass. Strong drop-coverage defender. Projects as a starting center at a strong mid-major or lower-tier power conference school."},
    {"name":"Daniel Freitag","school":"Buffalo","pos":"G/CG","cls":"So","height":"6'2\"","tier":"Tier 3","shooting":76,"playmaking":66,"defense":52,"rebounding":58,"tags":["20 PPG","High Volume Shooter","Pick and Roll Creator","39% from 3"],"projection":"High-major bench scorer","role":"High-Usage Scoring Guard","ts":"60.0","usg":"28.0","p3":"39.0","writeup":"High-usage scoring guard who carries Buffalo's offense. 20 PPG, 11 threes per 100 possessions at 39 percent. Real-volume shooter with the ultimate green light. Could be an efficient three-level secondary option backup guard at a high major."},
    {"name":"London Jemison","school":"Alabama","pos":"Wing/F","cls":"Fr","height":"6'8\"","tier":"Tier 3","shooting":76,"playmaking":48,"defense":64,"rebounding":66,"tags":["Floor Spacer","Off-Ball Mover","35.7% from 3","Low Usage High Efficiency"],"projection":"High-major role wing","role":"Off-Ball Spacing Wing","ts":"56.5","usg":"17.7","p3":"35.7","writeup":"Low-usage, high-efficiency wing whose value comes from spacing, movement, and playing within structure. 17.7% usage with 117.0 ORTG. Quick release, confident mechanics. Defensively functional and switchable."},
    {"name":"Treyson Anderson","school":"North Dakota State","pos":"F/C","cls":"So","height":"6'9\"","tier":"Tier 3","shooting":74,"playmaking":50,"defense":62,"rebounding":68,"tags":["Pure Jumper","Pick and Pop","38.4% from 3","Efficient Inside Arc"],"projection":"High-major backup 4/5","role":"Pick & Pop Big","ts":"58.0","usg":"18.0","p3":"38.4","writeup":"The jumper is pure. Clean mechanics, confident release, shoots at real volume (33-86 from three at 38.4%). Understands his role: spaces properly, lifts behind drives, ready to fire on the catch."},
    {"name":"Lewis Walker","school":"NC A&T","pos":"Wing/G","cls":"Fr","height":"6'6\"","tier":"Tier 3","shooting":70,"playmaking":55,"defense":58,"rebounding":58,"tags":["Physical Two Guard","Foul Drawer","37% from 3","Downhill Scorer"],"projection":"High-major secondary scorer","role":"Physical Downhill Wing","ts":"60.0","usg":"23.0","p3":"37.0","writeup":"Strong, physical 6'6 freshman wing who projects as a secondary downhill option at the high-major level. Legit two-guard frame, efficient and versatile. Foul drawing is real, converts at 87% from the line."},
    {"name":"Rob Dockery","school":"La Salle","pos":"Wing/W","cls":"So","height":"6'6\"","tier":"Tier 3","shooting":58,"playmaking":56,"defense":68,"rebounding":68,"tags":["High-Major Body","Foul Drawer","Transition Threat","Do-It-All Wing"],"projection":"High-major rotation wing","role":"Do-It-All Role Wing","ts":"58.0","usg":"20.0","p3":"32.0","writeup":"High-major role wing who can scale up immediately. Big, strong, physical body. Really effective in transition and around the rim. Low mistake player. Not flashy, but coaches trust him immediately."},
    {"name":"Adam Olsen","school":"South Alabama","pos":"F","cls":"Jr","height":"6'8\"","tier":"Tier 3","shooting":82,"playmaking":44,"defense":52,"rebounding":58,"tags":["Dynamic Shooter","Movement Catch-and-Shoot","DHO Weapon","One-Dribble Pull Up"],"projection":"High mid-major shooter","role":"Movement Shooter / DHO Weapon","ts":"62.0","usg":"20.0","p3":"41.0","writeup":"Dynamic shooting 4 who thrives almost entirely off movement and spacing actions. Elite catch-and-shoot guy. Not a creator. Clear role player who can really shoot it but is dependent on a system that uses handoffs and movement."},
    {"name":"Ishan Sharma","school":"Saint Louis","pos":"Wing/G","cls":"So","height":"6'5\"","tier":"Tier 3","shooting":76,"playmaking":60,"defense":72,"rebounding":56,"tags":["44% from 3","Switchable Defender","Role-Driven","Two-Way"],"projection":"High-major rotation wing","role":"Two-Way Connective Wing","ts":"62.0","usg":"17.0","p3":"44.0","writeup":"Role-driven, two-way guard who understands how to impact winning without needing the ball. Defensively solid and versatile. Offensively low usage, efficient production, and real shooting touch: around 44% from three."},
    {"name":"Tomislav Buljan","school":"New Mexico","pos":"C/PF","cls":"Fr","height":"6'9\"","tier":"Tier 3","shooting":38,"playmaking":44,"defense":62,"rebounding":76,"tags":["Massive Frame","Elite Rim Finisher","Physical Screener","17.7% ORB"],"projection":"High-major role big","role":"Screening Rebounding Big","ts":"60.0","usg":"25.7","p3":"23.5","writeup":"6'9 freshman big with a massive frame and true interior presence. High-usage but projects best as a screening, rebounding, physical interior big who can punish switches."},
    {"name":"Torey Alston","school":"Middle Tennessee","pos":"F/C","cls":"Jr","height":"6'8\"","tier":"Tier 3","shooting":38,"playmaking":44,"defense":68,"rebounding":78,"tags":["High Motor","Lob Threat","87.5% on Dunks","Foul Drawer"],"projection":"High-major rotation big","role":"High-Motor Lob Threat","ts":"60.0","usg":"20.0","p3":"15.4","writeup":"High-motor frontcourt piece who generates value through screening, rim pressure, and activity. Sets real, physical screens and creates separation. Legit lob threat and interior finisher. Strong rebounder."},
    {"name":"Terrence Hill Jr.","school":"VCU","pos":"G","cls":"So","height":"6'3\"","tier":"Tier 3","shooting":78,"playmaking":62,"defense":64,"rebounding":52,"tags":["Three-Level Scorer","Screen Navigator","131.9 ORTG","Pull-Up Touch"],"projection":"High-major scoring guard","role":"Three-Level Scoring Guard","ts":"63.1","usg":"23.9","p3":"38.0","writeup":"Natural scorer who is always looking to shoot first. Uses screens really well. 57.3 eFG and 63.1 TS on 23.9% usage. Confident bucket-getter who can hurt you at all three levels."},
    {"name":"Robert Miller III","school":"LSU","pos":"C","cls":"So","height":"6'10\"","tier":"Tier 3","shooting":40,"playmaking":44,"defense":72,"rebounding":68,"tags":["Freak Athlete","Pick and Roll Finisher","Lob Threat","Step-Up Screen Feel"],"projection":"High-major rim runner","role":"Rim-Running Lob Threat","ts":"58.0","usg":"14.0","p3":"0","writeup":"6'10 freak athlete with obvious tools. Runs well, plays fast. Offensively a pick-and-roll and lob guy. Defensively projects as an athletic 5 who can guard and protect the rim. Fast off the floor with real shot-blocking upside."},
    {"name":"Bishop Boswell","school":"Tennessee","pos":"G/CG","cls":"So","height":"6'4\"","tier":"Tier 3","shooting":74,"playmaking":64,"defense":70,"rebounding":62,"tags":["Three-Level Scorer","86% FT","62% FTR","64.4 TS"],"projection":"High-major guard","role":"Three-Level Scoring Guard","ts":"64.4","usg":"23.0","p3":"37.0","writeup":"23% usage, 124.8 ORTG, 64.4 TS. Efficient three-level scorer who gets to the line and hits 86%. Finishes well at the rim and shoots 37% from three. Strong frame, physical downhill guard, smart and tough."},
    {"name":"KJ Lewis","school":"Georgetown","pos":"CG","cls":"Jr","height":"6'4\"","tier":"Tier 3","shooting":52,"playmaking":62,"defense":64,"rebounding":64,"tags":["Strong Frame","Transition Threat","Secondary Playmaker","3rd Team All Big East"],"projection":"High-major rotation guard","role":"Physical Downhill Guard","ts":"54.0","usg":"22.0","p3":"28.0","writeup":"Physically strong, downhill guard who rebounds well for his position and brings real value in transition. Non-shooter. Fits as a high-major 2 guard and secondary scoring option. 3rd team All Big East."},
    {"name":"Noah Feddersen","school":"North Dakota State","pos":"PF/C","cls":"Jr","height":"6'10\"","tier":"Tier 3","shooting":52,"playmaking":46,"defense":62,"rebounding":70,"tags":["Soft Hands","Efficient Interior","Low-Mistake Big","Surprisingly Athletic"],"projection":"High-major backup 5","role":"Low-Mistake Interior Big","ts":"58.0","usg":"16.0","p3":"0","writeup":"Really solid functional big who can scale up because of how clean and controlled his game is. Efficient around the rim with good touch, soft hands, and better-than-expected athleticism for his size."},
    {"name":"Carey Booth","school":"Colorado State","pos":"F","cls":"Jr","height":"6'10\"","tier":"Tier 4","shooting":62,"playmaking":42,"defense":68,"rebounding":72,"tags":["Athletic Complementary Big","Defensive Rebounder","Lob Threat"],"projection":"Mid-major starter","role":"Athletic Complementary Big","ts":"58.0","usg":"16.0","p3":"33.0","writeup":"Strong defensive rebounder with solid block rate. Efficient around the rim. Best when cutting, in the dunker spot, or finishing lobs. Projects as a starter at a strong mid-major or 8th-9th man on a good Power 5 team."},
    {"name":"Isaiah Malone","school":"Florida Gulf Coast","pos":"Wing/F","cls":"Jr","height":"6'8\"","tier":"Tier 4","shooting":58,"playmaking":50,"defense":64,"rebounding":66,"tags":["Super Bouncy","Natural Weak-Side Blocker","Aggressive Downhill","Jumper Upside"],"projection":"High-major rotational big","role":"Athletic Wing / Weak-Side Blocker","ts":"58.0","usg":"19.0","p3":"52.9","writeup":"Long, athletic, explosive forward. Super bouncy and clearly more athletic than most. Natural weak-side shot blocker. Quick off two feet and plays above the rim easily. Could be a rotational big at a high major off of pure athleticism."},
    {"name":"Ben Hammond","school":"Virginia Tech","pos":"PG/CG","cls":"So","height":"5'11\"","tier":"Tier 4","shooting":74,"playmaking":72,"defense":70,"rebounding":50,"tags":["Low Turnover","Active Hands","High IQ","Real Shooter"],"projection":"High-major role guard","role":"Low-Mistake Floor-Spacing Guard","ts":"60.0","usg":"16.0","p3":"38.0","writeup":"Low-mistake, high-IQ combo guard whose value starts with shooting and decision-making. Does not turn the ball over. Legit three-point weapon on catch-and-shoot. Defensively plays with edge, averages around two steals per game."},
    {"name":"Jack Karasinski","school":"Bellarmine","pos":"Wing/F","cls":"So","height":"6'7\"","tier":"Tier 4","shooting":80,"playmaking":44,"defense":56,"rebounding":60,"tags":["44.9% FG","77.4% on Cuts","Elite Spot-Up","Non-Creator"],"projection":"High-major depth stretch 4","role":"Spot-Up Shooter / Cutter","ts":"65.0","usg":"16.0","p3":"39.0","writeup":"Elite efficiency wing who thrives without the ball. 44.9% FG, 77.4% on cuts. 129.5 ORTG, 65% TS. Un-athletic stretch 4 who could play 18-25 minutes and be effective."},
    {"name":"Blake Barklay","school":"East Tennessee State","pos":"Wing/F","cls":"So","height":"6'8\"","tier":"Tier 3","shooting":68,"playmaking":52,"defense":62,"rebounding":62,"tags":["Efficient Role Wing","36% from 3","Post Mismatch","Low Foul Rate"],"projection":"High-major rotation piece","role":"Versatile Role Wing","ts":"60.0","usg":"18.0","p3":"36.0","writeup":"Projects better than a lot of mid-major forwards. Efficient, plays under control. 36% from three on about 40 attempts. Can put it on the deck and attack on hard closeouts. Can absolutely be an effective high-major rotation piece."},
    {"name":"Gavin Doty","school":"Siena","pos":"G","cls":"So","height":"6'5\"","tier":"Tier 4","shooting":72,"playmaking":68,"defense":58,"rebounding":68,"tags":["Controlled Iso Scorer","Midrange Bag","Low Turnover","Strong Rebounder for Guard"],"projection":"High mid-major scorer","role":"Iso Mid-Range Scorer","ts":"57.0","usg":"22.6","p3":"28.0","writeup":"Plays 90% of minutes and scores efficiently on solid usage while taking great care of the ball. Controlled, iso-heavy scorer who operates from the top of the key and lives in the midrange."},
    {"name":"Sonny Wilson","school":"Toledo","pos":"CG","cls":"Jr","height":"6'1\"","tier":"Tier 4","shooting":76,"playmaking":68,"defense":52,"rebounding":50,"tags":["41% from 3","Snake Screen Specialist","Low Turnover","Crafty Scorer"],"projection":"High-major starter","role":"Ball Screen Scoring Guard","ts":"60.0","usg":"23.0","p3":"41.0","writeup":"Skilled offensive guard with real value as a shot-maker and low-turnover ball handler. 17 PPG with 23% usage, shot 41% from three on about 100 attempts. Really good in the midrange coming off ball screens."},
    {"name":"Chol Machot","school":"Charleston","pos":"F/C","cls":"RS So","height":"7'0\"","tier":"Tier 4","shooting":42,"playmaking":38,"defense":72,"rebounding":82,"tags":["Elite Length","High Motor","Rim Protector","Transition Runner"],"projection":"High-major role big","role":"Rim Protector / Energy Big","ts":"56.0","usg":"16.0","p3":"0","writeup":"Long, high-motor rim protector who generates value through rebounding and shot blocking. Elite length, blocks shots outside his area. Runs the floor extremely well for his size. Projects as a high-major role big."},
]


def parse_height_inches(ht_str):
    """Convert height string like 6'7" or 6-7 to total inches. Clean and reliable."""
    try:
        s = str(ht_str).replace('"', '').strip()
        if "\'" in s:
            parts = s.split("\'")
            return int(parts[0].strip()) * 12 + (int(parts[1].strip()) if parts[1].strip().isdigit() else 0)
        if "-" in s:
            parts = s.split("-")
            return int(parts[0].strip()) * 12 + int(parts[1].strip())
        val = int(s)
        return val if val > 12 else val * 12
    except:
        return 78


SHOT_ZONE_FREQ_STATS = ["PCT_RIM", "PCT_MID", "PCT_THREE"]
SHOT_ZONE_EFF_STATS = ["RIM_FG_PCT", "MID_FG_PCT", "THREE_FG_PCT"]
SHOT_ZONE_STATS = SHOT_ZONE_FREQ_STATS + SHOT_ZONE_EFF_STATS
SHOT_ZONE_MIN_ATTEMPTS = 15  # need a real sample before trusting a player's shot-selection profile


@st.cache_data(ttl=3600)
def build_shot_zone_profiles() -> pd.DataFrame:
    """
    Per-player shot profile from shot_chart: what share of a player's field-goal attempts come
    from the rim, mid-range, and three (shot selection), plus their FG% from each of those zones
    (efficiency) — i.e. both where they score from and how well. Used to make the comp finder
    account for real shot profile, not just overall shooting %.
    """
    try:
        conn = sqlite3.connect("scouting_hub.db")
        df = pd.read_sql_query("""
            SELECT player_name AS PLAYER, team_id, scoring_play AS made,
                   coord_x_norm AS x, coord_y_norm AS y, points_attempted AS pts
            FROM shot_chart
            WHERE shot_type != 'MadeFreeThrow' AND coord_x_norm IS NOT NULL AND coord_y_norm IS NOT NULL
        """, conn)
        rankings = pd.read_sql_query("SELECT espn_id, bart_name FROM team_rankings", conn)
        conn.close()
        if df.empty:
            return pd.DataFrame()

        dist = ((df["x"] - 25.0) ** 2 + (df["y"] - 5.25) ** 2) ** 0.5
        df["zone"] = np.where(df["pts"] == 3, "THREE", np.where(dist <= 4.0, "RIM", "MID"))

        grp = df.groupby(["PLAYER", "team_id", "zone"])
        attempts = grp.size().unstack(fill_value=0)
        makes = grp["made"].sum().unstack(fill_value=0)
        for z in ("RIM", "MID", "THREE"):
            if z not in attempts.columns:
                attempts[z] = 0
            if z not in makes.columns:
                makes[z] = 0
        total = attempts[["RIM", "MID", "THREE"]].sum(axis=1)

        def fg_pct(zone):
            a = attempts[zone]
            return np.where(a > 0, makes[zone] / a.replace(0, np.nan) * 100, np.nan)

        profile = pd.DataFrame({
            "PLAYER":        attempts.index.get_level_values("PLAYER"),
            "team_id":       attempts.index.get_level_values("team_id"),
            "PCT_RIM":       (attempts["RIM"]   / total * 100).values,
            "PCT_MID":       (attempts["MID"]   / total * 100).values,
            "PCT_THREE":     (attempts["THREE"] / total * 100).values,
            "RIM_FG_PCT":    fg_pct("RIM"),
            "MID_FG_PCT":    fg_pct("MID"),
            "THREE_FG_PCT":  fg_pct("THREE"),
        })
        profile = profile[total.values >= SHOT_ZONE_MIN_ATTEMPTS]

        team_map = dict(zip(rankings["espn_id"].astype(str), rankings["bart_name"]))
        profile["TEAM"] = profile["team_id"].astype(str).map(team_map)
        return profile.dropna(subset=["TEAM"])
    except Exception:
        return pd.DataFrame()


def merge_shot_zones(df_all: pd.DataFrame) -> pd.DataFrame:
    """df_all + shot-zone columns where available (NaN elsewhere — handled gracefully downstream)."""
    zone_profile = build_shot_zone_profiles()
    if zone_profile.empty:
        return df_all
    return df_all.merge(
        zone_profile[["PLAYER", "TEAM"] + SHOT_ZONE_STATS],
        on=["PLAYER", "TEAM"], how="left"
    )


@st.cache_data(ttl=3600)
def build_team_strength() -> pd.DataFrame:
    """Real team strength (KenPom-derived AdjEM) per BartTorvik team name — a continuous
    measure of level of competition, used instead of a blunt P5/non-P5 conference binary."""
    try:
        conn = sqlite3.connect("scouting_hub.db")
        df = pd.read_sql_query("SELECT bart_name AS TEAM, adj_em AS TEAM_ADJ_EM FROM team_rankings", conn)
        conn.close()
        return df.dropna(subset=["TEAM"])
    except Exception:
        return pd.DataFrame()


def add_derived_comp_stats(df_all: pd.DataFrame) -> pd.DataFrame:
    """df_all + shot-zone profile, team-strength (AdjEM), and AST/TO ratio — the extra
    signals the comp finder (and the card's percentile tiles) weigh in beyond raw box stats."""
    d = merge_shot_zones(df_all.copy())
    strength = build_team_strength()
    if not strength.empty:
        d = d.merge(strength, on="TEAM", how="left")
    if "AST" in d.columns and "TO" in d.columns:
        d["AST_TO"] = d.apply(lambda r: (r["AST"] / r["TO"]) if r["TO"] else None, axis=1)
    return d


# ---- national percentile benchmarks (BartTorvik, all D1) for the tile card front ----
NATIONAL_PCT_STATS = ["PRPG", "BPM", "OBPM", "DBPM", "ORTG", "USG", "EFG", "TS",
                       "TWO_P", "THREE_P", "FTR", "FT_PCT", "AST", "TO", "OR", "DR",
                       "BLK", "STL", "MIN_PCT"]
NATIONAL_LOWER_IS_BETTER = {"TO"}
DERIVED_PCT_STATS = ["AST_TO", "TEAM_ADJ_EM"] + SHOT_ZONE_STATS


@st.cache_data(ttl=3600)
def build_national_benchmarks(df_all: pd.DataFrame) -> dict:
    """Sorted national value lists per stat, used to percentile-rank any player for the tile card."""
    d = add_derived_comp_stats(df_all)
    benchmarks = {}
    for col in NATIONAL_PCT_STATS + DERIVED_PCT_STATS:
        if col in d.columns:
            benchmarks[col] = sorted(d[col].dropna().tolist())
    return benchmarks


@st.cache_data(ttl=3600)
def build_position_benchmarks(df_all: pd.DataFrame, box_df: pd.DataFrame) -> dict:
    """Per-position sorted value lists for both BartTorvik and boxscore stats.
    Returns {position_group: {stat: sorted_list}} for Guard, Wing, Big."""
    try:
        conn = sqlite3.connect("scouting_hub.db")
        pos_df = pd.read_sql_query("SELECT player_name, position_group FROM player_positions", conn)
        conn.close()
    except Exception:
        return {}

    result = {}
    for grp in ("Guard", "Wing", "Big"):
        names = set(pos_df[pos_df["position_group"] == grp]["player_name"])

        # BartTorvik stats
        d = merge_shot_zones(df_all[df_all["PLAYER"].isin(names)].copy())
        if "AST" in d.columns and "TO" in d.columns:
            d["AST_TO"] = d.apply(lambda r: (r["AST"] / r["TO"]) if r["TO"] else None, axis=1)
        bm = {}
        for col in NATIONAL_PCT_STATS + ["AST_TO"] + SHOT_ZONE_STATS:
            if col in d.columns:
                bm[col] = sorted(d[col].dropna().tolist())

        # Boxscore stats
        b = box_df[box_df["PLAYER"].isin(names)].copy()
        for col in ["PPG", "RPG", "APG", "SPG", "BPG", "FG_PCT", "TS", "EFG", "TWO_P",
                    "THREE_P", "FT_PCT", "FTR", "USG", "AST_PCT", "TOV_PCT", "AST_TO",
                    "OR_PCT", "DR_PCT", "STL_PCT", "BLK_PCT"]:
            if col in b.columns:
                bm[col] = sorted(b[col].dropna().tolist())

        result[grp] = bm
    return result


def national_pct(stat, value, benchmarks):
    vals = benchmarks.get(stat)
    if not vals or value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    p = get_pct(value, vals)
    if p is None:
        return None
    return (100 - p) if stat in NATIONAL_LOWER_IS_BETTER else p


def build_torvik_tile_groups(stats_row, benchmarks):
    """Real BartTorvik advanced-stat tiles for the card front, grouped like the Synergy tile mockup."""
    def t(stat, label, decimals=1, suffix=""):
        val = stats_row.get(stat)
        pct = national_pct(stat, val, benchmarks)
        try:
            display = f"{float(val):.{decimals}f}{suffix}"
        except (TypeError, ValueError):
            display = "—"
        return (label, display, pct if pct is not None else 50.0)

    try:
        ast_v, to_v = float(stats_row.get("AST", 0) or 0), float(stats_row.get("TO", 0) or 0)
        a_to = round(ast_v / to_v, 1) if to_v else None
    except (TypeError, ValueError):
        a_to = None
    a_to_pct = national_pct("AST_TO", a_to, benchmarks)

    return [
        ("IMPACT", [t("PRPG", "PRPG!"), t("BPM", "BPM"), t("OBPM", "OBPM"), t("DBPM", "DBPM")]),
        ("EFFICIENCY", [t("ORTG", "ORTG"), t("USG", "USG%"), t("EFG", "EFG%"), t("TS", "TS%")]),
        ("SHOOTING", [t("TWO_P", "2P%"), t("THREE_P", "3P%"), t("FTR", "FTr"), t("FT_PCT", "FT%")]),
        ("PLAYMAKING", [
            t("AST", "AST%"), t("TO", "TO%"),
            ("A/TO", f"{a_to:.1f}" if a_to is not None else "—", a_to_pct if a_to_pct is not None else 50.0),
            t("MIN_PCT", "MIN%"),
        ]),
        ("REB / DEFENSE", [t("OR", "OR%"), t("DR", "DR%"), t("BLK", "BLK%"), t("STL", "STL%")]),
    ]


# ---- Auto-generated skill tags: real percentile stats, not hand-typed labels ----
AUTO_TAG_STATS = [
    ("THREE_P", "Knockdown Shooter"),
    ("FT_PCT",  "Automatic at the Line"),
    ("TWO_P",   "Efficient Inside the Arc"),
    ("TS",      "High-Efficiency Scorer"),
    ("EFG",     "Elite Shot Selection"),
    ("USG",     "High-Usage Focal Point"),
    ("AST",     "Playmaker"),
    ("TO",      "Low-Mistake Ball-Handler"),
    ("OR",      "Elite Offensive Rebounder"),
    ("DR",      "Defensive Rebounding Anchor"),
    ("BLK",     "Rim Protector"),
    ("STL",     "Disruptive Defender"),
    ("BPM",     "High-Impact Winner"),
    ("OBPM",    "Offensive Engine"),
    ("DBPM",    "Defensive Menace"),
    ("FTR",     "Draws Contact / Gets to the Line"),
]


def build_auto_skill_tags(stats_row, benchmarks, top_n=4, threshold=85.0):
    """Tags generated from real national percentiles — fires only on genuinely elite stats."""
    scored = []
    for stat, label in AUTO_TAG_STATS:
        pct = national_pct(stat, stats_row.get(stat), benchmarks)
        if pct is not None and pct >= threshold:
            scored.append((pct, label))
    scored.sort(key=lambda x: -x[0])
    return [label for _, label in scored[:top_n]]


def build_synergy_auto_tags(play_tiles, top_n=2, pct_threshold=80.0):
    """Tags from real Synergy shot diet: what they attempt most, and what they're most efficient at."""
    tags = []
    if not play_tiles:
        return tags
    top_label = play_tiles[0][0]  # play_tiles is already sorted by freq_pct desc from the query
    tags.append(f"Primary Action: {top_label.title()}")
    efficient = sorted(
        (t for t in play_tiles if t[2] >= pct_threshold),
        key=lambda t: -t[2]
    )
    for label, ppp, pct in efficient:
        if label.title() != top_label.title():
            tags.append(f"Elite {label.title()} Efficiency")
            break
    return tags[:top_n]


# ---- Synergy back-of-card (uses the real synergy_playtypes / synergy_shots tables built by
#      build_synergy_playtypes.py / build_synergy_enriched.py — empty/graceful until those are run) ----
@st.cache_data(ttl=3600)
def get_synergy_card_data(player_name: str):
    try:
        conn = sqlite3.connect("scouting_hub.db")
        play_rows = conn.execute(
            "SELECT play_type, ppp, freq_pct FROM synergy_playtypes "
            "WHERE player_name = ? AND freq_pct > 0 ORDER BY freq_pct DESC",
            (player_name,)
        ).fetchall()
        play_tiles = []
        for play_type, ppp, freq in play_rows:
            bench = sorted(r[0] for r in conn.execute(
                "SELECT ppp FROM synergy_playtypes WHERE play_type = ? AND ppp IS NOT NULL", (play_type,)
            ).fetchall())
            pct = get_pct(ppp, bench) if bench else None
            play_tiles.append((play_type.upper(), f"{ppp:.2f}", pct if pct is not None else 50.0))

        shot_row = conn.execute(
            "SELECT fg2_pct, fg3_pct, efg_pct, ppp FROM synergy_shots WHERE player_name = ?",
            (player_name,)
        ).fetchone()
        shot_tiles = []
        if shot_row:
            fg2, fg3, efg, ppp_s = shot_row

            def bench_pct(col, val):
                if val is None:
                    return 50.0
                bench = sorted(r[0] for r in conn.execute(
                    f"SELECT {col} FROM synergy_shots WHERE {col} IS NOT NULL"
                ).fetchall())
                p = get_pct(val, bench) if bench else None
                return p if p is not None else 50.0

            if fg2 is not None:
                shot_tiles.append(("2P%", f"{fg2 * 100:.1f}%", bench_pct("fg2_pct", fg2)))
            if fg3 is not None:
                shot_tiles.append(("3P%", f"{fg3 * 100:.1f}%", bench_pct("fg3_pct", fg3)))
            if efg is not None:
                shot_tiles.append(("EFG%", f"{efg * 100:.1f}%", bench_pct("efg_pct", efg)))
            if ppp_s is not None:
                shot_tiles.append(("PPP", f"{ppp_s:.2f}", bench_pct("ppp", ppp_s)))
        conn.close()
        return play_tiles, shot_tiles
    except Exception:
        return [], []


def _tile_html(label, value, pct):
    bg, fg = pct_color(pct)
    pct_label = f'<div class="p" style="color:{fg};opacity:.7;">({pct:.0f}th)</div>' if pct is not None else ""
    return (f'<div class="tile" style="background:{bg}">'
            f'<div class="k" style="color:{fg};opacity:.72;">{label}</div>'
            f'<div class="v" style="color:{fg};">{value}</div>{pct_label}</div>')


def _tile_group_html(group_label, tiles):
    tiles_html = "".join(_tile_html(*tv) for tv in tiles)
    return (f'<div class="grp"><div class="grp-lab">{group_label}</div>'
            f'<div class="tiles">{tiles_html}</div></div>')


# ---- real BartTorvik position tag (index 64 of the raw feed) -> Guard/Wing/Big bucket ----
POS_TAG_BUCKET = {
    "Scoring PG": "Guard", "Pure PG": "Guard", "Combo G": "Guard",
    "Wing G": "Wing", "Wing F": "Wing", "Stretch 4": "Wing",
    "PF/C": "Big", "C": "Big",
}


# ==========================================
# UNIVERSAL COMP FINDER — works for any player, not just curated portal targets.
# Similarity is computed in percentile space (same national percentiles used for the
# tile card / auto-tags), weighted by position bucket, with the weight boosted toward
# whichever real-stat category the player is genuinely elite in. Level of competition is
# handled via TEAM_ADJ_EM (real KenPom team strength) in the weights below, not a blunt
# P5/non-P5 binary — a strong non-P5 team and a weak P5 team should score differently.
# ==========================================
COMP_CATEGORY_STATS = {
    "Shooting":     ["THREE_P", "TWO_P", "TS", "EFG", "FT_PCT"],
    "Playmaking":   ["AST", "TO", "AST_TO"],
    "Rebounding":   ["OR", "DR"],
    "Defense":      ["BLK", "STL", "DBPM"],
    "Shot Profile": SHOT_ZONE_STATS,
}

# Stats that actually get the dominant-category boost — usually the same as COMP_CATEGORY_STATS,
# except Playmaking excludes raw TO%: it's usage-inflated (high-usage playmakers naturally cough
# it up more even when highly efficient), so boosting it alongside AST%/AST_TO would amplify a
# mismatch that has nothing to do with the actual "elite playmaker" trait being matched on.
COMP_BOOST_STATS = {**COMP_CATEGORY_STATS, "Playmaking": ["AST", "AST_TO"]}

# PCT_RIM/PCT_MID/PCT_THREE = shot-selection profile (where a player actually scores from), and
# *_FG_PCT = their real FG% from each of those zones (how well) — both from real shot-chart data.
# A real comp needs to account for this, not just overall shooting %.
COMP_BASE_WEIGHTS = {
    "Guard": {"ORTG": 0.13, "AST": 0.12, "TO": 0.09, "STL": 0.09, "MIN_PCT": 0.07, "THREE_P": 0.08,
              "TS": 0.06, "BPM": 0.06, "USG": 0.05, "EFG": 0.04, "OBPM": 0.03, "DBPM": 0.03,
              "OR": 0.02, "DR": 0.03, "BLK": 0.02, "FTR": 0.02, "FT_PCT": 0.02, "TWO_P": 0.02, "HEIGHT": 0.08,
              "PCT_THREE": 0.06, "PCT_RIM": 0.03, "PCT_MID": 0.02,
              "THREE_FG_PCT": 0.04, "RIM_FG_PCT": 0.02, "MID_FG_PCT": 0.02,
              "PRPG": 0.07, "AST_TO": 0.05, "TEAM_ADJ_EM": 0.05},
    "Wing":  {"BPM": 0.13, "DBPM": 0.09, "STL": 0.09, "BLK": 0.09, "DR": 0.09, "OR": 0.07,
              "TS": 0.05, "EFG": 0.04, "THREE_P": 0.05, "AST": 0.04, "USG": 0.04, "ORTG": 0.04,
              "TO": 0.03, "OBPM": 0.04, "MIN_PCT": 0.04, "FTR": 0.02, "FT_PCT": 0.02, "TWO_P": 0.02, "HEIGHT": 0.08,
              "PCT_THREE": 0.05, "PCT_RIM": 0.04, "PCT_MID": 0.02,
              "THREE_FG_PCT": 0.03, "RIM_FG_PCT": 0.03, "MID_FG_PCT": 0.02,
              "PRPG": 0.06, "AST_TO": 0.03, "TEAM_ADJ_EM": 0.05},
    "Big":   {"ORTG": 0.11, "OR": 0.11, "DR": 0.11, "BLK": 0.09, "AST": 0.07, "TO": 0.06,
              "MIN_PCT": 0.06, "BPM": 0.06, "TS": 0.05, "USG": 0.04, "EFG": 0.03, "STL": 0.03,
              "DBPM": 0.03, "OBPM": 0.03, "THREE_P": 0.02, "FTR": 0.02, "FT_PCT": 0.02, "TWO_P": 0.02, "HEIGHT": 0.08,
              "PCT_RIM": 0.07, "PCT_MID": 0.03, "PCT_THREE": 0.03,
              "RIM_FG_PCT": 0.05, "MID_FG_PCT": 0.02, "THREE_FG_PCT": 0.02,
              "PRPG": 0.06, "AST_TO": 0.02, "TEAM_ADJ_EM": 0.05},
}

DOMINANT_CATEGORY_BOOST = 3.0
DOMINANT_CATEGORY_MIN_PCT = 70.0
COMP_MIN_GP = 8       # exclude tiny/early-season samples from being potential comps
COMP_MIN_MIN_PCT = 20  # exclude garbage-time/deep-bench players (real signal is too noisy)


def find_player_dominant_category(stats_row, benchmarks):
    """Which real-stat category (Shooting/Playmaking/Rebounding/Defense) is this player's
    genuine standout, if any. Returns None if nothing clears the bar — most players don't
    have one loud, obvious carrying trait, and it'd be dishonest to force one."""
    cat_avgs = {}
    for cat, stats in COMP_CATEGORY_STATS.items():
        pcts = [p for p in (national_pct(s, stats_row.get(s), benchmarks) for s in stats) if p is not None]
        cat_avgs[cat] = sum(pcts) / len(pcts) if pcts else 0.0
    best_cat = max(cat_avgs, key=cat_avgs.get)
    return best_cat if cat_avgs[best_cat] >= DOMINANT_CATEGORY_MIN_PCT else None


def build_comp_weights(bucket, dominant_category):
    weights = dict(COMP_BASE_WEIGHTS.get(bucket, COMP_BASE_WEIGHTS["Wing"]))
    if dominant_category:
        for stat in COMP_BOOST_STATS.get(dominant_category, []):
            if stat in weights:
                weights[stat] *= DOMINANT_CATEGORY_BOOST
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()} if total else weights


def find_stat_comps(player_name, df_all, benchmarks, n=8, bucket_override=None):
    """Real-stat-driven comp finder for any player in df_all. Returns (results, dominant_category)
    where results is a sorted list of (match_score_0_to_1, candidate_row)."""
    df_all = add_derived_comp_stats(df_all)
    match = df_all[df_all["PLAYER"] == player_name]
    if match.empty:
        return [], None
    target = match.iloc[0]

    target_ht = parse_height_inches(target.get("HEIGHT", "6-6"))
    bucket = bucket_override or POS_TAG_BUCKET.get(target.get("POS_TAG", ""), "Wing")
    dominant_category = find_player_dominant_category(target, benchmarks)
    weights = build_comp_weights(bucket, dominant_category)

    target_name = str(target["PLAYER"])
    target_team = str(target["TEAM"])

    # Small samples are noisy — a candidate matching on 5 games of variance isn't a real comp.
    candidates = df_all[(df_all["GP"] >= COMP_MIN_GP) & (df_all["MIN_PCT"] >= COMP_MIN_MIN_PCT)]

    results = []
    for _, row in candidates.iterrows():
        if str(row["PLAYER"]) == target_name and str(row["TEAM"]) == target_team:
            continue
        cand_ht = parse_height_inches(row.get("HEIGHT", "6-6"))
        if abs(target_ht - cand_ht) > 5:
            continue

        score = 0.0
        for stat, w in weights.items():
            if stat == "HEIGHT":
                score += w * max(0.0, 1 - abs(target_ht - cand_ht) / 5.0)
                continue
            t_pct = national_pct(stat, target.get(stat), benchmarks)
            c_pct = national_pct(stat, row.get(stat), benchmarks)
            if t_pct is None or c_pct is None:
                continue
            score += w * (1 - abs(t_pct - c_pct) / 100.0)

        score = max(0.0, min(1.0, score))
        results.append((score, row))

    results.sort(key=lambda x: -x[0])
    return results[:n], dominant_category


def build_general_tiles(stats_row):
    """Basic per-game counting stats — no percentile benchmark for these, shown plain."""
    def plain(stat_key, label):
        try:
            v = float(stats_row[stat_key])
            if math.isnan(v):
                raise ValueError
        except (TypeError, ValueError, KeyError):
            return (label, "—", None)
        return (label, fmt(v), None)

    return [plain("PPG", "PPG"), plain("RPG", "RPG"), plain("APG", "APG")]


def render_tile_card_html(player, df_all, benchmarks, show_writeup=False):
    name       = player.get("name", "")
    height     = player.get("height", "")
    pos        = player.get("pos", "")
    cls        = player.get("cls", "")
    school     = player.get("school", "")
    tier       = player.get("tier", "")
    projection = player.get("projection", "")
    role       = player.get("role", "")

    match = df_all[df_all["PLAYER"] == name]
    stats_row = match.iloc[0] if not match.empty else None
    pos_tag = stats_row.get("POS_TAG", "") if stats_row is not None else ""
    bucket = POS_TAG_BUCKET.get(pos_tag, "Wing")
    pos_display = pos_tag or pos or bucket

    # Single continuous view: basic counting stats first, then the percentile-ranked
    # BartTorvik category breakdown, then Synergy, then tags. No flip needed — the two
    # used to be split front/back but covered heavily overlapping ground.
    if stats_row is not None:
        blocks = _tile_group_html("GENERAL", build_general_tiles(stats_row))
        groups = build_torvik_tile_groups(stats_row, benchmarks)
        blocks += "".join(_tile_group_html(g, tiles) for g, tiles in groups)
    else:
        blocks = ('<div class="empty">No BartTorvik stat line found for this '
                  'player this season.</div>')

    play_tiles, shot_tiles = get_synergy_card_data(name)
    if play_tiles:
        blocks += _tile_group_html("SYNERGY PLAY TYPES", play_tiles)
    if shot_tiles:
        blocks += _tile_group_html("SHOOTING PROFILE (SYNERGY)", shot_tiles)
    if not play_tiles and not shot_tiles and stats_row is not None:
        blocks += ('<div class="empty">No Synergy data loaded for this player yet. Run '
                   'build_synergy_playtypes.py / build_synergy_enriched.py to populate '
                   'play-type and shooting-profile tiles.</div>')

    # Position / role / main-skill tags. Skill tags combine any hand-curated scouting
    # intel with tags auto-generated from real percentile stats and Synergy shot/play-type
    # data, so every player gets meaningful tags, not just the hand-scouted portal targets.
    skill_tags = list(player.get("tags", []))
    if stats_row is not None:
        for t in build_auto_skill_tags(stats_row, benchmarks):
            if t not in skill_tags:
                skill_tags.append(t)
    for t in build_synergy_auto_tags(play_tiles):
        if t not in skill_tags:
            skill_tags.append(t)

    tag_chips = [f'<span class="tagchip tagchip-pos">{pos_display.upper()}</span>']
    if role:
        tag_chips.append(f'<span class="tagchip tagchip-role">{role.upper()}</span>')
    tag_chips += [f'<span class="tagchip">{t}</span>' for t in skill_tags]
    blocks += (f'<div class="grp"><div class="grp-lab">TAGS</div>'
               f'<div class="tags">{"".join(tag_chips)}</div></div>')

    writeup_html = ""
    if show_writeup and player.get("writeup"):
        writeup_html = f'<div class="writeup">{player["writeup"]}</div>'

    card_id = re.sub(r'[^a-zA-Z0-9_]', '', f"card_{name.replace(' ', '_')}")

    return f"""
<!doctype html><html><head><meta charset="UTF-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow:wght@500;600;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root{{--card:#ffffff;--edge:#dde2ee;--ink:#0F172A;--dim:#64748B;--faint:#94A3B8;--gold:#B8860B;--blue:#2774AE;}}
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:transparent;color:var(--ink);font-family:'Barlow',sans-serif;}}
  .card{{background:var(--card);border:1px solid var(--edge);border-radius:13px;padding:20px 22px 22px;
    margin-bottom:8px;box-shadow:0 1px 4px rgba(0,0,0,.06);}}
  .head{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px;}}
  .title{{font-size:19px;font-weight:700;color:var(--ink);}}
  .title span{{display:block;font-family:'DM Mono',monospace;font-size:10px;color:var(--dim);
    letter-spacing:.04em;margin-top:4px;font-weight:400;text-transform:uppercase;}}
  .tier{{font-size:9px;padding:3px 9px;border-radius:3px;background:#fff7e0;
    border:1px solid #f9d98a;color:#92600a;font-weight:600;white-space:nowrap;}}
  .grp{{margin-bottom:12px}}
  .grp-lab{{font-family:'DM Mono',monospace;font-size:9.5px;letter-spacing:.16em;
    color:var(--dim);margin-bottom:8px;text-transform:uppercase;}}
  .tiles{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}}
  .tile{{border-radius:8px;padding:11px 10px 10px;border:1px solid rgba(0,0,0,.04)}}
  .tile .k{{font-family:'DM Mono',monospace;font-size:10.5px;font-weight:700;letter-spacing:.04em;
    text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
  .tile .v{{font-family:'DM Mono',monospace;font-size:18px;font-weight:600;margin-top:3px;line-height:1;}}
  .tile .p{{font-family:'DM Mono',monospace;font-size:10.5px;font-weight:700;margin-top:2px;}}
  .empty{{font-family:'DM Mono',monospace;font-size:11px;color:var(--dim);padding:16px 0;line-height:1.5;}}
  .tags{{margin-top:8px;}}
  .tagchip{{background:#e8f1f9;color:#2774AE;font-family:'DM Mono',monospace;font-size:10.5px;
    font-weight:700;padding:4px 10px;border-radius:3px;border:1px solid #b8d3ec;margin:2px 4px 2px 0;
    display:inline-block;text-transform:uppercase;letter-spacing:.03em;}}
  .tagchip-pos{{background:#fff7e0;color:#92600a;border-color:#f9d98a;}}
  .tagchip-role{{background:#eafaf1;color:#1a7a4c;border-color:#b8e6cc;}}
  .proj{{margin-top:12px;padding-top:12px;border-top:1px solid var(--edge);}}
  .proj-t{{font-size:12.5px;font-weight:700;color:var(--ink);}}
  .writeup{{font-family:'Barlow',sans-serif;font-size:12px;line-height:1.6;color:#374151;
    padding:12px 0 0;}}
</style>
</head>
<body>
<div class="card" id="{card_id}">
  <div class="head">
    <div class="title">{name}<span>{pos_display} &middot; {height} &middot; {cls} &middot; {school}</span></div>
    <span class="tier">{tier}</span>
  </div>
  {blocks}
  <div class="proj"><div class="proj-t">{projection}</div></div>
  {writeup_html}
</div>
</body>
</html>
"""


# ==========================================
# DATA LOAD
# ==========================================
load_bar = st.progress(0, text="Loading full database...")
df_all = load_all_data_v6()
load_bar.progress(100, text="Database ready.")
time.sleep(0.2)
load_bar.empty()

if df_all is None:
    st.error(
        "BartTorvik returned empty data.\n\n"
        "This usually means your IP is temporarily rate-limited. "
        "Wait 10-15 minutes or switch networks and reload."
    )
    st.stop()

_gl_ready = game_log_db_ready()

all_player_names = sorted(list(df_all["PLAYER"].unique()))

if "active_player" not in st.session_state:
    st.session_state.active_player = all_player_names[0]
if "go_to_profile" not in st.session_state:
    st.session_state.go_to_profile = False

# ==========================================
# HEADER
# ==========================================
st.markdown("""
<div id="ucla-header">
  <img src="https://cdn.freebiesupply.com/logos/large/2x/ucla-bruins-1-logo-png-transparent.png" alt="UCLA Logo">
  <div id="ucla-header-title">UCLA Basketball Analytics</div>
</div>
""", unsafe_allow_html=True)

tab_card, tab_depth, tab_onepager, tab2, tab3, tab4 = st.tabs([
    "Player Card",
    "Depth Chart",
    "One Pager",
    "Portal Discovery Engine",
    "Front Office Target Board",
    "Big Board Print View"
])

import streamlit.components.v1 as components
_go_to_profile = st.session_state.go_to_profile
if _go_to_profile:
    st.session_state.go_to_profile = False

components.html(f"""
<script>
(function() {{
    var goToProfile = {'true' if _go_to_profile else 'false'};
    var savedTab = goToProfile ? 0 : parseInt(localStorage.getItem('uclaActiveTab') || '0');

    function attachListeners(tabs) {{
        tabs.forEach(function(tab, i) {{
            tab.addEventListener('click', function() {{
                localStorage.setItem('uclaActiveTab', i);
            }});
        }});
    }}

    function tryRestore() {{
        var tabs = window.parent.document.querySelectorAll('[data-baseweb="tab"]');
        if (tabs.length >= 6) {{
            attachListeners(tabs);
            if (goToProfile || savedTab > 0) {{
                tabs[savedTab].click();
                if (goToProfile) {{ localStorage.setItem('uclaActiveTab', '0'); }}
            }}
        }} else {{
            setTimeout(tryRestore, 100);
        }}
    }}

    setTimeout(tryRestore, 150);

    // Listen for depth chart card clicks from card iframes (only register once)
    if (!window.parent._dcListenerAttached) {{
        window.parent._dcListenerAttached = true;
        try {{
            window.parent.addEventListener('message', function(evt) {{
                if (evt.data && evt.data.type === 'dc_click') {{
                    var playerKey = evt.data.key;
                    var btns = window.parent.document.querySelectorAll('button');
                    for (var i = 0; i < btns.length; i++) {{
                        if (btns[i].textContent.trim() === playerKey) {{
                            btns[i].click();
                            break;
                        }}
                    }}
                }}
            }});
        }} catch(e) {{ console.warn('postMessage listener failed:', e); }}
    }}
}})();
</script>
""", height=0, width=0)

# ==========================================
# LINEUP ANALYZER — helpers (used in depth chart tab)
# ==========================================
@st.cache_data(ttl=3600)
def load_lineup_segments() -> pd.DataFrame:
    try:
        conn = sqlite3.connect("scouting_hub.db")
        df = pd.read_sql_query("SELECT * FROM lineup_segments", conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


LINEUP_RANGES = {
    "ortg":        (85,  125, True),
    "ts":          (42,   70, True),
    "three_pct":   (25,   48, True),
    "three_rate":  (20,   55, True),
    "ft_rate":     (10,   50, True),
    "tov_rate":    (10,   30, False),
    "drtg":        (85,  125, False),
    "opp_ts":      (42,   70, False),
    "opp_tov_rate":(5,    25, True),
    "drb_pct":     (55,   90, True),
    "orb_pct":     (15,   45, True),
    "net_rtg":     (-25,  25, True),
}

def lineup_pct(key, value):
    if key not in LINEUP_RANGES:
        return None
    lo, hi, higher_good = LINEUP_RANGES[key]
    if hi == lo:
        return 50.0
    raw = (value - lo) / (hi - lo)
    raw = max(0.0, min(1.0, raw))
    return (raw * 100) if higher_good else ((1 - raw) * 100)


def compute_lineup_stats_from_segments(players: list, segs: pd.DataFrame):
    """
    Sum across all lineup_segments that contain every player in `players`.
    Returns a stats dict or None.
    """
    if segs.empty or not players:
        return None

    mask = pd.Series([True] * len(segs), index=segs.index)
    for p in players:
        player_mask = (
            (segs["p1"] == p) | (segs["p2"] == p) | (segs["p3"] == p) |
            (segs["p4"] == p) | (segs["p5"] == p)
        )
        mask = mask & player_mask

    sub = segs[mask]
    if sub.empty:
        return None

    mins   = sub["seconds"].sum() / 60
    t_pts  = sub["team_pts"].sum()
    o_pts  = sub["opp_pts"].sum()
    t_fga  = sub["team_fga"].sum()
    t_fgm  = sub["team_fgm"].sum()
    t_fg3a = sub["team_fg3a"].sum()
    t_fg3m = sub["team_fg3m"].sum()
    t_fta  = sub["team_fta"].sum()
    t_ftm  = sub["team_ftm"].sum()
    t_orb  = sub["team_orb"].sum()
    t_drb  = sub["team_drb"].sum()
    t_tov  = sub["team_tov"].sum()
    o_fga  = sub["opp_fga"].sum()
    o_fg3a = sub["opp_fg3a"].sum()
    o_tov  = sub["opp_tov"].sum()
    o_orb  = sub["opp_orb"].sum()
    o_drb  = sub["opp_drb"].sum()

    # Possession estimate (Dean Oliver): FGA + 0.44*FTA + TOV - ORB
    t_poss = t_fga + 0.44 * t_fta + t_tov - t_orb
    o_poss = o_fga + 0.44 * sub["opp_fta"].sum() + o_tov - o_orb
    poss   = (t_poss + o_poss) / 2  # use average per convention

    def safe(n, d): return round(n / d * 100, 1) if d > 0 else 0.0

    return {
        "minutes":    round(mins, 1),
        "segments":   len(sub),
        "games":      sub["game_date"].nunique(),
        "net_rtg":    round((t_pts - o_pts) / poss * 100, 1) if poss else 0,
        "ortg":       round(t_pts / poss * 100, 1) if poss else 0,
        "drtg":       round(o_pts / poss * 100, 1) if poss else 0,
        "ts":         safe(t_pts, 2 * (t_fga + 0.44 * t_fta)),
        "efg":        safe(t_fgm + 0.5 * t_fg3m, t_fga),
        "three_pct":  safe(t_fg3m, t_fg3a),
        "three_rate": safe(t_fg3a, t_fga),
        "ft_rate":    safe(t_fta, t_fga),
        "tov_rate":   round(t_tov / t_poss * 100, 1) if t_poss else 0,
        "orb_pct":    safe(t_orb, t_orb + o_drb),
        "drb_pct":    safe(t_drb, t_drb + o_orb),
        "opp_ts":     safe(o_pts, 2 * (o_fga + 0.44 * sub["opp_fta"].sum())),
        "opp_efg":    safe(sub["opp_fgm"].sum() + 0.5 * o_fg3a, o_fga),
        "opp_tov_rate": round(o_tov / o_poss * 100, 1) if o_poss else 0,
        "pts_per_min": round(t_pts / mins, 2) if mins else 0,
        "opp_per_min": round(o_pts / mins, 2) if mins else 0,
    }


# ==========================================
# TAB: DEPTH CHART (FRONT PAGE)
# ==========================================
with tab_depth:
    st.subheader("26-27 UCLA Bruins — Depth Chart")

    # ---- Load real per-game APG/RPG from game logs ----
    _pg_stats = {}
    try:
        _pg_conn = sqlite3.connect("scouting_hub.db")
        _pg_rows = _pg_conn.execute("""
            SELECT player_name,
                   ROUND(AVG(pts), 1) AS ppg,
                   ROUND(AVG(ast), 1) AS apg,
                   ROUND(AVG(reb), 1) AS rpg
            FROM player_game_logs
            WHERE team_name = 'UCLA Bruins'
            GROUP BY player_name
        """).fetchall()
        _pg_conn.close()
        for row in _pg_rows:
            _pg_stats[row[0]] = {"ppg": row[1], "apg": row[2], "rpg": row[3]}
    except Exception:
        pass

    # ---- VISUAL DEPTH CHART ----
    conn = sqlite3.connect('scouting_hub.db')
    chart_df = pd.read_sql_query(
        "SELECT player_name, position, depth, descriptor, bt_name, height, class_yr FROM roster ORDER BY depth",
        conn
    )
    conn.close()

    POSITIONS = [("PG", "Point Guard"), ("CG", "Combo Guard"), ("SF", "Small Forward"),
                 ("PF", "Power Forward"), ("C", "Center")]

    pos_cols = st.columns(5)

    for i, (pos_code, pos_label) in enumerate(POSITIONS):
        with pos_cols[i]:
            st.markdown(f"""
                <div style='background-color:#2774AE; color:white; font-weight:bold;
                            text-align:center; padding:8px; border-radius:6px; margin-bottom:10px;
                            font-size:13px; letter-spacing:0.5px;'>
                    {pos_code}<br><span style='font-size:9px; font-weight:400; opacity:0.85;'>{pos_label}</span>
                </div>
            """, unsafe_allow_html=True)

            group = chart_df[chart_df["position"] == pos_code].sort_values("depth")

            if group.empty:
                continue

            for _, pl in group.iterrows():
                pname = pl["player_name"]
                descriptor = pl["descriptor"] if pl["descriptor"] else ""
                bt_name = pl["bt_name"] if pl["bt_name"] else ""
                roster_ht = pl["height"] if pl.get("height") else ""
                roster_cl = pl["class_yr"] if pl.get("class_yr") else ""
                is_open = pname.strip().upper() == "OPEN"
                is_starter = int(pl["depth"]) == 1

                if is_open:
                    st.markdown(
                        "<div style=\"border:2px dashed #FFD100;border-radius:8px;padding:12px 10px;"
                        "margin-bottom:8px;background-color:rgba(255,209,0,0.06);text-align:center;\">"
                        "<div style=\"font-size:13px;font-weight:bold;color:#FFD100;\">OPEN</div>"
                        "<div style=\"font-size:10px;color:#FFD100;opacity:0.85;margin-top:2px;\">" + descriptor + "</div>"
                        "</div>",
                        unsafe_allow_html=True
                    )
                    continue

                border = "#FFD100" if is_starter else "#CBD5E1"
                starter_badge = (
                    "<span style=\"font-size:8px;background:#FFD100;color:#0F172A;"
                    "font-weight:bold;padding:1px 5px;border-radius:3px;margin-left:4px;\">S</span>"
                ) if is_starter else ""

                stat_grid = ""
                height_class = ""
                pg = _pg_stats.get(pname, {})

                if bt_name:
                    bt_match = df_all[df_all["PLAYER"] == bt_name]
                    if not bt_match.empty:
                        s = bt_match.iloc[0]
                        ppg_v = f"{pg['ppg']:.1f}" if pg.get('ppg') is not None else f"{s['PPG']:.1f}"
                        apg_v = f"{pg['apg']:.1f}" if pg.get('apg') is not None else (f"{s['APG']:.1f}" if s.get('APG', 0) else "—")
                        rpg_v = f"{pg['rpg']:.1f}" if pg.get('rpg') is not None else (f"{s['RPG']:.1f}" if s.get('RPG', 0) else "—")
                        usg_v = f"{s['USG']:.0f}%" if s.get('USG', 0) else "—"
                        bpm_v = f"{s['BPM']:+.1f}" if s.get('BPM', 0) else "—"
                        ts_v  = f"{s['TS']:.0f}%"  if s.get('TS', 0)  else "—"
                        stat_grid = (
                            "<div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:3px 6px;"
                            "margin:6px 0 4px 0;'>"
                            + "".join(
                                f"<div style='text-align:center;'>"
                                f"<div style='font-size:13px;font-weight:700;color:#0F172A;line-height:1.1;'>{v}</div>"
                                f"<div style='font-size:8px;color:#64748B;letter-spacing:0.3px;'>{l}</div>"
                                f"</div>"
                                for l, v in [("PPG", ppg_v), ("APG", apg_v), ("RPG", rpg_v),
                                             ("USG", usg_v), ("BPM", bpm_v), ("TS%", ts_v)]
                            )
                            + "</div>"
                        )
                        ht = s.get('HEIGHT', '') or ''
                        cl = s.get('CLASS', '') or ''
                        if ht or cl:
                            height_class = (
                                f"<div style='font-size:9px;color:#94a3b8;margin-top:2px;'>"
                                f"{ht}{'  ·  ' if ht and cl else ''}{cl}</div>"
                            )
                elif pg:
                    # In game logs but no BartTorvik — show what we have
                    ppg_v = f"{pg['ppg']:.1f}"
                    apg_v = f"{pg['apg']:.1f}"
                    rpg_v = f"{pg['rpg']:.1f}"
                    stat_grid = (
                        "<div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:3px 6px;"
                        "margin:6px 0 4px 0;'>"
                        + "".join(
                            f"<div style='text-align:center;'>"
                            f"<div style='font-size:13px;font-weight:700;color:#0F172A;line-height:1.1;'>{v}</div>"
                            f"<div style='font-size:8px;color:#64748B;letter-spacing:0.3px;'>{l}</div>"
                            f"</div>"
                            for l, v in [("PPG", ppg_v), ("APG", apg_v), ("RPG", rpg_v),
                                         ("USG", "—"), ("BPM", "—"), ("TS%", "—")]
                        )
                        + "</div>"
                    )
                    if roster_ht or roster_cl:
                        height_class = (
                            f"<div style='font-size:9px;color:#94a3b8;margin-top:2px;'>"
                            f"{roster_ht}{'  ·  ' if roster_ht and roster_cl else ''}{roster_cl}</div>"
                        )
                else:
                    # No BartTorvik, no game logs — show height/class from roster if available
                    if roster_ht or roster_cl:
                        height_class = (
                            f"<div style='font-size:9px;color:#94a3b8;margin-top:4px;'>"
                            f"{roster_ht}{'  ·  ' if roster_ht and roster_cl else ''}{roster_cl}</div>"
                        )

                is_clickable = bt_name and not df_all[df_all["PLAYER"] == bt_name].empty

                card_inner = (
                    "<div style='display:flex;justify-content:space-between;align-items:center;'>"
                    f"<span style='font-size:13px;font-weight:700;color:#0F172A;'>{pname}</span>"
                    + starter_badge + "</div>"
                    + stat_grid + height_class
                )

                card_style = (
                    f"border:1px solid {border};border-left:4px solid {border};"
                    f"border-radius:6px;padding:10px 10px 8px;"
                    f"background:#FFFFFF;box-shadow:1px 1px 3px rgba(0,0,0,0.05);"
                    + ("cursor:pointer;" if is_clickable else "")
                )

                if is_clickable:
                    import re as _re
                    card_key = _re.sub(r'[^a-zA-Z0-9_]', '', f"dc_{pos_code}_{pname.replace(' ', '_')}")
                    btn_trigger = f"__dc__{card_key}"
                    card_height = (130 if height_class else 118) if stat_grid else 46
                    components.html(f"""
<style>
  body {{ margin:0; padding:0; overflow:hidden; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
  .card {{
    border: 1px solid {border};
    border-left: 4px solid {border};
    border-radius: 6px;
    padding: 10px 10px 8px;
    background: #FFFFFF;
    box-shadow: 1px 1px 3px rgba(0,0,0,0.05);
    cursor: pointer;
    user-select: none;
  }}
  .card:hover {{ background: #f8fafc; }}
</style>
<div class="card" onclick="window.parent.postMessage({{type:'dc_click',key:'{btn_trigger}'}}, '*')">
  {card_inner}
</div>
""", height=card_height, scrolling=False)
                    # Hidden trigger button — zero height, caught by postMessage listener
                    st.markdown(f"""
<div id="dc-hide-{card_key}"></div>
<style>
div.element-container:has(#dc-hide-{card_key}) + div.element-container div[data-testid="stButton"] {{
    height: 0 !important; overflow: hidden !important; margin: 0 !important; padding: 0 !important;
}}
</style>
""", unsafe_allow_html=True)
                    clicked = st.button(btn_trigger, key=card_key)
                    if clicked:
                        st.session_state.active_player = bt_name
                        st.session_state.go_to_profile = True
                        st.rerun()
                else:
                    st.markdown(
                        f"<div style='{card_style};margin-bottom:8px;'>{card_inner}</div>",
                        unsafe_allow_html=True,
                    )

    st.divider()

    # ==========================================
    # LINEUP ANALYZER
    # ==========================================
    st.markdown("#### Lineup Combination Analyzer")
    st.caption(
        "Select any 2–5 players to see the team's offensive and defensive performance while on the court together."
    )

    _segs = load_lineup_segments()
    _seg_players = []
    if not _segs.empty:
        all_mentioned = pd.concat([
            _segs["p1"], _segs["p2"], _segs["p3"], _segs["p4"], _segs["p5"]
        ]).dropna().unique().tolist()
        _seg_players = sorted(all_mentioned)

    if not _seg_players:
        st.info("No lineup segment data found. Run `python3 build_lineup_segments.py` first.")
    else:
        selected_lineup = st.multiselect(
            "Select players:",
            options=_seg_players,
            default=[],
            placeholder="Search players...",
            label_visibility="collapsed",
        )

        if len(selected_lineup) >= 2:
            stats = compute_lineup_stats_from_segments(selected_lineup, _segs)

            if stats is None:
                st.warning("No lineup segments found with all selected players on the floor.")
            else:
                mins = stats["minutes"]
                segs = stats["segments"]
                games = stats["games"]
                net = stats["net_rtg"]
                net_color = "#16a34a" if net >= 0 else "#dc2626"
                net_sign  = "+" if net >= 0 else ""

                st.markdown(
                    f"<div style='font-size:13px;color:#64748B;margin-bottom:14px;'>"
                    f"<b>{mins:.0f} minutes</b> together across {segs} stints / {games} game{'s' if games!=1 else ''} · "
                    f"<span style='color:{net_color};font-weight:700;'>Net {net_sign}{net:.1f}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                def lu_card(col_obj, key, display_val, label):
                    pct = lineup_pct(key, stats[key])
                    bg, fg = pct_color(pct)
                    col_obj.markdown(
                        f"<div style='background:{bg};border-radius:8px;padding:12px 6px;text-align:center;'>"
                        f"<div style='font-size:20px;font-weight:700;color:{fg};line-height:1;'>{display_val}</div>"
                        f"<div style='font-size:9px;color:{fg};opacity:0.8;margin-top:4px;letter-spacing:0.3px;'>{label}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

                st.markdown("<div style='font-size:10px;font-weight:700;color:#2774AE;letter-spacing:0.8px;margin-bottom:6px;'>OFFENSE</div>", unsafe_allow_html=True)
                c1, c2, c3, c4, c5 = st.columns(5)
                lu_card(c1, "ortg",       f"{stats['ortg']:.1f}",       "Off Rtg")
                lu_card(c2, "ts",         f"{stats['ts']:.1f}%",        "TS%")
                lu_card(c3, "three_pct",  f"{stats['three_pct']:.1f}%", "3P%")
                lu_card(c4, "three_rate", f"{stats['three_rate']:.1f}%","3P Rate")
                lu_card(c5, "tov_rate",   f"{stats['tov_rate']:.1f}%",  "TOV%")

                st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

                st.markdown("<div style='font-size:10px;font-weight:700;color:#64748B;letter-spacing:0.8px;margin-bottom:6px;'>DEFENSE & REBOUNDING</div>", unsafe_allow_html=True)
                d1, d2, d3, d4, d5 = st.columns(5)
                lu_card(d1, "drtg",         f"{stats['drtg']:.1f}",         "Def Rtg")
                lu_card(d2, "opp_ts",       f"{stats['opp_ts']:.1f}%",      "Opp TS%")
                lu_card(d3, "opp_tov_rate", f"{stats['opp_tov_rate']:.1f}%","Opp TOV%")
                lu_card(d4, "drb_pct",      f"{stats['drb_pct']:.1f}%",     "DReb%")
                lu_card(d5, "orb_pct",      f"{stats['orb_pct']:.1f}%",     "OReb%")

    st.divider()

    # ==========================================
    # MOST COMMON 5-MAN LINEUPS
    # ==========================================
    st.markdown("#### Most Used 5-Man Lineups")

    @st.cache_data(ttl=3600)
    def load_top_lineups(min_minutes: float = 5.0, top_n: int = 12):
        try:
            conn = sqlite3.connect("scouting_hub.db")
            df = pd.read_sql_query(
                "SELECT p1,p2,p3,p4,p5,seconds,"
                "team_pts,opp_pts,team_fga,team_fgm,team_fg3a,team_fg3m,"
                "team_fta,team_ftm,team_tov,team_orb,team_drb,"
                "opp_fga,opp_fgm,opp_fg3a,opp_fg3m,opp_fta,opp_tov,opp_orb,opp_drb "
                "FROM lineup_segments",
                conn,
            )
            conn.close()
        except Exception:
            return pd.DataFrame()

        df = df.dropna(subset=["p1","p2","p3","p4","p5"])

        # Canonical sorted lineup key
        df["lineup_key"] = df[["p1","p2","p3","p4","p5"]].apply(
            lambda r: tuple(sorted(r)), axis=1
        )

        agg = df.groupby("lineup_key").agg(
            seconds    =("seconds",    "sum"),
            segs       =("seconds",    "count"),
            team_pts   =("team_pts",   "sum"),
            opp_pts    =("opp_pts",    "sum"),
            team_fga   =("team_fga",   "sum"),
            team_fgm   =("team_fgm",   "sum"),
            team_fg3a  =("team_fg3a",  "sum"),
            team_fg3m  =("team_fg3m",  "sum"),
            team_fta   =("team_fta",   "sum"),
            team_tov   =("team_tov",   "sum"),
            team_orb   =("team_orb",   "sum"),
            team_drb   =("team_drb",   "sum"),
            opp_fga    =("opp_fga",    "sum"),
            opp_fgm    =("opp_fgm",    "sum"),
            opp_fg3a   =("opp_fg3a",   "sum"),
            opp_fg3m   =("opp_fg3m",   "sum"),
            opp_fta    =("opp_fta",    "sum"),
            opp_tov    =("opp_tov",    "sum"),
            opp_orb    =("opp_orb",    "sum"),
            opp_drb    =("opp_drb",    "sum"),
        ).reset_index()

        agg["mins"] = agg["seconds"] / 60
        agg = agg[agg["mins"] >= min_minutes].sort_values("mins", ascending=False).head(top_n)

        rows = []
        for _, r in agg.iterrows():
            t_poss = r.team_fga + 0.44*r.team_fta + r.team_tov - r.team_orb
            o_poss = r.opp_fga  + 0.44*r.opp_fta  + r.opp_tov  - r.opp_orb
            poss   = (t_poss + o_poss) / 2 if (t_poss + o_poss) > 0 else 1
            ortg   = round(r.team_pts / poss * 100, 1)
            drtg   = round(r.opp_pts  / poss * 100, 1)
            net    = round(ortg - drtg, 1)
            ts_denom = 2 * (r.team_fga + 0.44 * r.team_fta)
            ts     = round(r.team_pts / ts_denom * 100, 1) if ts_denom > 0 else 0.0
            three_pct = round(r.team_fg3m / r.team_fg3a * 100, 1) if r.team_fg3a > 0 else 0.0
            tov_rate  = round(r.team_tov  / t_poss * 100, 1)      if t_poss > 0 else 0.0
            opp_ts_denom = 2 * (r.opp_fga + 0.44 * r.opp_fta)
            opp_ts   = round(r.opp_pts / opp_ts_denom * 100, 1) if opp_ts_denom > 0 else 0.0
            opp_tov  = round(r.opp_tov / o_poss * 100, 1) if o_poss > 0 else 0.0
            drb_pct  = round(r.team_drb / (r.team_drb + r.opp_orb) * 100, 1) if (r.team_drb + r.opp_orb) > 0 else 0.0
            rows.append({
                "Lineup":    " · ".join(r.lineup_key),
                "Min":       round(r.mins, 1),
                "Net":       net,
                "Off Rtg":   ortg,
                "TS%":       ts,
                "3P%":       three_pct,
                "TOV%":      tov_rate,
                "Def Rtg":   drtg,
                "Opp TS%":   opp_ts,
                "Opp TOV%":  opp_tov,
                "DReb%":     drb_pct,
            })
        return pd.DataFrame(rows)

    _top_lu = load_top_lineups()

    if _top_lu.empty:
        st.info("No lineup segment data found.")
    else:
        def color_net(val):
            if val > 5:   return "background:#d1fae5;color:#065f46;font-weight:700;"
            if val < -5:  return "background:#fee2e2;color:#991b1b;font-weight:700;"
            return "color:#374151;font-weight:600;"

        def color_stat(val, key):
            pct = lineup_pct(key, val)
            bg, fg = pct_color(pct)
            return f"background:{bg};color:{fg};font-weight:700;"

        # Render as styled HTML table
        th = "padding:6px 8px;text-align:center;font-size:10px;color:#64748b;letter-spacing:0.5px;font-weight:700;"
        th_l = "padding:6px 10px;text-align:left;font-size:10px;color:#64748b;letter-spacing:0.5px;font-weight:700;"

        def sec_header(label, colspan):
            return f"<th colspan='{colspan}' style='{th}border-bottom:1px solid #e2e8f0;'>{label}</th>"

        rows_html = ""
        for _, row in _top_lu.iterrows():
            net_s    = f"{row['Net']:+.1f}"
            net_c    = color_net(row["Net"])
            ortg_c   = color_stat(row["Off Rtg"],  "ortg")
            ts_c     = color_stat(row["TS%"],       "ts")
            tp_c     = color_stat(row["3P%"],       "three_pct")
            tov_c    = color_stat(row["TOV%"],      "tov_rate")
            drtg_c   = color_stat(row["Def Rtg"],   "drtg")
            opp_ts_c = color_stat(row["Opp TS%"],   "opp_ts")
            opp_tv_c = color_stat(row["Opp TOV%"],  "opp_tov_rate")
            drb_c    = color_stat(row["DReb%"],      "drb_pct")

            def _short_name(full):
                parts = full.split()
                if len(parts) >= 2 and parts[-1].lower() in ("jr.", "jr", "ii", "iii", "iv"):
                    return " ".join(parts[-2:])
                return parts[-1] if parts else full
            names = [_short_name(n) for n in row["Lineup"].split(" · ")]
            lineup_str = " · ".join(names)
            td = "padding:7px 8px;text-align:center;font-size:12px;"
            rows_html += (
                f"<tr style='border-bottom:1px solid #f1f5f9;'>"
                f"<td style='padding:7px 10px;font-size:12px;color:#0f172a;white-space:nowrap;'>{lineup_str}</td>"
                f"<td style='{td}color:#64748b;'>{row['Min']:.0f}</td>"
                f"<td style='{td}{net_c}'>{net_s}</td>"
                f"<td style='{td}{ortg_c}'>{row['Off Rtg']}</td>"
                f"<td style='{td}{ts_c}'>{row['TS%']}%</td>"
                f"<td style='{td}{tp_c}'>{row['3P%']}%</td>"
                f"<td style='{td}{tov_c}'>{row['TOV%']}%</td>"
                f"<td style='{td}{drtg_c}'>{row['Def Rtg']}</td>"
                f"<td style='{td}{opp_ts_c}'>{row['Opp TS%']}%</td>"
                f"<td style='{td}{opp_tv_c}'>{row['Opp TOV%']}%</td>"
                f"<td style='{td}{drb_c}'>{row['DReb%']}%</td>"
                f"</tr>"
            )

        st.markdown(
            f"""<table style='width:100%;border-collapse:collapse;font-family:sans-serif;'>
            <thead>
              <tr style='border-bottom:1px solid #e2e8f0;'>
                <th rowspan='2' style='{th_l}vertical-align:bottom;'>LINEUP</th>
                <th rowspan='2' style='{th}vertical-align:bottom;'>MIN</th>
                <th rowspan='2' style='{th}vertical-align:bottom;'>NET</th>
                {sec_header('— OFFENSE —', 4)}
                {sec_header('— DEFENSE —', 4)}
              </tr>
              <tr style='border-bottom:2px solid #2774AE;'>
                <th style='{th}'>OFF RTG</th>
                <th style='{th}'>TS%</th>
                <th style='{th}'>3P%</th>
                <th style='{th}'>TOV%</th>
                <th style='{th}'>DEF RTG</th>
                <th style='{th}'>OPP TS%</th>
                <th style='{th}'>OPP TOV%</th>
                <th style='{th}'>DREB%</th>
              </tr>
            </thead>
            <tbody>
              {rows_html}
            </tbody>
            </table>""",
            unsafe_allow_html=True,
        )

    st.divider()

    # ---- ROSTER EDITOR (bottom) ----
    with st.expander("Edit Roster", expanded=False):
        st.caption(
            "**Position** must be one of PG / CG / SF / PF / C. "
            "**Depth** sets stacking order (1 = starter). **BT Name** must match exact BartTorvik spelling — leave blank for freshmen / walk-ons."
        )

        conn = sqlite3.connect('scouting_hub.db')
        roster_df = pd.read_sql_query(
            "SELECT player_name AS Player, position AS Pos, depth AS Depth, "
            "descriptor AS Descriptor, bt_name AS [BT Name] FROM roster ORDER BY position, depth",
            conn
        )
        conn.close()

        edited = st.data_editor(
            roster_df,
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "Pos": st.column_config.SelectboxColumn("Pos", options=["PG", "CG", "SF", "PF", "C"], required=True),
                "Depth": st.column_config.NumberColumn("Depth", min_value=1, max_value=10, step=1),
            },
            key="roster_editor"
        )

        if st.button("Save Roster Changes"):
            conn = sqlite3.connect('scouting_hub.db')
            cursor = conn.cursor()
            cursor.execute("DELETE FROM roster")
            for _, r in edited.iterrows():
                pname = str(r["Player"]).strip() if pd.notna(r["Player"]) else ""
                if not pname:
                    continue
                cursor.execute(
                    "INSERT INTO roster (player_name, position, depth, descriptor, bt_name) VALUES (?, ?, ?, ?, ?)",
                    (
                        pname,
                        str(r["Pos"]) if pd.notna(r["Pos"]) else "PG",
                        int(r["Depth"]) if pd.notna(r["Depth"]) else 1,
                        str(r["Descriptor"]) if pd.notna(r["Descriptor"]) else "",
                        str(r["BT Name"]) if pd.notna(r["BT Name"]) else "",
                    )
                )
            conn.commit()
            conn.close()
            st.success("Roster updated.")
            st.rerun()


# ==========================================
# TAB: PLAYER CARD (Individual Profile + Advanced Card + Target Board link-up)
# ==========================================
with tab_card:
    st.subheader("Player Card")

    # Two-way sync between this dropdown and active_player (set by Depth Chart, Portal
    # Discovery, Target Board, etc). A widget's key can't be reassigned after it's
    # instantiated, so external changes must be applied before creating the selectbox —
    # but we can only tell "external change" apart from "user touched this dropdown" by
    # tracking what active_player was the last time *this* tab synced it.
    if st.session_state.active_player != st.session_state.get("_last_synced_active_player"):
        st.session_state["card_player_select"] = st.session_state.active_player

    selected_dropdown = st.selectbox("Search or select any player:", all_player_names,
                                     key="card_player_select")

    if selected_dropdown != st.session_state.active_player:
        st.session_state.active_player = selected_dropdown

    st.session_state["_last_synced_active_player"] = st.session_state.active_player

    current_player = st.session_state.active_player
    p_data = df_all[df_all["PLAYER"] == current_player].iloc[0]

    conn = sqlite3.connect('scouting_hub.db')
    cursor = conn.cursor()
    cursor.execute(
        "SELECT scout_name, priority_tier, position, role, rumored_nil, personal_val, agent, agency, "
        "photo_url, eval_date, notes, value_tag FROM player_notes WHERE player_name = ?",
        (current_player,))
    db_row = cursor.fetchone()

    saved_scout     = db_row[0] if db_row and db_row[0] else "Trey Doty"
    saved_tier      = db_row[1] if db_row and db_row[1] else "Mid Priority"
    saved_pos       = db_row[2] if db_row and db_row[2] else "PG"
    saved_role      = db_row[3] if db_row else ""
    saved_nil       = db_row[4] if db_row else ""
    saved_val       = db_row[5] if db_row else ""
    saved_agent     = db_row[6] if db_row else ""
    saved_agency    = db_row[7] if db_row else ""
    saved_photo     = db_row[8] if db_row else ""
    saved_date      = db_row[9] if db_row else "No previous evaluations logged"
    saved_notes     = db_row[10] if db_row else ""
    saved_value_tag = db_row[11] if db_row and db_row[11] else "Properly Valued"

    if not saved_photo:
        _tid = str(p_data["team_espn_id"]) if "team_espn_id" in p_data.index and pd.notna(p_data["team_espn_id"]) else ""
        saved_photo = fetch_espn_headshot(current_player, _tid)
        if db_row and saved_photo:
            cursor.execute("UPDATE player_notes SET photo_url = ? WHERE player_name = ?", (saved_photo, current_player))
            conn.commit()

    conn.close()

    TIER_OPTIONS = ["High Priority", "Mid Priority", "Low Priority"]
    VALUE_TAG_OPTIONS = ["Undervalued", "Properly Valued", "Overvalued"]

    # Advance class year: data is 2025-26, we're building for 2026-27
    _class_advance = {"Fr": "So", "So": "Jr", "Jr": "Sr", "Sr": "Graduate", "Rs-Fr": "Fr", "Rs-So": "So", "Rs-Jr": "Jr", "Rs-Sr": "Sr"}
    _raw_class = p_data.get("CLASS", "") if hasattr(p_data, "get") else (p_data["CLASS"] if "CLASS" in p_data.index else "")
    _display_class = _class_advance.get(str(_raw_class).strip(), str(_raw_class).strip())

    _tid = str(p_data["team_espn_id"]) if "team_espn_id" in p_data.index and pd.notna(p_data["team_espn_id"]) else ""
    if not _tid:
        try:
            _gl_conn = sqlite3.connect("scouting_hub.db")
            _tid_row = _gl_conn.execute(
                "SELECT team_espn_id FROM player_game_logs WHERE player_name = ? AND team_espn_id IS NOT NULL LIMIT 1",
                (current_player,)
            ).fetchone()
            _gl_conn.close()
            if _tid_row:
                _tid = str(_tid_row[0])
        except Exception:
            pass
    _bio = fetch_espn_bio(current_player, _tid)
    _weight = _bio.get("weight", "")
    _position = _bio.get("position", "")

    # KenPom SOS rank for the player's team
    _sos_rank = None
    try:
        _kp_conn = sqlite3.connect("scouting_hub.db")
        _sos_row = _kp_conn.execute(
            "SELECT sos_rank FROM kenpom_sos WHERE kp_team = ?", (p_data["TEAM"],)
        ).fetchone()
        _kp_conn.close()
        if _sos_row:
            _sos_rank = _sos_row[0]
    except Exception:
        pass

    _conf_names = {
        "A10": "Atlantic 10", "ACC": "ACC", "AE": "America East", "ASun": "ASUN",
        "Amer": "American Athletic", "B10": "Big Ten", "B12": "Big 12", "BE": "Big East",
        "BSky": "Big Sky", "BSth": "Big South", "BW": "Big West", "CAA": "CAA",
        "CUSA": "Conference USA", "Horz": "Horizon League", "Ivy": "Ivy League",
        "MAAC": "MAAC", "MAC": "MAC", "MEAC": "MEAC", "MVC": "Missouri Valley",
        "MWC": "Mountain West", "NEC": "NEC", "OVC": "Ohio Valley", "Pat": "Patriot League",
        "SB": "Sun Belt", "SC": "Southern Conference", "SEC": "SEC", "SWAC": "SWAC",
        "Slnd": "Southland", "Sum": "Summit League", "WAC": "WAC", "WCC": "West Coast",
    }
    _conf_display = _conf_names.get(str(p_data["CONF"]), str(p_data["CONF"]))

    # Pull boxscore stats for header + stat grid
    _hdr_box = load_consistent_boxscore_stats()
    _hdr_row = _hdr_box[_hdr_box["PLAYER"] == current_player]
    if len(_hdr_row) > 1:
        _team_match = _hdr_row[_hdr_row["TEAM"].str.contains(str(p_data["TEAM"]), case=False, na=False)]
        if not _team_match.empty:
            _hdr_row = _team_match
    _hdr = _hdr_row.iloc[0] if not _hdr_row.empty else None

    # Position-filtered benchmarks (Guard/Wing/Big)
    _pos_benchmarks = build_position_benchmarks(df_all, _hdr_box)

    # Determine position group for this player
    _player_pos_group = "Guard"  # default
    try:
        _pg_conn = sqlite3.connect("scouting_hub.db")
        _pg_row = _pg_conn.execute(
            "SELECT position_group FROM player_positions WHERE player_name = ?", (current_player,)
        ).fetchone()
        _pg_conn.close()
        if _pg_row:
            _player_pos_group = _pg_row[0]
        elif _position:
            # Fall back to ESPN bio position
            _pos_lower = _position.lower()
            if any(w in _pos_lower for w in ("center", "big")):
                _player_pos_group = "Big"
            elif any(w in _pos_lower for w in ("forward",)):
                _player_pos_group = "Wing"
            else:
                _player_pos_group = "Guard"
    except Exception:
        pass

    _active_bm = _pos_benchmarks.get(_player_pos_group, {})
    _BOX_LOWER = {"TOV_PCT"}
    _BT_LOWER  = {"TO"}

    def _fmt(val, dec=1):
        try:
            return f"{float(val):.{dec}f}" if val is not None and str(val) not in ("", "nan", "None") else "—"
        except Exception:
            return "—"

    def _box_pct(col, val):
        vals = _active_bm.get(col)
        if not vals or val is None:
            return None
        try:
            v = float(val)
            if math.isnan(v):
                return None
        except Exception:
            return None
        p = get_pct(v, vals)
        return (100 - p) if col in _BOX_LOWER else p

    def _chip(label, val, pct, suffix="", dec=1):
        bg, fg = pct_color(pct)
        disp = _fmt(val, dec)
        if disp == "—":
            bg, fg = "#EAECF0", "#1A1A1A"
        val_str = f"{disp}{suffix}" if disp != "—" else "—"
        return (
            f"<div style='background:{bg};color:{fg};border-radius:6px;padding:5px 8px;"
            f"display:flex;flex-direction:column;min-width:70px'>"
            f"<span style='font-size:0.68rem;opacity:0.75'>{label}</span>"
            f"<span style='font-size:0.95rem;font-weight:700'>{val_str}</span>"
            f"</div>"
        )

    def _stat_row_colored(label, val, pct, suffix="", dec=1):
        bg, fg = pct_color(pct)
        disp = _fmt(val, dec)
        val_str = f"{disp}{suffix}" if disp != "—" else "—"
        if disp == "—":
            bg, fg = "#EAECF0", "#1A1A1A"
        pct_label = f"<span style='font-size:0.65rem;opacity:0.65;margin-left:4px'>({pct:.0f}th)</span>" if pct is not None else ""
        return (
            f"<div style='background:{bg};color:{fg};border-radius:5px;padding:5px 10px;"
            f"display:flex;justify-content:space-between;align-items:center;margin-bottom:3px'>"
            f"<span style='font-size:0.78rem;font-weight:700;opacity:0.9'>{label}</span>"
            f"<span style='font-size:0.9rem;font-weight:700'>{val_str}{pct_label}</span>"
            f"</div>"
        )

    def _cat_table(title, rows_html):
        return (
            f"<div style='margin-bottom:16px'>"
            f"<div style='font-size:1rem;font-weight:800;text-transform:uppercase;"
            f"letter-spacing:0.05em;margin-bottom:6px'>{title}</div>"
            f"{''.join(rows_html)}"
            f"</div>"
        )

    col_img, col_info = st.columns([1, 4])
    with col_img:
        if saved_photo:
            st.image(saved_photo, use_container_width=True)
        else:
            st.info("No headshot logged")

    with col_info:
        st.markdown(f"## {current_player}")
        _sos_str = f"&nbsp;&nbsp;·&nbsp;&nbsp;SOS: #{_sos_rank}" if _sos_rank else ""
        st.markdown(f"**{p_data['TEAM']}** &nbsp;·&nbsp; {_conf_display}{_sos_str}")
        bio_parts = []
        if p_data["HEIGHT"]:
            bio_parts.append(p_data["HEIGHT"])
        if _weight:
            bio_parts.append(_weight)
        if _position:
            bio_parts.append(_position)
        if _display_class:
            bio_parts.append(_display_class)
        st.markdown("&nbsp;&nbsp;·&nbsp;&nbsp;".join(bio_parts))
        st.caption(f"Last evaluation: {saved_date}")

    # Basic box score, right below the header — Season plus Conference/Non-Conference splits.
    if _hdr is not None:
        def _row_num(v, d=1):
            try:
                return f"{float(v):.{d}f}"
            except (TypeError, ValueError):
                return "—"

        def _row_pct(v):
            try:
                v = float(v)
            except (TypeError, ValueError):
                return "—"
            return f"{v:.1f}%" if v else "—"

        def _stats_table_row(row_label, r):
            if r is None:
                return f"<tr><td>{row_label}</td>" + "<td>—</td>" * 16 + "</tr>"
            return (
                f"<tr><td style='font-weight:600'>{row_label}</td>"
                f"<td>{_row_num(r.get('GP'), 0)}</td>"
                f"<td>{_row_num(r.get('MPG'))}</td>"
                f"<td>{_row_num(r.get('PPG'))}</td>"
                f"<td>{_row_num(r.get('RPG'))}</td>"
                f"<td>{_row_num(r.get('APG'))}</td>"
                f"<td>{_row_num(r.get('SPG'))}</td>"
                f"<td>{_row_num(r.get('BPG'))}</td>"
                f"<td>{_row_pct(r.get('FG_PCT'))}</td>"
                f"<td>{_row_pct(r.get('EFG'))}</td>"
                f"<td>{_row_pct(r.get('TS'))}</td>"
                f"<td>{_row_pct(r.get('TWO_P'))}</td>"
                f"<td>{_row_pct(r.get('THREE_P'))}</td>"
                f"<td>{_row_pct(r.get('USG'))}</td>"
                f"<td>{_row_pct(r.get('AST_PCT'))}</td>"
                f"<td>{_row_pct(r.get('OR_PCT'))}</td>"
                f"<td>{_row_pct(r.get('DR_PCT'))}</td>"
                "</tr>"
            )

        _conf_map = build_team_conf_map(df_all)
        _own_conf = p_data["CONF"]
        _in_conf_ids = tuple(sorted(eid for eid, c in _conf_map.items() if c == _own_conf))

        _conf_row = _non_conf_row = None
        if _in_conf_ids:
            _conf_box = load_consistent_boxscore_stats(conf_ids=_in_conf_ids)
            _cr = _conf_box[_conf_box["PLAYER"] == current_player]
            _conf_row = _cr.iloc[0] if not _cr.empty else None

            _nonconf_box = load_consistent_boxscore_stats(conf_ids=_in_conf_ids, exclude_conf_ids=True)
            _ncr = _nonconf_box[_nonconf_box["PLAYER"] == current_player]
            _non_conf_row = _ncr.iloc[0] if not _ncr.empty else None

        _stats_rows_html = _stats_table_row("Season", _hdr)
        if _conf_row is not None or _non_conf_row is not None:
            _stats_rows_html += _stats_table_row("Conference", _conf_row)
            _stats_rows_html += _stats_table_row("Non-Conf", _non_conf_row)

        st.markdown(
            "<style>.card-stats-table{width:100%;border-collapse:collapse;font-size:0.82rem;margin-top:8px;}"
            ".card-stats-table th{text-align:center;padding:4px 6px;color:#6b7280;font-size:0.72rem;"
            "text-transform:uppercase;border-bottom:2px solid #e5e7eb;}"
            ".card-stats-table td{text-align:center;padding:5px 6px;border-bottom:1px solid #f0f0f0;}</style>"
            "<table class='card-stats-table'><thead><tr>"
            "<th></th><th>GP</th><th>MPG</th><th>PPG</th><th>RPG</th><th>APG</th><th>SPG</th><th>BPG</th>"
            "<th>FG%</th><th>EFG%</th><th>TS%</th><th>2P%</th><th>3P%</th><th>USG%</th>"
            "<th>AST%</th><th>OR%</th><th>DR%</th>"
            "</tr></thead><tbody>" + _stats_rows_html + "</tbody></table>",
            unsafe_allow_html=True,
        )
        if _conf_row is None and _non_conf_row is None:
            st.caption("Conference/Non-Conference split unavailable — couldn't match this team's conference to game log opponents.")

    st.divider()

    # ── Bucketed stat categories ──────────────────────────────────────────
    card_benchmarks = build_national_benchmarks(df_all)
    if _hdr is not None:
        _bt = p_data  # BartTorvik row for PRPG/BPM/OBPM/DBPM/ORTG/THREE_P_100

        def _bt_pct(col, val):
            # Use position-filtered benchmarks; fall back to national
            vals = _active_bm.get(col)
            if vals:
                if not val or (isinstance(val, float) and math.isnan(val)):
                    return None
                try:
                    p = get_pct(float(val), vals)
                    return (100 - p) if col in _BT_LOWER else p
                except Exception:
                    return None
            return national_pct(col, val, card_benchmarks)

        eff_html = _cat_table("Efficiency", [
            _stat_row_colored("ORTG",  _bt.get("ORTG"),  _bt_pct("ORTG",  _bt.get("ORTG"))),
            _stat_row_colored("USG%",  _hdr.get("USG"),  _box_pct("USG",  _hdr.get("USG")),  "%"),
            _stat_row_colored("TS%",   _hdr.get("TS"),   _box_pct("TS",   _hdr.get("TS")),   "%"),
            _stat_row_colored("EFG%",  _hdr.get("EFG"),  _box_pct("EFG",  _hdr.get("EFG")),  "%"),
        ])

        imp_html = _cat_table("Impact", [
            _stat_row_colored("PRPG",  _bt.get("PRPG"),  _bt_pct("PRPG",  _bt.get("PRPG"))),
            _stat_row_colored("BPM",   _bt.get("BPM"),   _bt_pct("BPM",   _bt.get("BPM"))),
            _stat_row_colored("OBPM",  _bt.get("OBPM"),  _bt_pct("OBPM",  _bt.get("OBPM"))),
            _stat_row_colored("DBPM",  _bt.get("DBPM"),  _bt_pct("DBPM",  _bt.get("DBPM"))),
            _stat_row_colored("MIN%",  _bt.get("MIN_PCT"), _bt_pct("MIN_PCT", _bt.get("MIN_PCT")), "%"),
        ])

        play_html = _cat_table("Playmaking", [
            _stat_row_colored("AST%",   _hdr.get("AST_PCT"), _box_pct("AST_PCT", _hdr.get("AST_PCT")), "%"),
            _stat_row_colored("TOV%",   _hdr.get("TOV_PCT"), _box_pct("TOV_PCT", _hdr.get("TOV_PCT")), "%"),
            _stat_row_colored("AST/TO", _hdr.get("AST_TO"),  _box_pct("AST_TO",  _hdr.get("AST_TO")),  "", 2),
            _stat_row_colored("USG%",   _hdr.get("USG"),     _box_pct("USG",     _hdr.get("USG")),     "%"),
        ])

        shoot_html = _cat_table("Shooting", [
            _stat_row_colored("TS%",     _hdr.get("TS"),       _box_pct("TS",      _hdr.get("TS")),      "%"),
            _stat_row_colored("2P%",     _hdr.get("TWO_P"),    _box_pct("TWO_P",   _hdr.get("TWO_P")),   "%"),
            _stat_row_colored("3P%",     _hdr.get("THREE_P"),  _box_pct("THREE_P", _hdr.get("THREE_P")), "%"),
            _stat_row_colored("3P Rate", _bt.get("THREE_P_100"), _bt_pct("THREE_P", _bt.get("THREE_P_100")), " /100"),
            _stat_row_colored("FT%",     _hdr.get("FT_PCT"),   _box_pct("FT_PCT",  _hdr.get("FT_PCT")),  "%"),
            _stat_row_colored("FTR",     _hdr.get("FTR"),      _box_pct("FTR",     _hdr.get("FTR")),     "%"),
        ])

        reb_html = _cat_table("Rebounding", [
            _stat_row_colored("OREB%", _hdr.get("OR_PCT"), _box_pct("OR_PCT", _hdr.get("OR_PCT")), "%"),
            _stat_row_colored("DREB%", _hdr.get("DR_PCT"), _box_pct("DR_PCT", _hdr.get("DR_PCT")), "%"),
            _stat_row_colored("RPG",   _hdr.get("RPG"),    _box_pct("RPG",    _hdr.get("RPG"))),
        ])

        def_html = _cat_table("Defense", [
            _stat_row_colored("STL%",  _hdr.get("STL_PCT"), _box_pct("STL_PCT", _hdr.get("STL_PCT")), "%"),
            _stat_row_colored("BLK%",  _hdr.get("BLK_PCT"), _box_pct("BLK_PCT", _hdr.get("BLK_PCT")), "%"),
            _stat_row_colored("DBPM",  _bt.get("DBPM"),     _bt_pct("DBPM",     _bt.get("DBPM"))),
            _stat_row_colored("SPG",   _hdr.get("SPG"),     _box_pct("SPG",     _hdr.get("SPG"))),
            _stat_row_colored("BPG",   _hdr.get("BPG"),     _box_pct("BPG",     _hdr.get("BPG"))),
        ])

        st.caption(f"Percentiles vs. all {_player_pos_group}s nationally")
        col_left, col_right = st.columns(2)
        with col_left:
            st.markdown(eff_html + shoot_html + play_html, unsafe_allow_html=True)
        with col_right:
            st.markdown(imp_html + reb_html + def_html, unsafe_allow_html=True)

    curated_player = next((p for p in PORTAL_PLAYERS if p["name"] == current_player), None)

    st.write("**Competition Split**")

    _split = st.radio(
        "Competition split",
        ["All Games", "Top 100", "Top 50"],
        horizontal=True,
        key="profile_split",
        label_visibility="collapsed",
    )

    _max_rank = None if _split == "All Games" else (100 if _split == "Top 100" else 50)

    if not _gl_ready:
        st.info("Run `python3 build_game_logs.py` to enable the shot chart.")
    else:
        _box_df = load_consistent_boxscore_stats(_max_rank)
        _pbox = _box_df[_box_df["PLAYER"] == current_player]
        if len(_pbox) > 1:
            _bt_team = p_data["TEAM"]
            _team_match = _pbox[_pbox["TEAM"].str.contains(_bt_team, case=False, na=False)]
            if not _team_match.empty:
                _pbox = _team_match

        # Shot chart section — use matched team_espn_id to avoid name collisions
        _team_id = _pbox.iloc[0]["team_espn_id"] if not _pbox.empty and "team_espn_id" in _pbox.columns else None
        _shots = load_player_shots(current_player, _team_id)
        if not _shots.empty:
            st.write("**Shot Chart**")
            _chart_title = f"{current_player}  ·  {_split}"
            _fig = draw_shot_chart(_shots, title=_chart_title)
            col_chart, col_gap = st.columns([3, 2])
            with col_chart:
                st.pyplot(_fig, use_container_width=True)
            plt.close(_fig)

    st.divider()

    with st.expander(f"Find Comps: {current_player}", expanded=False):
        if curated_player:
            if curated_player.get("writeup"):
                st.write(curated_player["writeup"])
            st.write(f"**Projection:** {curated_player.get('projection', '')}  ·  "
                     f"**Role:** {curated_player.get('role', '')}")
            st.divider()

        if df_all is None or df_all.empty:
            st.warning("BartTorvik data unavailable.")
        else:
            comp_bucket_options = ["Guard", "Wing", "Big"]
            auto_bucket = POS_TAG_BUCKET.get(p_data.get("POS_TAG", ""), "Wing")
            cc1, cc2 = st.columns([1, 2])
            with cc1:
                comp_n = st.slider("Comps to show:", 3, 15, 8, key="comp_n_slider")
            with cc2:
                comp_bucket = st.radio("Position group for weighting:", comp_bucket_options,
                                       index=comp_bucket_options.index(auto_bucket),
                                       horizontal=True, key="comp_bucket_radio")

            top_matches, dominant_cat = find_stat_comps(
                current_player, df_all, card_benchmarks, n=comp_n, bucket_override=comp_bucket
            )

            boost_note = f" boosted toward this player's real-stat strength: **{dominant_cat}**" if dominant_cat else ""
            st.write(f"**Top {len(top_matches)} comps from {len(df_all):,} current-season players** "
                     f"— height ±5in, weighted by **{comp_bucket}** profile{boost_note}, "
                     f"real KenPom team strength nudges the ranking, shot-selection profile and "
                     f"zone FG% (rim/mid/three) also weighted in where shot-chart data exists.")

            def _zone_fmt(freq, eff):
                eff_txt = f"{eff:.0f}% FG" if pd.notna(eff) else "no FG% sample"
                return f"{freq:.0f}% ({eff_txt})"

            _zone_df = merge_shot_zones(df_all)
            _target_zone_row = _zone_df[_zone_df["PLAYER"] == current_player]
            if not _target_zone_row.empty and pd.notna(_target_zone_row.iloc[0].get("PCT_RIM")):
                tz = _target_zone_row.iloc[0]
                st.caption(
                    f"**{current_player}'s shot profile (share of FGA, zone FG%):** "
                    f"Rim {_zone_fmt(tz['PCT_RIM'], tz['RIM_FG_PCT'])} · "
                    f"Mid {_zone_fmt(tz['PCT_MID'], tz['MID_FG_PCT'])} · "
                    f"Three {_zone_fmt(tz['PCT_THREE'], tz['THREE_FG_PCT'])}"
                )

            COMP_STAT_LABELS = {
                "ORTG": "ORtg", "AST": "AST%", "TO": "TO%", "STL": "STL%", "MIN_PCT": "Min%",
                "THREE_P": "3P%", "TS": "TS%", "BPM": "BPM", "USG": "USG%", "EFG": "eFG%",
                "OBPM": "OBPM", "DBPM": "DBPM", "OR": "OR%", "DR": "DR%", "BLK": "BLK%",
                "FTR": "FT Rate", "FT_PCT": "FT%", "TWO_P": "2P%", "PRPG": "PRPG",
                "AST_TO": "AST/TO", "TEAM_ADJ_EM": "Team AdjEM",
                "PCT_RIM": "Rim FGA%", "PCT_MID": "Mid FGA%", "PCT_THREE": "3PT FGA%",
                "RIM_FG_PCT": "Rim FG%", "MID_FG_PCT": "Mid FG%", "THREE_FG_PCT": "3PT FG%",
            }

            def _stat_val(row, stat):
                v = row.get(stat)
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    return None
                if stat in ("TS", "EFG") and v <= 1.0:
                    v = v * 100
                return float(v)

            def _plain_tile(label, value_str):
                return (
                    "<div style=\"flex:1;padding:6px 4px;text-align:center;border-right:1px solid #e5e7eb;background:#F1F5F9;\">"
                    "<div style=\"font-size:12px;font-weight:600;color:#0F172A;\">" + value_str + "</div>"
                    "<div style=\"font-size:7px;color:#64748B;text-transform:uppercase;margin-top:1px;\">" + label + "</div>"
                    "</div>"
                )

            def _pct_tile(label, value, pct, decimals=1, suffix="%"):
                bg, fg = pct_color(pct)
                pct_txt = f"({pct:.0f}th)" if pct is not None else ""
                val_txt = fmt(value, decimals, suffix) if value is not None else "—"
                return (
                    "<div style=\"flex:1;padding:6px 4px;text-align:center;border-right:1px solid #e5e7eb;background:" + bg + ";\">"
                    "<div style=\"font-size:12px;font-weight:600;color:" + fg + ";\">" + val_txt + "</div>"
                    "<div style=\"font-size:7px;color:" + fg + ";opacity:.75;text-transform:uppercase;margin-top:1px;\">" + label + "</div>"
                    "<div style=\"font-size:7px;color:" + fg + ";opacity:.6;\">" + pct_txt + "</div>"
                    "</div>"
                )

            if not top_matches:
                st.info("No close height/stat matches found in the current season database.")
            else:
                for _comp_idx, (match_score, match_data) in enumerate(top_matches):
                    pct = round(match_score * 100, 1)
                    c_name = str(match_data.get("PLAYER", ""))
                    c_team = str(match_data.get("TEAM", ""))
                    c_conf = str(match_data.get("CONF", ""))
                    c_ht   = str(match_data.get("HEIGHT", ""))
                    c_class = str(match_data.get("CLASS", "") or "")

                    # Basic box score — plain, no percentile, easy to scan at a glance.
                    basic_row_html = (
                        "<div style=\"display:flex;border:1px solid #e5e7eb;border-radius:5px;overflow:hidden;margin-bottom:6px;\">"
                        + _plain_tile("PPG", fmt(_stat_val(match_data, "PPG"), 1))
                        + _plain_tile("RPG", fmt(_stat_val(match_data, "RPG"), 1))
                        + _plain_tile("APG", fmt(_stat_val(match_data, "APG"), 1)).replace("border-right:1px solid #e5e7eb;", "")
                        + "</div>"
                    )

                    # Advanced stats — percentile-colored, same visual language as the Player Card.
                    adv_stats = [("TS", "TS%"), ("USG", "USG%"), ("EFG", "eFG%"), ("BPM", "BPM"), ("AST", "AST%")]
                    adv_html = ""
                    for i, (stat, label) in enumerate(adv_stats):
                        v = _stat_val(match_data, stat)
                        p = national_pct(stat, v, card_benchmarks)
                        tile = _pct_tile(label, v, p)
                        if i == len(adv_stats) - 1:
                            tile = tile.replace("border-right:1px solid #e5e7eb;", "")
                        adv_html += tile
                    adv_row_html = ("<div style=\"display:flex;border:1px solid #e5e7eb;border-radius:5px;"
                                    "overflow:hidden;margin-bottom:6px;\">" + adv_html + "</div>")

                    # "Why matched" callout — the specific stats behind this player's dominant-category
                    # boost, with real values, so it's clear *why* this is a comp, not just a score.
                    why_html = ""
                    if dominant_cat:
                        cat_stats = COMP_BOOST_STATS.get(dominant_cat, [])
                        cat_tiles = ""
                        shown = 0
                        for stat in cat_stats:
                            v = _stat_val(match_data, stat)
                            if v is None:
                                continue
                            p = national_pct(stat, match_data.get(stat), card_benchmarks)
                            label = COMP_STAT_LABELS.get(stat, stat)
                            decimals = 2 if stat == "AST_TO" else 1
                            suffix = "" if stat in ("AST_TO", "BPM", "TEAM_ADJ_EM") else "%"
                            cat_tiles += _pct_tile(label, v, p, decimals=decimals, suffix=suffix)
                            shown += 1
                        if shown:
                            idx = cat_tiles.rfind("border-right:1px solid #e5e7eb;")
                            if idx != -1:
                                cat_tiles = cat_tiles[:idx] + cat_tiles[idx + len("border-right:1px solid #e5e7eb;"):]
                            why_html = (
                                "<div style=\"margin-bottom:6px;\">"
                                "<div style=\"font-size:8px;font-weight:700;color:#92600a;text-transform:uppercase;"
                                "letter-spacing:.04em;margin-bottom:4px;\">⭐ Matched on: " + dominant_cat + "</div>"
                                "<div style=\"display:flex;border:1px solid #f9d98a;border-radius:5px;overflow:hidden;"
                                "background:#fffdf7;\">" + cat_tiles + "</div>"
                                "</div>"
                            )

                    zone_row_html = ""
                    if pd.notna(match_data.get("PCT_RIM")):
                        zone_html = (
                            _pct_tile("Rim FGA", match_data["PCT_RIM"], None, decimals=0)
                            + _pct_tile("Mid FGA", match_data["PCT_MID"], None, decimals=0)
                            + _pct_tile("Three FGA", match_data["PCT_THREE"], None, decimals=0).replace("border-right:1px solid #e5e7eb;", "")
                        )
                        zone_row_html = ("<div style=\"display:flex;border:1px solid #e5e7eb;border-radius:5px;"
                                          "overflow:hidden;margin-bottom:6px;\">" + zone_html + "</div>")

                    html = (
                        "<div style=\"background:#ffffff;border:1px solid #dde2ee;border-left:4px solid #2774AE;border-radius:8px;padding:12px 14px;margin-bottom:8px;\">"
                        "<div style=\"display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px;\">"
                        "<div>"
                        "<div style=\"font-size:14px;font-weight:700;color:#111827;\">" + c_name + "</div>"
                        "<div style=\"font-size:9px;color:#6b7280;margin-top:2px;\">" + c_ht
                        + (" &middot; " + c_class if c_class else "") + " &middot; " + c_team + " (" + c_conf + ")</div>"
                        "</div>"
                        "<span style=\"font-size:8px;font-weight:600;padding:4px 8px;border-radius:3px;background:#e8f1f9;color:#2774AE;border:1px solid #b8d3ec;\">" + str(pct) + "% match</span>"
                        "</div>"
                        + basic_row_html
                        + adv_row_html
                        + why_html
                        + zone_row_html +
                        "<div style=\"height:3px;background:#e5e7eb;border-radius:2px;\">"
                        "<div style=\"height:100%;width:" + str(pct) + "%;background:#2774AE;border-radius:2px;\"></div>"
                        "</div>"
                        "</div>"
                    )
                    st.markdown(html, unsafe_allow_html=True)
                    if st.button(f"↗ Open {c_name}'s Player Card", key=f"comp_open_{current_player}_{_comp_idx}_{c_name}"):
                        st.session_state.active_player = c_name
                        st.session_state.go_to_profile = True
                        st.rerun()

    st.divider()

    st.write("**Detailed Scouting Report**")
    col_scout, col_pos, col_role = st.columns(3)
    with col_scout:
        scout_input = st.text_input("Assigned Staff Member / Scout Name:", value=saved_scout)
    with col_pos:
        position_list = ["PG", "CG", "W", "F", "C"]
        pos_idx = position_list.index(saved_pos) if saved_pos in position_list else 0
        position_input = st.selectbox("Primary Position Grouping:", position_list, index=pos_idx)
    with col_role:
        role_input = st.text_input("Projected Tactical Role Allocation (e.g., Starting Point Guard):", value=saved_role)

    st.write("**🎯 Front Office Target Board**")
    col_tier, col_valtag = st.columns(2)
    with col_tier:
        tier_input = st.selectbox("Priority", TIER_OPTIONS,
                                  index=TIER_OPTIONS.index(saved_tier) if saved_tier in TIER_OPTIONS else 1)
    with col_valtag:
        value_tag_input = st.selectbox("Value Tag", VALUE_TAG_OPTIONS,
                                       index=VALUE_TAG_OPTIONS.index(saved_value_tag) if saved_value_tag in VALUE_TAG_OPTIONS else 1)

    st.write("**Representation & Personnel Valuation**")
    col_agent, col_agency, col_nil, col_val = st.columns(4)
    with col_agent:
        agent_input = st.text_input("Primary Agent:", value=saved_agent)
    with col_agency:
        agency_input = st.text_input("Agency:", value=saved_agency)
    with col_nil:
        nil_input = st.text_input("Rumored External NIL:", value=saved_nil)
    with col_val:
        val_input = st.text_input("Internal Staff Valuation:", value=saved_val)

    photo_input = st.text_input("Headshot Image Link (Optional manual override):", value=saved_photo)
    notes_input = st.text_area("Detailed Background Intel, Character Evaluations, and General Notes:",
                               value=saved_notes, height=150)

    if st.button("Save Scouting Report"):
        execution_date = datetime.now().strftime("%Y-%m-%d")
        _tid2 = str(p_data["team_espn_id"]) if "team_espn_id" in p_data.index and pd.notna(p_data["team_espn_id"]) else ""
        final_photo = photo_input if photo_input else fetch_espn_headshot(current_player, _tid2)
        conn = sqlite3.connect('scouting_hub.db')
        cursor = conn.cursor()
        cursor.execute('''
                       INSERT INTO player_notes (player_name, team_name, scout_name, priority_tier, position, role,
                                                 rumored_nil, personal_val, agent, agency, photo_url, eval_date,
                                                 notes, value_tag)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(player_name) DO
                       UPDATE SET
                           scout_name=excluded.scout_name, priority_tier=excluded.priority_tier,
                           position=excluded.position, role=excluded.role, rumored_nil=excluded.rumored_nil,
                           personal_val=excluded.personal_val, agent=excluded.agent, agency=excluded.agency,
                           photo_url=excluded.photo_url, eval_date=excluded.eval_date, notes=excluded.notes,
                           value_tag=excluded.value_tag
                       ''',
                       (current_player, p_data["TEAM"], scout_input, tier_input, position_input, role_input,
                        nil_input, val_input, agent_input, agency_input, final_photo, execution_date,
                        notes_input, value_tag_input))
        conn.commit()
        conn.close()
        st.success(f"Scouting report saved for {current_player}.")
        st.rerun()


# ==========================================
# TAB: ONE PAGER (PRINTABLE PLAYER SHEET)
# ==========================================
with tab_onepager:
    st.subheader("Printable One Pager")
    st.caption(
        "Shows the currently active player (set from the Depth Chart, Portal Discovery Engine, or "
        "Front Office Target Board). Click into the sheet to add notes, then use the print button."
    )

    op_player = st.session_state.active_player
    op_match = df_all[df_all["PLAYER"] == op_player]
    op_stats = op_match.iloc[0] if not op_match.empty else None

    conn = sqlite3.connect('scouting_hub.db')
    cursor = conn.cursor()
    cursor.execute(
        "SELECT team_name, position, agent, photo_url, notes, scout_name "
        "FROM player_notes WHERE player_name = ?", (op_player,)
    )
    op_note_row = cursor.fetchone()
    op_roster_row = cursor.execute(
        "SELECT position, height, class_yr FROM roster WHERE bt_name = ? OR player_name = ?",
        (op_player, op_player)
    ).fetchone()
    conn.close()

    op_team = (
        (op_note_row[0] if op_note_row and op_note_row[0] else None)
        or (op_stats["TEAM"] if op_stats is not None else None)
        or "—"
    )
    op_pos = (
        (op_roster_row[0] if op_roster_row and op_roster_row[0] else None)
        or (op_note_row[1] if op_note_row and op_note_row[1] else None)
        or "—"
    )
    op_height = (
        (op_roster_row[1] if op_roster_row and op_roster_row[1] else None)
        or (op_stats["HEIGHT"] if op_stats is not None else None)
        or "—"
    )
    op_class = (
        (op_roster_row[2] if op_roster_row and op_roster_row[2] else None)
        or (op_stats["CLASS"] if op_stats is not None else None)
        or "—"
    )
    op_agent = (op_note_row[2] if op_note_row and op_note_row[2] else None) or "—"
    op_scout = (op_note_row[5] if op_note_row and op_note_row[5] else "")
    op_notes_raw = (op_note_row[4] if op_note_row and op_note_row[4] else "").strip()
    op_photo = op_note_row[3] if op_note_row and op_note_row[3] else ""
    if not op_photo:
        _op_tid = ""
        try:
            _op_row = df_all[df_all["PLAYER"] == op_player]
            if not _op_row.empty and "team_espn_id" in _op_row.columns:
                _op_tid = str(_op_row.iloc[0]["team_espn_id"])
        except Exception:
            pass
        op_photo = fetch_espn_headshot(op_player, _op_tid)

    banner_lines = [ln.strip() for ln in op_notes_raw.split("\n") if ln.strip()][:3]
    banner_bullets_html = "".join(f'<li contenteditable="true">{ln}</li>' for ln in banner_lines)
    banner_bullets_html += '<li contenteditable="true"></li>'

    def _op_num(v, d=1):
        try:
            return f"{float(v):.{d}f}"
        except (TypeError, ValueError):
            return "—"

    def _op_pct(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return "—"
        return f"{v:.1f}%" if v else "—"

    # Same box-score source and Season/Conference/Non-Conf split logic as the Player Card,
    # so the two views always show matching numbers.
    _op_hdr_box = load_consistent_boxscore_stats()
    _op_hdr_row = _op_hdr_box[_op_hdr_box["PLAYER"] == op_player]
    if len(_op_hdr_row) > 1:
        _op_team_match = _op_hdr_row[_op_hdr_row["TEAM"].str.contains(str(op_team), case=False, na=False)]
        if not _op_team_match.empty:
            _op_hdr_row = _op_team_match
    op_hdr = _op_hdr_row.iloc[0] if not _op_hdr_row.empty else None

    op_conf_row = op_nonconf_row = None
    if op_stats is not None:
        _op_conf_map = build_team_conf_map(df_all)
        _op_own_conf = op_stats["CONF"]
        _op_in_conf_ids = tuple(sorted(eid for eid, c in _op_conf_map.items() if c == _op_own_conf))
        if _op_in_conf_ids:
            _op_conf_box = load_consistent_boxscore_stats(conf_ids=_op_in_conf_ids)
            _ocr = _op_conf_box[_op_conf_box["PLAYER"] == op_player]
            op_conf_row = _ocr.iloc[0] if not _ocr.empty else None

            _op_nonconf_box = load_consistent_boxscore_stats(conf_ids=_op_in_conf_ids, exclude_conf_ids=True)
            _oncr = _op_nonconf_box[_op_nonconf_box["PLAYER"] == op_player]
            op_nonconf_row = _oncr.iloc[0] if not _oncr.empty else None

    def _op_stats_row(label, r):
        if r is None:
            return f"<tr><td>{label}</td>" + "<td>—</td>" * 16 + "</tr>"
        return (
            f"<tr><td>{label}</td>"
            f"<td>{_op_num(r.get('GP'), 0)}</td>"
            f"<td>{_op_num(r.get('MPG'))}</td>"
            f"<td>{_op_num(r.get('PPG'))}</td>"
            f"<td>{_op_num(r.get('RPG'))}</td>"
            f"<td>{_op_num(r.get('APG'))}</td>"
            f"<td>{_op_num(r.get('SPG'))}</td>"
            f"<td>{_op_num(r.get('BPG'))}</td>"
            f"<td>{_op_pct(r.get('FG_PCT'))}</td>"
            f"<td>{_op_pct(r.get('EFG'))}</td>"
            f"<td>{_op_pct(r.get('TS'))}</td>"
            f"<td>{_op_pct(r.get('TWO_P'))}</td>"
            f"<td>{_op_pct(r.get('THREE_P'))}</td>"
            f"<td>{_op_pct(r.get('USG'))}</td>"
            f"<td>{_op_pct(r.get('AST_PCT'))}</td>"
            f"<td>{_op_pct(r.get('OR_PCT'))}</td>"
            f"<td>{_op_pct(r.get('DR_PCT'))}</td>"
            "</tr>"
        )

    if op_hdr is not None:
        _op_rows_html = _op_stats_row("Season", op_hdr)
        if op_conf_row is not None or op_nonconf_row is not None:
            _op_rows_html += _op_stats_row("Conference", op_conf_row)
            _op_rows_html += _op_stats_row("Non-Conf", op_nonconf_row)

        stats_table_html = f"""
        <table class="stats">
          <thead><tr>
            <th></th><th>GP</th><th>MPG</th><th>PPG</th><th>RPG</th><th>APG</th><th>SPG</th><th>BPG</th>
            <th>FG%</th><th>EFG%</th><th>TS%</th><th>2P%</th><th>3P%</th><th>USG%</th>
            <th>AST%</th><th>OR%</th><th>DR%</th>
          </tr></thead>
          <tbody>{_op_rows_html}</tbody>
        </table>
        """
    else:
        stats_table_html = (
            '<div style="font-family:Arimo,sans-serif;font-size:12px;color:#8494a5;">'
            'No BartTorvik stat line available for this player yet.</div>'
        )

    staff_notes_html = "".join('<li contenteditable="true"></li>' for _ in range(5))
    photo_style = f"background-image:url('{op_photo}');" if op_photo else ""

    one_pager_html = f"""
<!doctype html><html><head><meta charset="UTF-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Spectral:wght@400;500;600;700;800&family=Arimo:wght@400;700&display=swap" rel="stylesheet">
<style>
  :root {{ --navy: #1b3a5c; --banner-blue: #3a6ea8; --ink: #1b3a5c; --rule: #1b3a5c; --paper: #ffffff; }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #e8e8e8; font-family: 'Spectral', Georgia, serif; color: var(--ink); padding: 24px 0; }}
  .toolbar {{ max-width: 8.5in; margin: 0 auto 14px; display: flex; justify-content: flex-end; gap: 8px; padding: 0 8px; }}
  .toolbar button {{ font-family: 'Arimo', Arial, sans-serif; font-size: 13px; font-weight: 700; padding: 8px 16px;
    border: none; border-radius: 4px; cursor: pointer; background: var(--navy); color: #fff; }}
  .toolbar button.secondary {{ background: #6b7c8f; }}
  .page {{ width: 8.5in; min-height: 11in; margin: 0 auto; background: var(--paper); padding: 0.45in 0.5in 0.5in;
    box-shadow: 0 2px 14px rgba(0,0,0,0.18); }}
  .banner {{ background: var(--banner-blue); color: #fff; padding: 22px 26px 20px; display: flex;
    justify-content: space-between; align-items: flex-start; border-bottom: 3px solid var(--navy); }}
  .banner h1 {{ font-size: 40px; font-weight: 600; line-height: 1.05; margin-bottom: 10px; letter-spacing: 0.2px; }}
  .facts {{ font-size: 15.5px; font-weight: 700; line-height: 1.5; }}
  .facts span.lbl {{ font-weight: 400; opacity: 0.85; }}
  .banner-notes {{ list-style: none; margin-top: 12px; font-size: 13.5px; font-weight: 400; line-height: 1.4; max-width: 5.4in; }}
  .banner-notes li {{ padding-left: 20px; position: relative; margin-bottom: 4px; outline: none; }}
  .banner-notes li::before {{ content: "\\2756"; position: absolute; left: 0; font-size: 10px; opacity: 0.85; }}
  .banner-notes li:empty::after {{ content: "Click to add profile note..."; opacity: 0.5; }}
  .headshot {{ width: 130px; height: 130px; border-radius: 6px; background-color: #dce6f2; background-size: cover;
    background-position: center; display: flex; align-items: center; justify-content: center;
    font-family: 'Arimo', sans-serif; font-size: 11px; color: #4a6a94; flex-shrink: 0; margin-left: 20px; }}
  .sec {{ display: flex; align-items: center; gap: 18px; margin: 26px 0 10px; }}
  .sec h2 {{ font-size: 26px; font-weight: 700; letter-spacing: 0.5px; white-space: nowrap; }}
  .sec .rule {{ flex: 1; height: 5px; background: var(--rule); max-width: 55%; }}
  .statline {{ font-family: 'Arimo', Arial, sans-serif; font-size: 12px; font-weight: 700; margin-bottom: 6px; }}
  table.stats {{ width: 100%; border-collapse: separate; border-spacing: 0; font-family: 'Arimo', Arial, sans-serif;
    font-size: 13px; border: 1px solid #d7dfe7; border-radius: 6px; overflow: hidden; }}
  table.stats th {{ font-weight: 700; text-align: right; padding: 8px 9px; background: var(--navy); color: #eaf0f7;
    font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.04em; }}
  table.stats th:first-child {{ text-align: left; }}
  table.stats td {{ text-align: right; padding: 8px 9px; font-weight: 600; color: #22384e;
    border-bottom: 1px solid #eef1f5; }}
  table.stats tr:last-child td {{ border-bottom: none; }}
  table.stats tr:nth-child(even) td {{ background: #f4f7fa; }}
  table.stats td:first-child {{ text-align: left; font-weight: 700; color: var(--banner-blue); }}
  .notes-hint {{ font-family: 'Arimo', sans-serif; font-size: 11px; color: #8494a5; margin-bottom: 6px; }}
  ul.notes {{ list-style: none; font-size: 18.5px; line-height: 1.65; }}
  ul.notes li {{ padding-left: 30px; position: relative; margin-bottom: 11px; outline: none; min-height: 1.2em; }}
  ul.notes li::before {{ content: "\\2756"; position: absolute; left: 4px; color: var(--navy); font-size: 16px; }}
  ul.notes li:empty::after {{ content: "Click to add note..."; color: #b6c1cc; }}
  .attribution {{ font-family: 'Arimo', sans-serif; font-size: 11px; color: #8494a5; margin-top: 4px; font-style: italic; }}
  .footer-block {{ margin-top: 28px; }}
  .footer-label {{ font-size: 20px; font-weight: 700; letter-spacing: 0.3px; text-decoration: underline;
    margin-bottom: 6px; outline: none; min-height: 1.2em; }}
  .footer-label:empty::after {{ content: "Click to add title..."; color: #b6c1cc; text-decoration: none; }}
  .footer-fill {{ font-family: 'Arimo', sans-serif; font-size: 15px; min-height: 26px; border-bottom: 1px dashed #b9c4cf;
    padding: 4px 2px; outline: none; }}
  .footer-fill:empty::after {{ content: "Click to add instructions for Cronin..."; color: #b6c1cc; }}
  @media print {{
    body {{ background: #fff; padding: 0; }}
    .toolbar {{ display: none; }}
    .page {{ box-shadow: none; width: auto; min-height: auto; padding: 0.25in 0.35in; }}
    .notes-hint {{ display: none; }}
    .banner-notes li:empty, ul.notes li:empty {{ display: none; }}
    .footer-fill:empty::after, .footer-label:empty::after {{ content: ""; }}
    .banner {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .sec .rule {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    table.stats {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  }}
</style>
</head>
<body>
<div class="toolbar">
  <button class="secondary" onclick="addNote()">+ Add Note</button>
  <button onclick="window.print()">Print One Pager</button>
</div>
<div class="page">
  <div class="banner">
    <div>
      <h1>{op_player}</h1>
      <div class="facts">
        <span class="lbl">Current Team:</span> {op_team}<br>
        <span class="lbl">Height:</span> {op_height}<br>
        <span class="lbl">Class:</span> {op_class} &nbsp;&bull;&nbsp; <span class="lbl">Pos:</span> {op_pos}<br>
        <span class="lbl">Agent:</span> {op_agent}
      </div>
      <ul class="banner-notes">{banner_bullets_html}</ul>
    </div>
    <div class="headshot" style="{photo_style}"></div>
  </div>

  <div class="sec"><h2>STATS</h2><div class="rule"></div></div>
  <div class="statline">{op_player} &bull; {op_pos} &bull; {op_height} &bull; {op_class}</div>
  {stats_table_html}

  <div class="sec"><h2>STAFF NOTES</h2><div class="rule"></div></div>
  <div class="notes-hint">Assistants: click any bullet to type. Use + Add Note for more lines. Empty bullets are hidden when printed.</div>
  <ul class="notes" id="notesList">{staff_notes_html}</ul>
  <div class="attribution" contenteditable="true">Notes by: {op_scout}</div>

  <div class="footer-block">
    <div class="footer-label" contenteditable="true"></div>
    <div class="footer-fill" contenteditable="true"></div>
  </div>
  <div class="footer-block">
    <div class="footer-label" contenteditable="true"></div>
    <div class="footer-fill" contenteditable="true"></div>
  </div>
</div>
<script>
  function addNote() {{
    const li = document.createElement('li');
    li.contentEditable = 'true';
    document.getElementById('notesList').appendChild(li);
    li.focus();
  }}
</script>
</body>
</html>
"""
    components.html(one_pager_html, height=1450, scrolling=True)


# ==========================================
# TAB 2: PORTAL DISCOVERY ENGINE
# ==========================================
with tab2:
    st.subheader("Database Sifting & Portal Filtering")

    st.write("**Competition Filter**")
    _disc_split = st.radio(
        "Discovery competition split",
        ["All Games", "Top 100", "Top 50"],
        horizontal=True,
        key="discovery_split",
        label_visibility="collapsed",
    )
    _disc_max_rank = 100 if _disc_split == "Top 100" else (50 if _disc_split == "Top 50" else None)
    if _disc_max_rank is not None and _gl_ready:
        disc_base_df = load_consistent_boxscore_stats(_disc_max_rank).rename(columns={
            "OR_PCT": "OR", "DR_PCT": "DR", "AST_PCT": "AST",
            "BLK_PCT": "BLK", "STL_PCT": "STL",
        })
        _model_cols = ["PLAYER", "CONF", "CLASS", "HEIGHT",
                       "BPM", "OBPM", "DBPM", "PRPG", "MIN_PCT", "ORTG", "THREE_P_100"]
        _meta = df_all[[c for c in _model_cols if c in df_all.columns]].drop_duplicates("PLAYER")
        disc_base_df = disc_base_df.merge(_meta, on="PLAYER", how="left")
    elif _disc_max_rank is not None and not _gl_ready:
        st.info(
            f"**{_disc_split} game logs not yet built.** "
            "Run `python3 build_game_logs.py` to enable this split. Showing All Games in the meantime."
        )
        disc_base_df = df_all
    else:
        disc_base_df = df_all

    with st.expander("Advanced Database Filters", expanded=False):
        st.write("Adjust parameters to filter the active portal pool. Leaving fields blank or sliders at their maximum range includes all players.")

        col_cat1, col_cat2, col_cat3 = st.columns(3)
        with col_cat1:
            conf_options = sorted(list(df_all["CONF"].unique()))
            selected_confs = st.multiselect("Filter by Conference:", conf_options)
        with col_cat2:
            team_options = sorted(list(df_all["TEAM"].unique()))
            selected_teams = st.multiselect("Filter by Program / Team:", team_options)
        with col_cat3:
            class_options = sorted(list(df_all["CLASS"].dropna().unique()))
            selected_classes = st.multiselect("Filter by Class / Eligibility:", class_options)

        st.write("**Statistical Range Bounds**")
        f1, f2, f3, f4 = st.columns(4)

        with f1:
            st.markdown("**Volume & Impact**")
            min_pct = st.slider("Min %",     0.0, 100.0, (0.0, 100.0), step=1.0)
            usg     = st.slider("Usage %",   0.0,  50.0, (0.0,  50.0), step=1.0)
            bpm     = st.slider("Box BPM",  -20.0, 30.0, (-20.0, 30.0), step=0.5)
            obpm    = st.slider("Off. BPM", -20.0, 30.0, (-20.0, 30.0), step=0.5)
            dbpm    = st.slider("Def. BPM", -20.0, 20.0, (-20.0, 20.0), step=0.5)

        with f2:
            st.markdown("**Efficiency & Scoring**")
            ortg  = st.slider("O-Rating", 0.0, 150.0, (0.0, 150.0), step=1.0)
            efg   = st.slider("eFG %",    0.0, 100.0, (0.0, 100.0), step=1.0)
            ts    = st.slider("TS %",     0.0, 100.0, (0.0, 100.0), step=1.0)
            two_p = st.slider("2P %",     0.0, 100.0, (0.0, 100.0), step=1.0)

        with f3:
            st.markdown("**Shooting & Frequency**")
            three_p     = st.slider("3P %",                0.0, 100.0, (0.0, 100.0), step=1.0)
            three_p_100 = st.slider("3PA/100",              0.0,  30.0, (0.0,  30.0), step=0.5)
            ftr         = st.slider("Free Throw Rate (FTR)", 0.0, 150.0, (0.0, 150.0), step=1.0)

        with f4:
            st.markdown("**Playmaking & Rebounding**")
            ast = st.slider("Ast %",   0.0,  60.0, (0.0,  60.0), step=1.0)
            tov = st.slider("TO %",    0.0, 100.0, (0.0, 100.0), step=1.0)
            orb = st.slider("O-Reb %", 0.0,  50.0, (0.0,  50.0), step=1.0)
            drb = st.slider("D-Reb %", 0.0,  50.0, (0.0,  50.0), step=1.0)
            blk = st.slider("Blk %",   0.0,  30.0, (0.0,  30.0), step=0.5)
            stl = st.slider("Stl %",   0.0,  15.0, (0.0,  15.0), step=0.5)

    filtered_df = disc_base_df.copy()

    if selected_confs:
        filtered_df = filtered_df[filtered_df["CONF"].isin(selected_confs)]
    if selected_teams:
        filtered_df = filtered_df[filtered_df["TEAM"].isin(selected_teams)]
    if selected_classes:
        filtered_df = filtered_df[filtered_df["CLASS"].isin(selected_classes)]

    def _col_filter(df, col, lo, hi):
        return df[df[col].between(lo, hi)] if col in df.columns else df

    filtered_df = _col_filter(filtered_df, "MIN_PCT",   min_pct[0],    min_pct[1])
    filtered_df = _col_filter(filtered_df, "BPM",       bpm[0],        bpm[1])
    filtered_df = _col_filter(filtered_df, "OBPM",      obpm[0],       obpm[1])
    filtered_df = _col_filter(filtered_df, "DBPM",      dbpm[0],       dbpm[1])
    filtered_df = _col_filter(filtered_df, "ORTG",      ortg[0],       ortg[1])
    filtered_df = _col_filter(filtered_df, "USG",       usg[0],        usg[1])
    filtered_df = _col_filter(filtered_df, "EFG",       efg[0],        efg[1])
    filtered_df = _col_filter(filtered_df, "TS",        ts[0],         ts[1])
    filtered_df = _col_filter(filtered_df, "OR",        orb[0],        orb[1])
    filtered_df = _col_filter(filtered_df, "DR",        drb[0],        drb[1])
    filtered_df = _col_filter(filtered_df, "AST",       ast[0],        ast[1])
    filtered_df = _col_filter(filtered_df, "TO",        tov[0],        tov[1])
    filtered_df = _col_filter(filtered_df, "BLK",       blk[0],        blk[1])
    filtered_df = _col_filter(filtered_df, "STL",       stl[0],        stl[1])
    filtered_df = _col_filter(filtered_df, "FTR",       ftr[0],        ftr[1])
    filtered_df = _col_filter(filtered_df, "TWO_P",     two_p[0],      two_p[1])
    filtered_df = _col_filter(filtered_df, "THREE_P",   three_p[0],    three_p[1])
    filtered_df = _col_filter(filtered_df, "THREE_P_100", three_p_100[0], three_p_100[1])

    sort_col = "PRPG" if "PRPG" in filtered_df.columns else "PPG" if "PPG" in filtered_df.columns else filtered_df.columns[0]
    filtered_df = filtered_df.sort_values(by=sort_col, ascending=False)

    _hidden = {"team_espn_id"}
    ordered_cols = ["PLAYER", "TEAM", "CONF", "CLASS", "HEIGHT", "GP", "PPG", "PRPG", "BPM", "MIN_PCT", "USG", "EFG", "TS", "AST", "OR", "DR", "BLK", "STL"]
    ordered_cols = [c for c in ordered_cols if c in filtered_df.columns]
    remaining_cols = [c for c in filtered_df.columns if c not in ordered_cols and c not in _hidden]
    filtered_df = filtered_df[ordered_cols + remaining_cols]

    st.write(f"**Filter Results ({st.session_state.discovery_split}):** Found {len(filtered_df)} profiles matching criteria.")

    # A widget callback only fires when *this* widget's own selection genuinely
    # changes from a user click on it — unlike checking event_discovery.selection.rows
    # in the main body, which re-reads the same still-selected row on every rerun
    # (including ones triggered by unrelated widgets, like picking a new player in the
    # Player Card dropdown) and would keep forcing active_player back to this row.
    def _on_portal_row_click():
        sel = st.session_state.get("discovery_df_select", {})
        rows = sel.get("selection", {}).get("rows", [])
        if rows:
            st.session_state.active_player = filtered_df.iloc[rows[0]]["PLAYER"]
            st.session_state.go_to_profile = True

    # BartTorvik's raw feed comes back at full float precision (e.g. 14.6471), which is what
    # made this read like an unformatted spreadsheet export — round it for display via
    # column_config instead of mutating the underlying data used for filtering/sorting above.
    _pct_cols = {"USG", "EFG", "TS", "AST", "OR", "DR", "BLK", "STL", "FTR", "FT_PCT",
                 "TWO_P", "THREE_P", "THREE_P_100", "MIN_PCT"}
    _decimal_cols = {"PPG", "PRPG", "BPM", "OBPM", "DBPM", "SOS", "RPG", "APG", "TO"}
    _discovery_col_config = {
        "PLAYER": st.column_config.TextColumn("Player", pinned=True),
        "TEAM": st.column_config.TextColumn("Team"),
        "CONF": st.column_config.TextColumn("Conf"),
        "CLASS": st.column_config.TextColumn("Class"),
        "HEIGHT": st.column_config.TextColumn("Height"),
        "GP": st.column_config.NumberColumn("GP", format="%d"),
    }
    for _c in filtered_df.columns:
        if _c in _discovery_col_config:
            continue
        if _c in _pct_cols:
            _discovery_col_config[_c] = st.column_config.NumberColumn(_c, format="%.1f%%")
        elif _c in _decimal_cols:
            _discovery_col_config[_c] = st.column_config.NumberColumn(_c, format="%.1f")

    st.markdown(
        "<style>"
        "div[data-testid='stDataFrame'] { border: 1px solid #d7dfe7; border-radius: 8px; "
        "overflow: hidden; box-shadow: 0 1px 3px rgba(15,23,42,0.06); }"
        "</style>",
        unsafe_allow_html=True,
    )

    event_discovery = st.dataframe(
        filtered_df,
        hide_index=True,
        on_select=_on_portal_row_click,
        selection_mode="single-row",
        height=650,
        column_config=_discovery_col_config,
        key="discovery_df_select",
    )

    if event_discovery.selection.rows:
        clicked_idx = event_discovery.selection.rows[0]
        clicked_player = filtered_df.iloc[clicked_idx]["PLAYER"]
        st.caption(f"🎯 **{clicked_player}** selected — their full card is loaded on the "
                   f"**Player Card** and **One Pager** tabs.")


# ==========================================
# TAB 3: FRONT OFFICE TARGET BOARD
# ==========================================
with tab3:
    st.subheader("Central Board Records")
    conn = sqlite3.connect('scouting_hub.db')
    db_df = pd.read_sql_query('''
        SELECT player_name AS PLAYER, team_name AS TEAM, position AS POS, role AS ROLE,
               agent AS AGENT, agency AS AGENCY, rumored_nil AS [RUMORED NIL],
               personal_val AS [OUR VALUE], eval_date AS [LOG DATE],
               scout_name AS SCOUT, notes AS NOTES, priority_tier AS TIER,
               value_tag AS [VALUE TAG]
        FROM player_notes
        WHERE priority_tier IS NOT NULL AND priority_tier != ''
    ''', conn)
    conn.close()

    VALUE_TAG_COLORS = {"Undervalued": "#16a34a", "Overvalued": "#dc2626", "Properly Valued": "#64748B"}

    if db_df.empty:
        st.info("No targets currently logged onto the system database. Use the **Add to Board** "
                 "widget on the Player Card tab to log one.")
    else:
        card_benchmarks_board = build_national_benchmarks(df_all)
        for tier in ["High Priority", "Mid Priority", "Low Priority"]:
            tier_filtered = db_df[db_df["TIER"] == tier]
            st.markdown(f"### {tier} ({len(tier_filtered)})")
            if tier_filtered.empty:
                st.write("*No targets assigned to this category tier.*")
                continue

            for _, row in tier_filtered.iterrows():
                p_name = row["PLAYER"]
                v_tag = row["VALUE TAG"] if row["VALUE TAG"] else "Properly Valued"
                v_color = VALUE_TAG_COLORS.get(v_tag, "#64748B")

                with st.expander(f"{p_name}  ·  {row['TEAM'] or '—'}  ·  {v_tag}"):
                    badge_html = (
                        f"<span style='background:{v_color}1A;color:{v_color};border:1px solid {v_color}55;"
                        f"padding:3px 10px;border-radius:4px;font-size:11px;font-weight:700;'>{v_tag.upper()}</span>"
                    )
                    if row["SCOUT"]:
                        badge_html += (f"&nbsp;&nbsp;<span style='font-size:12px;color:#475569;'>"
                                       f"Scout: {row['SCOUT']}</span>")
                    st.markdown(badge_html, unsafe_allow_html=True)
                    if row["ROLE"]:
                        st.caption(f"Role: {row['ROLE']}")
                    if row["NOTES"]:
                        st.write(row["NOTES"])

                    match_row = df_all[df_all["PLAYER"] == p_name]
                    curated_row = next((p for p in PORTAL_PLAYERS if p["name"] == p_name), None)
                    card_p = curated_row or {
                        "name": p_name,
                        "school": row["TEAM"] or (match_row.iloc[0]["TEAM"] if not match_row.empty else ""),
                        "pos": row["POS"] or "",
                        "cls": match_row.iloc[0]["CLASS"] if not match_row.empty else "",
                        "height": match_row.iloc[0]["HEIGHT"] if not match_row.empty else "",
                        "tier": tier, "projection": "", "role": row["ROLE"] or "", "tags": [],
                    }
                    components.html(
                        render_tile_card_html(card_p, df_all, card_benchmarks_board, show_writeup=False),
                        height=760, scrolling=True,
                    )

                    if st.button(f"Open full Player Card", key=f"goto_{tier}_{p_name}"):
                        st.session_state.active_player = p_name
                        st.session_state.go_to_profile = True
                        st.rerun()


# ==========================================
# TAB 4: PRINTS / VISUAL BOARD VIEW
# ==========================================
with tab4:
    st.subheader("Staff Roster Print Layout")
    st.write("Clean card formatting optimized for direct browser printing (File -> Print).")

    filter_tier = st.selectbox("Select Target Priority Tier to Display:",
                               ["High Priority", "Mid Priority", "Low Priority", "All Records"])

    conn = sqlite3.connect('scouting_hub.db')
    if filter_tier == "All Records":
        board_data = pd.read_sql_query("SELECT * FROM player_notes", conn)
    else:
        board_data = pd.read_sql_query("SELECT * FROM player_notes WHERE priority_tier = ?", conn,
                                       params=(filter_tier,))

    for idx, row in board_data.iterrows():
        if not row["photo_url"]:
            _board_tid = ""
            try:
                _br = df_all[df_all["PLAYER"] == row["player_name"]]
                if not _br.empty and "team_espn_id" in _br.columns:
                    _board_tid = str(_br.iloc[0]["team_espn_id"])
            except Exception:
                pass
            fetched_img = fetch_espn_headshot(row["player_name"], _board_tid)
            if fetched_img:
                cursor = conn.cursor()
                cursor.execute("UPDATE player_notes SET photo_url = ? WHERE player_name = ?",
                               (fetched_img, row["player_name"]))
                conn.commit()
                board_data.at[idx, "photo_url"] = fetched_img
    conn.close()

    if board_data.empty:
        st.warning("No tracked player records match the active criteria tier selection.")
    else:
        pos_columns = ["PG", "CG", "W", "F", "C"]
        st_cols = st.columns(5)

        for i, pos_group in enumerate(pos_columns):
            with st_cols[i]:
                st.markdown(
                    "<div style=\"background-color:#1E3A8A;color:white;font-weight:bold;"
                    "text-align:center;padding:6px;border-radius:4px;margin-bottom:12px;\">"
                    + pos_group + "</div>",
                    unsafe_allow_html=True
                )

                group_players = board_data[board_data["position"] == pos_group]

                if group_players.empty:
                    st.caption("No targets assigned")
                else:
                    for _, player in group_players.iterrows():
                        p_name = player["player_name"]
                        stat_match = df_all[df_all["PLAYER"] == p_name]
                        if not stat_match.empty:
                            s = stat_match.iloc[0]
                            stat_line = f"BPM: {s['BPM']} | USG: {s['USG']}% | eFG: {s['EFG']}%"
                            meta_line = f"{s['HEIGHT']} | {s['CLASS']}"
                        else:
                            stat_line = "No active metrics line linked"
                            meta_line = "N/A"

                        photo = player["photo_url"] if player["photo_url"] else "https://via.placeholder.com/150"
                        role_label = player["role"] if player["role"] else "Unassigned Role"
                        team_name = player["team_name"]

                        st.markdown(
                            "<div style=\"border:1px solid #CBD5E1;border-radius:6px;padding:10px;"
                            "margin-bottom:12px;background-color:#FFFFFF;box-shadow:1px 1px 3px rgba(0,0,0,0.05);\">"
                            "<table style=\"width:100%;border-collapse:collapse;margin-bottom:4px;\">"
                            "<tr>"
                            "<td style=\"width:95px;vertical-align:top;\">"
                            "<div style=\"width:90px;height:90px;display:flex;align-items:center;justify-content:center;"
                            "border-radius:4px;border:1px solid #E2E8F0;background-color:#F8FAFC;overflow:hidden;\">"
                            "<img src=\"" + photo + "\" onerror=\"this.onerror=null;this.src='https://upload.wikimedia.org/wikipedia/commons/8/89/Portrait_Placeholder.png';\" "
                            "style=\"max-width:100%;max-height:100%;object-fit:contain;\"/>"
                            "</div></td>"
                            "<td style=\"padding-left:12px;vertical-align:top;line-height:1.3;\">"
                            "<div style=\"font-size:14px;font-weight:bold;color:#0F172A;\">" + p_name + "</div>"
                            "<div style=\"font-size:11px;color:#475569;font-weight:600;\">" + team_name + "</div>"
                            "<div style=\"font-size:11px;color:#64748B;\">" + meta_line + "</div>"
                            "</td></tr></table>"
                            "<div style=\"border-top:1px dashed #E2E8F0;padding-top:4px;font-size:10px;font-weight:600;color:#1E40AF;\">"
                            "🎯 " + role_label + "</div>"
                            "<div style=\"font-size:9.5px;font-weight:bold;color:#475569;margin-top:2px;\">"
                            "📊 " + stat_line + "</div>"
                            "</div>",
                            unsafe_allow_html=True
                        )
