"""
fetch_cbb_analytics.py
----------------------
Pulls CBB Analytics data for UCLA into scouting_hub.db.

Tables populated:
  cbb_player_agg        — season/split aggregated box + advanced stats
  cbb_player_agg_pbp    — PBP-derived stats (shot zones, assisted %, creation, etc.)
  cbb_player_game_logs  — game-by-game box scores
  cbb_lineups           — 5-man lineup efficiency
  cbb_on_off            — on/off/diff splits per player
  cbb_meta              — competition and team ID reference

Run once per season, or re-run to refresh.
    cd /Users/matthewknauer/Desktop/ucla-basketball
    python3 fetch_cbb_analytics.py
"""

import sqlite3
import requests
import json
import time
import warnings

warnings.filterwarnings("ignore")

API_KEY    = "s4gxa7mmocarvlqgchcgtcg0uad3ebzi"
BASE_URL   = "https://rest.cbbanalytics.com/v3"
HEADERS    = {"x-api-key": API_KEY}
DB_PATH    = "scouting_hub.db"

UCLA_TEAM_ID = 104360

# All available men's seasons with PBP (2019+)
COMPETITIONS = {
    2026: 41097,
    2025: 38409,
    2024: 36046,
    2023: 33533,
    2022: 30629,
    2021: 27693,
    2020: 24996,
}

# Scopes to pull for agg stats. "season" = full season, others are key splits.
AGG_SCOPES = ["season", "confReg", "home", "away", "l5g", "l10g",
               "quad1", "quad2", "quad3", "quad4", "wins", "losses", "clutch"]


def get(url, params=None, retries=5):
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, params=params or {}, timeout=20)
            if r.status_code == 429:
                wait = 30 * (attempt + 1)
                print(f"  Rate limited, sleeping {wait}s...")
                time.sleep(wait)
                continue
            if r.status_code != 200:
                print(f"  HTTP {r.status_code} for {url} — skipping")
                return {}
            return r.json()
        except Exception as e:
            print(f"  Error: {e}, retrying in 10s...")
            time.sleep(10)
    return {}


def paginate(url, params=None):
    params = dict(params or {})
    params.setdefault("limit", 1000)
    results = []
    cursor = None
    while True:
        if cursor:
            params["after"] = cursor
        d = get(url, params)
        meta = d.get("response", {}).get("meta", {})
        batch = d.get("response", {}).get("data", [])
        results.extend(batch)
        if not meta.get("hasMore") or not batch:
            break
        cursor = meta.get("nextCursor")
        time.sleep(0.3)
    return results


def init_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cbb_meta (
            key TEXT PRIMARY KEY, value TEXT);

        CREATE TABLE IF NOT EXISTS cbb_player_agg (
            id TEXT PRIMARY KEY,
            competition_id INTEGER,
            season INTEGER,
            team_id INTEGER,
            player_id INTEGER,
            player_name TEXT,
            scope TEXT,
            position TEXT,
            class_yr TEXT,
            is_transfer INTEGER,
            gp INTEGER,
            gs INTEGER,
            mins REAL,
            poss REAL,
            pts REAL,
            reb REAL,
            orb REAL,
            drb REAL,
            ast REAL,
            stl REAL,
            blk REAL,
            tov REAL,
            pf REAL,
            pfd REAL,
            fgm REAL,
            fga REAL,
            fgm2 REAL,
            fga2 REAL,
            fgm3 REAL,
            fga3 REAL,
            ftm REAL,
            fta REAL,
            plus_minus REAL,
            fg_pct REAL,
            fg2_pct REAL,
            fg3_pct REAL,
            efg_pct REAL,
            ts_pct REAL,
            ft_pct REAL,
            fga3_rate REAL,
            orb_pct REAL,
            drb_pct REAL,
            reb_pct REAL,
            ast_pct REAL,
            ast_tov REAL,
            stl_pct REAL,
            blk_pct REAL,
            tov_pct REAL,
            usage_pct REAL,
            per REAL,
            warp REAL,
            ws REAL,
            ortg REAL,
            drtg REAL,
            rapm REAL,
            orapm REAL,
            drapm REAL,
            vps REAL,
            updated TEXT
        );

        CREATE TABLE IF NOT EXISTS cbb_player_agg_pbp (
            id TEXT PRIMARY KEY,
            competition_id INTEGER,
            season INTEGER,
            team_id INTEGER,
            player_id INTEGER,
            player_name TEXT,
            scope TEXT,
            gp INTEGER,
            mins REAL,
            pts REAL,
            pts_created REAL,
            fga REAL,
            fgm REAL,
            fga2 REAL,
            fgm2 REAL,
            fga3 REAL,
            fgm3 REAL,
            ast REAL,
            ast2 REAL,
            ast3 REAL,
            orb REAL,
            stl REAL,
            blk REAL,
            tov REAL,
            pf REAL,
            fta REAL,
            ftm REAL,
            usage_pct REAL,
            ts_pct REAL,
            efg_pct REAL,
            fga3_rate REAL,
            fg_pct REAL,
            fg2_pct REAL,
            fg3_pct REAL,
            ft_pct REAL,
            atr2_fga REAL, atr2_fgm REAL, atr2_fg_pct REAL, atr2_fga_freq REAL,
            paint2_fga REAL, paint2_fgm REAL, paint2_fg_pct REAL, paint2_fga_freq REAL,
            mid2_fga REAL, mid2_fgm REAL, mid2_fg_pct REAL, mid2_fga_freq REAL,
            c3_fga REAL, c3_fgm REAL, c3_fg_pct REAL, c3_fga_freq REAL,
            atb3_fga REAL, atb3_fgm REAL, atb3_fg_pct REAL, atb3_fga_freq REAL,
            lc3_fga REAL, lc3_fgm REAL, lc3_fg_pct REAL,
            rc3_fga REAL, rc3_fgm REAL, rc3_fg_pct REAL,
            rim3s_fga REAL, rim3s_fgm REAL, rim3s_fg_pct REAL, rim3s_fga_freq REAL,
            lane2_fga REAL, lane2_fgm REAL, lane2_fg_pct REAL, lane2_fga_freq REAL,
            dunk_fga REAL, dunk_fgm REAL,
            layup_fga REAL, layup_fgm REAL,
            astd_pct REAL,
            fgm2_astd_pct REAL,
            fgm3_astd_pct REAL,
            pct_ast_atr2 REAL,
            pct_ast_paint2 REAL,
            pct_ast_mid2 REAL,
            pct_ast_c3 REAL,
            pct_ast_atb3 REAL,
            indvl_stop_pct REAL,
            and1_pct REAL,
            orb_fg_pct REAL,
            left_fg_pct REAL,
            right_fg_pct REAL,
            center_fg_pct REAL,
            updated TEXT
        );

        CREATE TABLE IF NOT EXISTS cbb_player_game_logs (
            id TEXT PRIMARY KEY,
            competition_id INTEGER,
            season INTEGER,
            team_id INTEGER,
            player_id INTEGER,
            player_name TEXT,
            game_id TEXT,
            game_date TEXT,
            opponent TEXT,
            is_home INTEGER,
            is_win INTEGER,
            gp INTEGER,
            gs INTEGER,
            mins REAL,
            pts INTEGER,
            reb INTEGER,
            orb INTEGER,
            drb INTEGER,
            ast INTEGER,
            stl INTEGER,
            blk INTEGER,
            tov INTEGER,
            pf INTEGER,
            pfd INTEGER,
            fgm INTEGER,
            fga INTEGER,
            fgm2 INTEGER,
            fga2 INTEGER,
            fgm3 INTEGER,
            fga3 INTEGER,
            ftm INTEGER,
            fta INTEGER,
            plus_minus INTEGER,
            fg_pct REAL,
            fg3_pct REAL,
            ts_pct REAL,
            efg_pct REAL,
            usage_pct REAL,
            updated TEXT
        );

        CREATE TABLE IF NOT EXISTS cbb_lineups (
            id TEXT PRIMARY KEY,
            competition_id INTEGER,
            season INTEGER,
            team_id INTEGER,
            scope TEXT,
            p_name1 TEXT, p_name2 TEXT, p_name3 TEXT, p_name4 TEXT, p_name5 TEXT,
            p_id1 INTEGER, p_id2 INTEGER, p_id3 INTEGER, p_id4 INTEGER, p_id5 INTEGER,
            gp INTEGER,
            mins REAL,
            poss REAL,
            pts REAL,
            pts_agst REAL,
            plus_minus REAL,
            ortg REAL,
            drtg REAL,
            net_rtg REAL,
            fgm REAL,
            fga REAL,
            updated TEXT
        );

        CREATE TABLE IF NOT EXISTS cbb_on_off (
            id TEXT PRIMARY KEY,
            competition_id INTEGER,
            season INTEGER,
            team_id INTEGER,
            player_id INTEGER,
            player_name TEXT,
            scope TEXT,
            on_off_diff TEXT,
            mins REAL,
            poss REAL,
            ortg REAL,
            drtg REAL,
            net_rtg REAL,
            updated TEXT
        );
    """)
    conn.commit()


def upsert_player_agg(conn, rows):
    conn.executemany("""
        INSERT OR REPLACE INTO cbb_player_agg VALUES (
            :id,:competition_id,:season,:team_id,:player_id,:player_name,:scope,
            :position,:class_yr,:is_transfer,
            :gp,:gs,:mins,:poss,:pts,:reb,:orb,:drb,:ast,:stl,:blk,:tov,:pf,:pfd,
            :fgm,:fga,:fgm2,:fga2,:fgm3,:fga3,:ftm,:fta,:plus_minus,
            :fg_pct,:fg2_pct,:fg3_pct,:efg_pct,:ts_pct,:ft_pct,:fga3_rate,
            :orb_pct,:drb_pct,:reb_pct,:ast_pct,:ast_tov,:stl_pct,:blk_pct,
            :tov_pct,:usage_pct,:per,:warp,:ws,:ortg,:drtg,:rapm,:orapm,:drapm,
            :vps,:updated)
    """, rows)
    conn.commit()


def upsert_player_agg_pbp(conn, rows):
    conn.executemany("""
        INSERT OR REPLACE INTO cbb_player_agg_pbp VALUES (
            :id,:competition_id,:season,:team_id,:player_id,:player_name,:scope,
            :gp,:mins,:pts,:pts_created,:fga,:fgm,:fga2,:fgm2,:fga3,:fgm3,
            :ast,:ast2,:ast3,:orb,:stl,:blk,:tov,:pf,:fta,:ftm,
            :usage_pct,:ts_pct,:efg_pct,:fga3_rate,:fg_pct,:fg2_pct,:fg3_pct,:ft_pct,
            :atr2_fga,:atr2_fgm,:atr2_fg_pct,:atr2_fga_freq,
            :paint2_fga,:paint2_fgm,:paint2_fg_pct,:paint2_fga_freq,
            :mid2_fga,:mid2_fgm,:mid2_fg_pct,:mid2_fga_freq,
            :c3_fga,:c3_fgm,:c3_fg_pct,:c3_fga_freq,
            :atb3_fga,:atb3_fgm,:atb3_fg_pct,:atb3_fga_freq,
            :lc3_fga,:lc3_fgm,:lc3_fg_pct,
            :rc3_fga,:rc3_fgm,:rc3_fg_pct,
            :rim3s_fga,:rim3s_fgm,:rim3s_fg_pct,:rim3s_fga_freq,
            :lane2_fga,:lane2_fgm,:lane2_fg_pct,:lane2_fga_freq,
            :dunk_fga,:dunk_fgm,:layup_fga,:layup_fgm,
            :astd_pct,:fgm2_astd_pct,:fgm3_astd_pct,
            :pct_ast_atr2,:pct_ast_paint2,:pct_ast_mid2,:pct_ast_c3,:pct_ast_atb3,
            :indvl_stop_pct,:and1_pct,:orb_fg_pct,
            :left_fg_pct,:right_fg_pct,:center_fg_pct,:updated)
    """, rows)
    conn.commit()


def parse_agg(d, comp_id, season):
    rid = d.get("_id", "")
    return {
        "id": rid,
        "competition_id": comp_id,
        "season": season,
        "team_id": d.get("teamId"),
        "player_id": d.get("playerId"),
        "player_name": d.get("fullName"),
        "scope": d.get("scope"),
        "position": d.get("position"),
        "class_yr": d.get("classYr"),
        "is_transfer": int(bool(d.get("isTransfer"))),
        "gp": d.get("gp"), "gs": d.get("gs"),
        "mins": d.get("mins"), "poss": d.get("poss"),
        "pts": d.get("ptsScored"), "reb": d.get("reb"),
        "orb": d.get("orb"), "drb": d.get("drb"),
        "ast": d.get("ast"), "stl": d.get("stl"),
        "blk": d.get("blk"), "tov": d.get("tov"),
        "pf": d.get("pf"), "pfd": d.get("pfd"),
        "fgm": d.get("fgm"), "fga": d.get("fga"),
        "fgm2": d.get("fgm2"), "fga2": d.get("fga2"),
        "fgm3": d.get("fgm3"), "fga3": d.get("fga3"),
        "ftm": d.get("ftm"), "fta": d.get("fta"),
        "plus_minus": d.get("plusMinus"),
        "fg_pct": d.get("fgPct"), "fg2_pct": d.get("fg2Pct"),
        "fg3_pct": d.get("fg3Pct"), "efg_pct": d.get("efgPct"),
        "ts_pct": d.get("tsPct"), "ft_pct": d.get("ftPct"),
        "fga3_rate": d.get("fga3Rate"),
        "orb_pct": d.get("orbPct"), "drb_pct": d.get("drbPct"),
        "reb_pct": d.get("rebPct"), "ast_pct": d.get("astPct"),
        "ast_tov": d.get("astTov"), "stl_pct": d.get("stlPct"),
        "blk_pct": d.get("blkPct"), "tov_pct": d.get("tovPct"),
        "usage_pct": d.get("usagePct"),
        "per": d.get("per"), "warp": d.get("warp"), "ws": d.get("ws"),
        "ortg": d.get("ortgPlayer"), "drtg": d.get("drtgPlayer"),
        "rapm": d.get("rapm"), "orapm": d.get("orapm"), "drapm": d.get("drapm"),
        "vps": d.get("vps"),
        "updated": d.get("updated"),
    }


def parse_agg_pbp(d, comp_id, season):
    return {
        "id": d.get("_id", ""),
        "competition_id": comp_id, "season": season,
        "team_id": d.get("teamId"), "player_id": d.get("playerId"),
        "player_name": d.get("fullName"), "scope": d.get("scope"),
        "gp": d.get("gpPbp"), "mins": d.get("minsPbp"),
        "pts": d.get("ptsScored"), "pts_created": d.get("ptsCreated"),
        "fga": d.get("fga"), "fgm": d.get("fgm"),
        "fga2": d.get("fga2"), "fgm2": d.get("fgm2"),
        "fga3": d.get("fga3"), "fgm3": d.get("fgm3"),
        "ast": d.get("ast"), "ast2": d.get("ast2"), "ast3": d.get("ast3"),
        "orb": d.get("orb"), "stl": d.get("stl"), "blk": d.get("blk"),
        "tov": d.get("tov"), "pf": d.get("pf"),
        "fta": d.get("fta"), "ftm": d.get("ftm"),
        "usage_pct": d.get("usagePct"), "ts_pct": d.get("tsPct"),
        "efg_pct": d.get("efgPct"), "fga3_rate": d.get("fga3Rate"),
        "fg_pct": d.get("fgPct"), "fg2_pct": d.get("fg2Pct"),
        "fg3_pct": d.get("fg3Pct"), "ft_pct": d.get("ftPct"),
        "atr2_fga": d.get("atr2Fga"), "atr2_fgm": d.get("atr2Fgm"),
        "atr2_fg_pct": d.get("atr2FgPct"), "atr2_fga_freq": d.get("atr2FgaFreq"),
        "paint2_fga": d.get("paint2Fga"), "paint2_fgm": d.get("paint2Fgm"),
        "paint2_fg_pct": d.get("paint2FgPct"), "paint2_fga_freq": d.get("paint2FgaFreq"),
        "mid2_fga": d.get("mid2Fga"), "mid2_fgm": d.get("mid2Fgm"),
        "mid2_fg_pct": d.get("mid2FgPct"), "mid2_fga_freq": d.get("mid2FgaFreq"),
        "c3_fga": d.get("c3Fga"), "c3_fgm": d.get("c3Fgm"),
        "c3_fg_pct": d.get("c3FgPct"), "c3_fga_freq": d.get("c3FgaFreq"),
        "atb3_fga": d.get("atb3Fga"), "atb3_fgm": d.get("atb3Fgm"),
        "atb3_fg_pct": d.get("atb3FgPct"), "atb3_fga_freq": d.get("atb3FgaFreq"),
        "lc3_fga": d.get("lc3Fga"), "lc3_fgm": d.get("lc3Fgm"), "lc3_fg_pct": d.get("lc3FgPct"),
        "rc3_fga": d.get("rc3Fga"), "rc3_fgm": d.get("rc3Fgm"), "rc3_fg_pct": d.get("rc3FgPct"),
        "rim3s_fga": d.get("rim3sFga"), "rim3s_fgm": d.get("rim3sFgm"),
        "rim3s_fg_pct": d.get("rim3sFgPct"), "rim3s_fga_freq": d.get("rim3sFgaFreq"),
        "lane2_fga": d.get("lane2Fga"), "lane2_fgm": d.get("lane2Fgm"),
        "lane2_fg_pct": d.get("lane2FgPct"), "lane2_fga_freq": d.get("lane2FgaFreq"),
        "dunk_fga": d.get("dunkFga"), "dunk_fgm": d.get("dunkFgm"),
        "layup_fga": d.get("layupFga"), "layup_fgm": d.get("layupFgm"),
        "astd_pct": d.get("fgmAstdPct"),
        "fgm2_astd_pct": d.get("fgm2AstdPct"),
        "fgm3_astd_pct": d.get("fgm3AstdPct"),
        "pct_ast_atr2": d.get("pctAstAtr2"),
        "pct_ast_paint2": d.get("pctAstPaint2"),
        "pct_ast_mid2": d.get("pctAstMid2"),
        "pct_ast_c3": d.get("pctAstC3"),
        "pct_ast_atb3": d.get("pctAstAtb3"),
        "indvl_stop_pct": d.get("indvlStopPct"),
        "and1_pct": d.get("and1Pct"),
        "orb_fg_pct": d.get("orbFgPct"),
        "left_fg_pct": d.get("leftFgPct"),
        "right_fg_pct": d.get("rightFgPct"),
        "center_fg_pct": d.get("centerFgPct"),
        "updated": d.get("updated"),
    }


def main():
    conn = sqlite3.connect(DB_PATH)
    init_tables(conn)

    # --- Store meta ---
    conn.execute("INSERT OR REPLACE INTO cbb_meta VALUES ('ucla_team_id', ?)", (str(UCLA_TEAM_ID),))
    for season, comp_id in COMPETITIONS.items():
        conn.execute("INSERT OR REPLACE INTO cbb_meta VALUES (?, ?)",
                     (f"comp_id_{season}", str(comp_id)))
    conn.commit()

    for season, comp_id in sorted(COMPETITIONS.items(), reverse=True):
        print(f"\n{'='*60}")
        print(f"Season {season}  (competitionId={comp_id})")
        print(f"{'='*60}")

        # --- 1. Player Agg Box (all scopes) ---
        print("  1/4  Player agg-box...")
        agg_rows = paginate(f"{BASE_URL}/stats/player/agg-box",
                            {"teamIds": UCLA_TEAM_ID, "competitionIds": comp_id})
        parsed = [parse_agg(d, comp_id, season) for d in agg_rows]
        if parsed:
            upsert_player_agg(conn, parsed)
        scopes_found = sorted(set(d["scope"] for d in parsed))
        print(f"     {len(parsed)} rows | scopes: {scopes_found}")
        time.sleep(1)

        # --- 2. Player Agg PBP (season scope only for speed) ---
        print("  2/4  Player agg-pbp...")
        pbp_rows = paginate(f"{BASE_URL}/stats/player/agg-pbp",
                            {"teamIds": UCLA_TEAM_ID, "competitionIds": comp_id})
        parsed_pbp = [parse_agg_pbp(d, comp_id, season) for d in pbp_rows]
        if parsed_pbp:
            upsert_player_agg_pbp(conn, parsed_pbp)
        print(f"     {len(parsed_pbp)} rows")
        time.sleep(1)

        # --- 3. Player Game Logs ---
        print("  3/4  Player game logs...")
        game_rows = paginate(f"{BASE_URL}/stats/player/game-box",
                             {"teamIds": UCLA_TEAM_ID, "competitionIds": comp_id})
        log_inserts = []
        for d in game_rows:
            log_inserts.append({
                "id": d.get("_id", ""),
                "competition_id": comp_id, "season": season,
                "team_id": d.get("teamId"),
                "player_id": d.get("playerId"),
                "player_name": d.get("fullName"),
                "game_id": d.get("gameId"),
                "game_date": d.get("gameDate"),
                "opponent": d.get("teamMarketAgst"),
                "is_home": int(bool(d.get("isHome"))),
                "is_win": int(bool(d.get("isWin"))),
                "gp": d.get("gp"), "gs": d.get("gs"),
                "mins": d.get("mins"),
                "pts": d.get("ptsScored"), "reb": d.get("reb"),
                "orb": d.get("orb"), "drb": d.get("drb"),
                "ast": d.get("ast"), "stl": d.get("stl"),
                "blk": d.get("blk"), "tov": d.get("tov"),
                "pf": d.get("pf"), "pfd": d.get("pfd"),
                "fgm": d.get("fgm"), "fga": d.get("fga"),
                "fgm2": d.get("fgm2"), "fga2": d.get("fga2"),
                "fgm3": d.get("fgm3"), "fga3": d.get("fga3"),
                "ftm": d.get("ftm"), "fta": d.get("fta"),
                "plus_minus": d.get("plusMinus"),
                "fg_pct": d.get("fgPct"), "fg3_pct": d.get("fg3Pct"),
                "ts_pct": d.get("tsPct"), "efg_pct": d.get("efgPct"),
                "usage_pct": d.get("usagePct"),
                "updated": d.get("updated"),
            })
        if log_inserts:
            conn.executemany("""INSERT OR REPLACE INTO cbb_player_game_logs VALUES (
                :id,:competition_id,:season,:team_id,:player_id,:player_name,
                :game_id,:game_date,:opponent,:is_home,:is_win,
                :gp,:gs,:mins,:pts,:reb,:orb,:drb,:ast,:stl,:blk,:tov,:pf,:pfd,
                :fgm,:fga,:fgm2,:fga2,:fgm3,:fga3,:ftm,:fta,:plus_minus,
                :fg_pct,:fg3_pct,:ts_pct,:efg_pct,:usage_pct,:updated)""", log_inserts)
            conn.commit()
        print(f"     {len(log_inserts)} rows")
        time.sleep(1)

        # --- 4. Lineups ---
        print("  4/4  Lineups...")
        lineup_rows = paginate(f"{BASE_URL}/stats/lineups/agg",
                               {"teamIds": UCLA_TEAM_ID, "competitionIds": comp_id})
        lineup_inserts = []
        for d in lineup_rows:
            mins = d.get("minsPbp") or d.get("mins")
            poss = d.get("poss")
            pts  = d.get("ptsScored")
            pts_agst = d.get("ptsAgst")
            ortg = (pts / poss * 100) if (poss and pts is not None) else None
            drtg = (pts_agst / poss * 100) if (poss and pts_agst is not None) else None
            net  = (ortg - drtg) if (ortg is not None and drtg is not None) else None
            lineup_inserts.append({
                "id": d.get("_id", ""),
                "competition_id": comp_id, "season": season,
                "team_id": d.get("teamId"),
                "scope": d.get("scope"),
                "p_name1": d.get("pName1"), "p_name2": d.get("pName2"),
                "p_name3": d.get("pName3"), "p_name4": d.get("pName4"),
                "p_name5": d.get("pName5"),
                "p_id1": d.get("pId1"), "p_id2": d.get("pId2"),
                "p_id3": d.get("pId3"), "p_id4": d.get("pId4"),
                "p_id5": d.get("pId5"),
                "gp": d.get("gpPbp"),
                "mins": mins, "poss": poss,
                "pts": pts, "pts_agst": pts_agst,
                "plus_minus": d.get("plusMinus"),
                "ortg": ortg, "drtg": drtg, "net_rtg": net,
                "fgm": d.get("fgm"), "fga": d.get("fga"),
                "updated": d.get("updated"),
            })
        if lineup_inserts:
            conn.executemany("""INSERT OR REPLACE INTO cbb_lineups VALUES (
                :id,:competition_id,:season,:team_id,:scope,
                :p_name1,:p_name2,:p_name3,:p_name4,:p_name5,
                :p_id1,:p_id2,:p_id3,:p_id4,:p_id5,
                :gp,:mins,:poss,:pts,:pts_agst,:plus_minus,
                :ortg,:drtg,:net_rtg,:fgm,:fga,:updated)""", lineup_inserts)
            conn.commit()
        print(f"     {len(lineup_inserts)} rows")

        # --- On/Off ---
        print("  +    On/Off...")
        onoff_rows = paginate(f"{BASE_URL}/stats/on-off/agg",
                              {"teamIds": UCLA_TEAM_ID, "competitionIds": comp_id})
        onoff_inserts = []
        for d in onoff_rows:
            mins  = d.get("minsPbp")
            poss  = d.get("poss")
            pts   = d.get("ptsScored")
            pts_a = d.get("ptsAgst")
            ortg  = (pts / poss * 100) if poss and pts is not None else None
            drtg  = (pts_a / poss * 100) if poss and pts_a is not None else None
            net   = (ortg - drtg) if ortg is not None and drtg is not None else None
            onoff_inserts.append({
                "id": d.get("_id", ""),
                "competition_id": comp_id, "season": season,
                "team_id": d.get("teamId"),
                "player_id": d.get("playerId"),
                "player_name": d.get("fullName"),
                "scope": d.get("scope"),
                "on_off_diff": d.get("onOffDiff"),
                "mins": mins, "poss": poss,
                "ortg": ortg, "drtg": drtg, "net_rtg": net,
                "updated": d.get("updated"),
            })
        if onoff_inserts:
            conn.executemany("""INSERT OR REPLACE INTO cbb_on_off VALUES (
                :id,:competition_id,:season,:team_id,:player_id,:player_name,
                :scope,:on_off_diff,:mins,:poss,:ortg,:drtg,:net_rtg,:updated)""", onoff_inserts)
            conn.commit()
        print(f"     {len(onoff_inserts)} rows")

        time.sleep(2)

    # Summary
    print("\n=== Done ===")
    for tbl in ["cbb_player_agg", "cbb_player_agg_pbp", "cbb_player_game_logs",
                "cbb_lineups", "cbb_on_off"]:
        n = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        print(f"  {tbl}: {n} rows")
    conn.close()


if __name__ == "__main__":
    main()
