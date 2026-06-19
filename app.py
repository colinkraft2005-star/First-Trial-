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
from datetime import datetime

# ==========================================
# LOCAL MAC SSL OVERRIDE
# ==========================================
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass

st.set_page_config(layout="wide")


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
                       notes        TEXT
                   )
                   ''')
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS roster
                   (
                       id          INTEGER PRIMARY KEY AUTOINCREMENT,
                       player_name TEXT,
                       position    TEXT,
                       depth       INTEGER,
                       descriptor  TEXT,
                       bt_name     TEXT
                   )
                   ''')
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


init_db()
seed_roster_if_empty()


# ==========================================
# HEADSHOT FETCHER
# ==========================================
def fetch_sr_headshot_silent(player_name, team_name=""):
    cleaned_name = player_name.replace(".", "").replace(",", "")
    safe_name = urllib.parse.quote(cleaned_name)
    search_url = f"https://www.sports-reference.com/cbb/search/search.fcgi?search={safe_name}"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    img_pattern = r'src="(https://www.sports-reference.com/req/[^"]+/cbb/images/players/[^"]+\.jpg)"'
    suffix_words = ['jr', 'ii', 'iii', 'iv', 'v']
    name_parts = cleaned_name.lower().split()
    detected_suffix = name_parts[-1] if (name_parts and name_parts[-1] in suffix_words) else None

    def parse_html_for_image(html, current_url):
        match = re.search(img_pattern, html)
        if match:
            return match.group(1)
        if "/cbb/search/search.fcgi" in current_url:
            results = re.findall(r'href="(/cbb/players/([^"]+)\.html)"[^>]*>(.*?)<\/a>(.*?)(?:<\/div>|<li>|<tr|<td>)',
                                 html, re.IGNORECASE | re.DOTALL)
            if results:
                for link, slug, display_name, context in results:
                    if team_name and (team_name.lower() in context.lower() or team_name.lower() in display_name.lower()):
                        if detected_suffix and f"-{detected_suffix}" not in slug.lower():
                            continue
                        return fetch_profile_image(link)
                suffix_matches = []
                for link, slug, display_name, context in results:
                    if detected_suffix and f"-{detected_suffix}" in slug.lower():
                        suffix_matches.append(link)
                if suffix_matches:
                    return fetch_profile_image(suffix_matches[-1])
                try:
                    def extract_num(r):
                        num_match = re.search(r'-(\d+)$', r[1])
                        return int(num_match.group(1)) if num_match else 0
                    best_link = max(results, key=extract_num)[0]
                    return fetch_profile_image(best_link)
                except Exception:
                    return fetch_profile_image(results[0][0])
        return ""

    def fetch_profile_image(player_page_path):
        try:
            player_url = f"https://www.sports-reference.com{player_page_path}"
            player_response = requests.get(player_url, headers=headers, timeout=5, verify=False)
            img_match = re.search(img_pattern, player_response.text)
            return img_match.group(1) if img_match else ""
        except Exception:
            return ""

    try:
        response = requests.get(search_url, headers=headers, timeout=5, verify=False)
        img_url = parse_html_for_image(response.text, response.url)
        if img_url:
            return img_url
        if detected_suffix:
            base_name = " ".join(name_parts[:-1])
            fallback_url = f"https://www.sports-reference.com/cbb/search/search.fcgi?search={urllib.parse.quote(base_name)}"
            fallback_resp = requests.get(fallback_url, headers=headers, timeout=5, verify=False)
            img_url = parse_html_for_image(fallback_resp.text, fallback_resp.url)
            if img_url:
                return img_url
    except Exception:
        pass
    return ""


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
                        "MIN_PCT":     safe_float(row, 4),
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
                        "TWO_P":       safe_float(row, 18) * 100,
                        "THREE_P":     safe_float(row, 21) * 100,
                        "THREE_P_100": safe_float(row, 65) if len(row) > 65 else 0.0,
                        "CLASS":       str(row[25]) if len(row) > 25 else "",
                        "HEIGHT":      str(row[26]) if len(row) > 26 else "",
                        "PRPG":        safe_float(row, 28),
                        "BPM":         safe_float(row, 50),
                        "OBPM":        safe_float(row, 51),
                        "DBPM":        safe_float(row, 52),
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
def load_top100_data_v6():
    time.sleep(3)
    return fetch_barttorvik_safe(top_filter=100)

@st.cache_data(ttl=3600)
def load_top50_data_v6():
    time.sleep(6)
    return fetch_barttorvik_safe(top_filter=50)


# ==========================================
# SEQUENTIAL DATA LOAD WITH PROGRESS BAR
# ==========================================
load_bar = st.progress(0, text="Loading full database...")
df_all = load_all_data_v6()
load_bar.progress(33, text="Loading Top 100 competition data...")
df_top100 = load_top100_data_v6()
load_bar.progress(66, text="Loading Top 50 competition data...")
df_top50 = load_top50_data_v6()
load_bar.progress(100, text="Database ready.")
time.sleep(0.4)
load_bar.empty()

failed = []
if df_all is None:    failed.append("All Games")
if df_top100 is None: failed.append("Top 100")
if df_top50 is None:  failed.append("Top 50")

if failed:
    st.error(
        f"BartTorvik returned empty data for: **{', '.join(failed)}**\n\n"
        "This usually means your IP is temporarily rate-limited by the server. "
        "Try one of the following:\n"
        "- Wait 10-15 minutes and rerun\n"
        "- Switch to your phone hotspot and rerun\n"
        "- Connect to a VPN and rerun"
    )
    st.stop()

all_player_names = sorted(list(df_all["PLAYER"].unique()))

if "active_player" not in st.session_state:
    st.session_state.active_player = all_player_names[0]

# ==========================================
# HEADER
# ==========================================
head_col1, head_col2 = st.columns([1, 12])
with head_col1:
    st.image("https://cdn.freebiesupply.com/logos/large/2x/ucla-bruins-1-logo-png-transparent.png", width=55)
with head_col2:
    st.markdown("<h2 style='margin: 0; padding-top: 8px; color: #FFFFFF;'>UCLA Transfer Portal Database</h2>",
                unsafe_allow_html=True)
st.write("***")

tab_depth, tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Depth Chart",
    "Individual Player Profile",
    "Portal Discovery Engine",
    "Front Office Target Board",
    "Big Board Print View",
    "Player Card / Ranking System"
])

# ==========================================
# TAB: DEPTH CHART (FRONT PAGE)
# ==========================================
with tab_depth:
    st.subheader("26-27 UCLA Bruins — Depth Chart")

    # ---- ROSTER EDITOR ----
    with st.expander("Edit Roster", expanded=False):
        st.caption(
            "Add, remove, or reorder players. **Position** must be one of PG / CG / SF / PF / C. "
            "**Depth** sets the stacking order (1 = starter). For stats to auto-link, **BT Name** must "
            "match the player's exact BartTorvik spelling — leave it blank for freshmen / walk-ons."
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

    # ---- VISUAL DEPTH CHART ----
    conn = sqlite3.connect('scouting_hub.db')
    chart_df = pd.read_sql_query(
        "SELECT player_name, position, depth, descriptor, bt_name FROM roster ORDER BY depth",
        conn
    )
    conn.close()

    POSITIONS = [("PG", "Point Guard"), ("CG", "Combo Guard"), ("SF", "Small Forward"),
                 ("PF", "Power Forward"), ("C", "Center")]

    pos_cols = st.columns(5)

    for i, (pos_code, pos_label) in enumerate(POSITIONS):
        with pos_cols[i]:
            # Column header
            st.markdown(f"""
                <div style='background-color:#2774AE; color:white; font-weight:bold;
                            text-align:center; padding:8px; border-radius:6px; margin-bottom:12px;
                            font-size:13px; letter-spacing:0.5px;'>
                    {pos_code}<br><span style='font-size:9px; font-weight:400; opacity:0.85;'>{pos_label}</span>
                </div>
            """, unsafe_allow_html=True)

            group = chart_df[chart_df["position"] == pos_code].sort_values("depth")

            if group.empty:
                st.caption("No players assigned")
                continue

            for _, pl in group.iterrows():
                pname = pl["player_name"]
                descriptor = pl["descriptor"] if pl["descriptor"] else ""
                bt_name = pl["bt_name"] if pl["bt_name"] else ""
                is_open = pname.strip().upper() == "OPEN"
                is_starter = int(pl["depth"]) == 1

                # OPEN slot rendering
                if is_open:
                    st.markdown(f"""
                        <div style='border:2px dashed #FFD100; border-radius:8px; padding:14px 10px;
                                    margin-bottom:10px; background-color:rgba(255,209,0,0.06); text-align:center;'>
                            <div style='font-size:13px; font-weight:bold; color:#FFD100;'>OPEN</div>
                            <div style='font-size:10px; color:#FFD100; opacity:0.85; margin-top:2px;'>{descriptor}</div>
                        </div>
                    """, unsafe_allow_html=True)
                    continue

                # Pull live stats if this player links to BartTorvik
                stat_line = ""
                if bt_name:
                    match = df_all[df_all["PLAYER"] == bt_name]
                    if not match.empty:
                        s = match.iloc[0]
                        stat_line = f"BPM {s['BPM']:.1f} · USG {s['USG']:.0f}% · eFG {s['EFG']:.0f}%"

                border = "#FFD100" if is_starter else "#CBD5E1"
                starter_badge = ("<span style='font-size:8px; background:#FFD100; color:#0F172A; "
                                 "font-weight:bold; padding:1px 5px; border-radius:3px;'>STARTER</span>") if is_starter else ""

                stat_html = (f"<div style='font-size:9.5px; color:#2774AE; font-weight:600; margin-top:3px;'>{stat_line}</div>"
                             if stat_line else "")
                desc_html = (f"<div style='font-size:9.5px; color:#64748B; margin-top:2px;'>{descriptor}</div>"
                             if descriptor else "")

                st.markdown(f"""
                    <div style='border:1px solid {border}; border-left:4px solid {border}; border-radius:6px;
                                padding:9px 10px; margin-bottom:10px; background-color:#FFFFFF;
                                box-shadow:1px 1px 3px rgba(0,0,0,0.05);'>
                        <div style='display:flex; justify-content:space-between; align-items:center;'>
                            <span style='font-size:12.5px; font-weight:bold; color:#0F172A;'>{pname}</span>
                            {starter_badge}
                        </div>
                        {stat_html}
                        {desc_html}
                    </div>
                """, unsafe_allow_html=True)

                # Jump-to-profile button (only for stat-linked players)
                if bt_name and not df_all[df_all["PLAYER"] == bt_name].empty:
                    if st.button(f"View {pname}", key=f"depth_view_{pos_code}_{pname}",
                                 use_container_width=True):
                        st.session_state.active_player = bt_name
                        st.rerun()

    st.write("")
    st.caption("⭐ Yellow = projected starter · Dashed yellow = open slot · "
               "Returning/transfer players show live BartTorvik metrics; incoming freshmen show roster notes.")


# ==========================================
# TAB 1: INDIVIDUAL PLAYER SCOUTING
# ==========================================
with tab1:
    st.subheader("Personnel Target Evaluation")

    current_idx = all_player_names.index(st.session_state.active_player)
    selected_dropdown = st.selectbox("Search or select player profile:", all_player_names, index=current_idx)

    if selected_dropdown != st.session_state.active_player:
        st.session_state.active_player = selected_dropdown
        st.rerun()

    current_player = st.session_state.active_player
    p_data = df_all[df_all["PLAYER"] == current_player].iloc[0]

    conn = sqlite3.connect('scouting_hub.db')
    cursor = conn.cursor()
    cursor.execute(
        "SELECT scout_name, priority_tier, position, role, rumored_nil, personal_val, agent, agency, photo_url, eval_date, notes FROM player_notes WHERE player_name = ?",
        (current_player,))
    db_row = cursor.fetchone()

    saved_scout  = db_row[0] if db_row else "Trey Doty"
    saved_tier   = db_row[1] if db_row else "Watchlist"
    saved_pos    = db_row[2] if db_row else "PG"
    saved_role   = db_row[3] if db_row else ""
    saved_nil    = db_row[4] if db_row else ""
    saved_val    = db_row[5] if db_row else ""
    saved_agent  = db_row[6] if db_row else ""
    saved_agency = db_row[7] if db_row else ""
    saved_photo  = db_row[8] if db_row else ""
    saved_date   = db_row[9] if db_row else "No previous evaluations logged"
    saved_notes  = db_row[10] if db_row else ""

    if not saved_photo:
        saved_photo = fetch_sr_headshot_silent(current_player, p_data["TEAM"])
        if db_row and saved_photo:
            cursor.execute("UPDATE player_notes SET photo_url = ? WHERE player_name = ?", (saved_photo, current_player))
            conn.commit()

    conn.close()

    col_img, col_info = st.columns([1, 5])
    with col_img:
        if saved_photo:
            st.image(saved_photo, width=130)
        else:
            st.info("No headshot logged")

    with col_info:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Program",    p_data["TEAM"])
        c2.metric("Conference", p_data["CONF"])
        c3.metric("Class",      p_data["CLASS"])
        c4.metric("Height",     p_data["HEIGHT"])
        st.caption(f"📅 **Last Evaluation Update Stamped:** {saved_date}")

    st.write("**Player Metrics Line**")
    stat_col1, stat_col2, stat_col3, _ = st.columns([1, 1, 1, 5])

    if "profile_split" not in st.session_state:
        st.session_state.profile_split = "All Games"

    with stat_col1:
        if st.button("All Games", key="prof_all",
                     type="primary" if st.session_state.profile_split == "All Games" else "secondary"):
            st.session_state.profile_split = "All Games"
            st.rerun()
    with stat_col2:
        if st.button("Top 100", key="prof_100",
                     type="primary" if st.session_state.profile_split == "Top 100" else "secondary"):
            st.session_state.profile_split = "Top 100"
            st.rerun()
    with stat_col3:
        if st.button("Top 50", key="prof_50",
                     type="primary" if st.session_state.profile_split == "Top 50" else "secondary"):
            st.session_state.profile_split = "Top 50"
            st.rerun()

    split_map = {"All Games": df_all, "Top 100": df_top100, "Top 50": df_top50}
    active_df = split_map[st.session_state.profile_split]

    player_stats = active_df[active_df["PLAYER"] == current_player]
    if player_stats.empty:
        st.info(f"No {st.session_state.profile_split} data available for {current_player}.")
    else:
        st.dataframe(player_stats.drop(columns=["CLASS", "HEIGHT"]), hide_index=True)

    st.write("***")

    col_scout, col_tier = st.columns(2)
    with col_scout:
        scout_input = st.text_input("Assigned Staff Member / Scout Name:", value=saved_scout)
    with col_tier:
        tier_input = st.selectbox("Recruitment Board Category Hierarchy:", ["High Priority", "Watchlist", "Pass"],
                                  index=["High Priority", "Watchlist", "Pass"].index(saved_tier))

    st.write("**Roster Alignment & Structural Role Classification**")
    col_pos, col_role = st.columns(2)
    with col_pos:
        position_list = ["PG", "CG", "W", "F", "C"]
        pos_idx = position_list.index(saved_pos) if saved_pos in position_list else 0
        position_input = st.selectbox("Primary Position Grouping:", position_list, index=pos_idx)
    with col_role:
        role_input = st.text_input("Projected Tactical Role Allocation (e.g., Starting Point Guard):", value=saved_role)

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

    if st.button("Commit Intel to Board"):
        execution_date = datetime.now().strftime("%Y-%m-%d")
        final_photo = photo_input if photo_input else fetch_sr_headshot_silent(current_player, p_data["TEAM"])
        conn = sqlite3.connect('scouting_hub.db')
        cursor = conn.cursor()
        cursor.execute('''
                       INSERT INTO player_notes (player_name, team_name, scout_name, priority_tier, position, role,
                                                 rumored_nil, personal_val, agent, agency, photo_url, eval_date, notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(player_name) DO
                       UPDATE SET
                           scout_name=excluded.scout_name, priority_tier=excluded.priority_tier,
                           position=excluded.position, role=excluded.role, rumored_nil=excluded.rumored_nil,
                           personal_val=excluded.personal_val, agent=excluded.agent, agency=excluded.agency,
                           photo_url=excluded.photo_url, eval_date=excluded.eval_date, notes=excluded.notes
                       ''',
                       (current_player, p_data["TEAM"], scout_input, tier_input, position_input, role_input,
                        nil_input, val_input, agent_input, agency_input, final_photo, execution_date, notes_input))
        conn.commit()
        conn.close()
        st.success(f"Intel dynamically updated for {current_player}.")
        st.rerun()


# ==========================================
# TAB 2: PORTAL DISCOVERY ENGINE
# ==========================================
with tab2:
    st.subheader("Database Sifting & Portal Filtering")

    st.write("**Competition Filter**")
    tier_col1, tier_col2, tier_col3, _ = st.columns([1, 1, 1, 5])

    if "discovery_split" not in st.session_state:
        st.session_state.discovery_split = "All Games"

    with tier_col1:
        if st.button("All Games", key="disc_all",
                     type="primary" if st.session_state.discovery_split == "All Games" else "secondary"):
            st.session_state.discovery_split = "All Games"
            st.rerun()
    with tier_col2:
        if st.button("Top 100", key="disc_100",
                     type="primary" if st.session_state.discovery_split == "Top 100" else "secondary"):
            st.session_state.discovery_split = "Top 100"
            st.rerun()
    with tier_col3:
        if st.button("Top 50", key="disc_50",
                     type="primary" if st.session_state.discovery_split == "Top 50" else "secondary"):
            st.session_state.discovery_split = "Top 50"
            st.rerun()

    disc_split_map = {"All Games": df_all, "Top 100": df_top100, "Top 50": df_top50}
    disc_base_df = disc_split_map[st.session_state.discovery_split]

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

    filtered_df = filtered_df[
        (filtered_df["MIN_PCT"].between(min_pct[0], min_pct[1])) &
        (filtered_df["BPM"].between(bpm[0], bpm[1])) &
        (filtered_df["OBPM"].between(obpm[0], obpm[1])) &
        (filtered_df["DBPM"].between(dbpm[0], dbpm[1])) &
        (filtered_df["ORTG"].between(ortg[0], ortg[1])) &
        (filtered_df["USG"].between(usg[0], usg[1])) &
        (filtered_df["EFG"].between(efg[0], efg[1])) &
        (filtered_df["TS"].between(ts[0], ts[1])) &
        (filtered_df["OR"].between(orb[0], orb[1])) &
        (filtered_df["DR"].between(drb[0], drb[1])) &
        (filtered_df["AST"].between(ast[0], ast[1])) &
        (filtered_df["TO"].between(tov[0], tov[1])) &
        (filtered_df["BLK"].between(blk[0], blk[1])) &
        (filtered_df["STL"].between(stl[0], stl[1])) &
        (filtered_df["FTR"].between(ftr[0], ftr[1])) &
        (filtered_df["TWO_P"].between(two_p[0], two_p[1])) &
        (filtered_df["THREE_P"].between(three_p[0], three_p[1])) &
        (filtered_df["THREE_P_100"].between(three_p_100[0], three_p_100[1]))
    ]

    filtered_df = filtered_df.sort_values(by="PRPG", ascending=False)

    ordered_cols = ["PLAYER", "TEAM", "CONF", "CLASS", "HEIGHT", "PRPG", "BPM", "MIN_PCT", "USG", "EFG"]
    remaining_cols = [c for c in filtered_df.columns if c not in ordered_cols]
    filtered_df = filtered_df[ordered_cols + remaining_cols]

    st.write(f"**Filter Results ({st.session_state.discovery_split}):** Found {len(filtered_df)} profiles matching criteria.")

    event_discovery = st.dataframe(
        filtered_df,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        height=650
    )

    if event_discovery.selection.rows:
        clicked_idx = event_discovery.selection.rows[0]
        clicked_player = filtered_df.iloc[clicked_idx]["PLAYER"]
        if st.session_state.active_player != clicked_player:
            st.session_state.active_player = clicked_player
            st.rerun()


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
               scout_name AS SCOUT, notes AS NOTES, priority_tier AS TIER
        FROM player_notes
    ''', conn)
    conn.close()

    if db_df.empty:
        st.info("No targets currently logged onto the system database.")
    else:
        for tier in ["High Priority", "Watchlist", "Pass"]:
            st.markdown(f"### {tier}")
            tier_filtered = db_df[db_df["TIER"] == tier]
            if tier_filtered.empty:
                st.write("*No targets assigned to this category tier.*")
            else:
                event_board = st.dataframe(tier_filtered.drop(columns=["TIER"]), hide_index=True,
                                           on_select="rerun", selection_mode="single-row", key=f"board_{tier}")
                if event_board.selection.rows:
                    clicked_idx = event_board.selection.rows[0]
                    clicked_player = tier_filtered.iloc[clicked_idx]["PLAYER"]
                    if st.session_state.active_player != clicked_player:
                        st.session_state.active_player = clicked_player
                        st.rerun()


# ==========================================
# TAB 4: PRINTS / VISUAL BOARD VIEW
# ==========================================
with tab4:
    st.subheader("Staff Roster Print Layout")
    st.write("Clean card formatting optimized for direct browser printing (File -> Print).")

    filter_tier = st.selectbox("Select Target Priority Tier to Display:", ["High Priority", "Watchlist", "All Records"])

    conn = sqlite3.connect('scouting_hub.db')
    if filter_tier == "All Records":
        board_data = pd.read_sql_query("SELECT * FROM player_notes", conn)
    else:
        board_data = pd.read_sql_query("SELECT * FROM player_notes WHERE priority_tier = ?", conn,
                                       params=(filter_tier,))

    for idx, row in board_data.iterrows():
        if not row["photo_url"]:
            fetched_img = fetch_sr_headshot_silent(row["player_name"], row["team_name"])
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
                st.markdown(f"""
                    <div style='background-color:#1E3A8A; color:white; font-weight:bold;
                                text-align:center; padding:6px; border-radius:4px; margin-bottom:12px;'>
                        {pos_group}
                    </div>
                """, unsafe_allow_html=True)

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

                        st.markdown(f"""
                            <div style='border:1px solid #CBD5E1; border-radius:6px; padding:10px;
                                        margin-bottom:12px; background-color:#FFFFFF; box-shadow: 1px 1px 3px rgba(0,0,0,0.05);'>
                                <table style='width:100%; border-collapse:collapse; margin-bottom:4px;'>
                                    <tr>
                                        <td style='width:95px; vertical-align:top;'>
                                            <div style='width:90px; height:90px; display:flex; align-items:center; justify-content:center; border-radius:4px; border:1px solid #E2E8F0; background-color:#F8FAFC; overflow:hidden;'>
                                                <img src='{photo}' onerror="this.onerror=null; this.src='https://upload.wikimedia.org/wikipedia/commons/8/89/Portrait_Placeholder.png';" style='max-width:100%; max-height:100%; object-fit:contain;'/>
                                            </div>
                                        </td>
                                        <td style='padding-left:12px; vertical-align:top; line-height:1.3;'>
                                            <div style='font-size:14px; font-weight:bold; color:#0F172A;'>{p_name}</div>
                                            <div style='font-size:11px; color:#475569; font-weight:600;'>{player['team_name']}</div>
                                            <div style='font-size:11px; color:#64748B;'>{meta_line}</div>
                                        </td>
                                    </tr>
                                </table>
                                <div style='border-top:1px dashed #E2E8F0; padding-top:4px; font-size:10px; font-weight:600; color:#1E40AF;'>
                                    🎯 {role_label}
                                </div>
                                <div style='font-size:9.5px; font-weight:bold; color:#475569; margin-top:2px;'>
                                    📊 {stat_line}
                                </div>
                            </div>
                        """, unsafe_allow_html=True)

# ==========================================
# TAB 5: PLAYER CARD / RANKING SYSTEM
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


def get_bar_color(score):
    if score >= 80:
        return "#2774AE"
    if score >= 65:
        return "#F0B429"
    return "#DC2626"


def render_card_html(player, show_writeup=False):
    sh_c = get_bar_color(player["shooting"])
    df_c = get_bar_color(player["defense"])
    pl_c = get_bar_color(player["playmaking"])
    rb_c = get_bar_color(player["rebounding"])

    tags_html = "".join([
        "<span style=\"background:#e8f1f9;color:#2774AE;font-family:'DM Mono',monospace;font-size:8px;font-weight:600;padding:3px 9px;border-radius:3px;border:1px solid #b8d3ec;margin:2px;display:inline-block;text-transform:uppercase;letter-spacing:.04em;\">" + t + "</span>"
        for t in player.get("tags", [])
    ])

    writeup_html = ""
    if show_writeup and player.get("writeup"):
        writeup_html = "<div style=\"padding:10px 14px;border-top:1px solid #e5e7eb;font-size:12px;line-height:1.65;color:#374151;\">" + player["writeup"] + "</div>"

    ts  = str(player.get("ts", ""))
    usg = str(player.get("usg", ""))
    p3  = str(player.get("p3", "0"))

    stats_html = ""
    if ts:
        stats_html = (
            "<div style=\"display:flex;border-bottom:1px solid #e5e7eb;background:#fff;\">"
            "<div style=\"flex:1;padding:9px 0;text-align:center;border-right:1px solid #e5e7eb;\">"
            "<span style=\"font-size:13px;font-weight:500;color:#111827;display:block;\">" + ts + "%</span>"
            "<span style=\"font-size:7px;color:#6b7280;text-transform:uppercase;display:block;margin-top:2px;\">TS%</span>"
            "</div>"
            "<div style=\"flex:1;padding:9px 0;text-align:center;border-right:1px solid #e5e7eb;\">"
            "<span style=\"font-size:13px;font-weight:500;color:#111827;display:block;\">" + usg + "%</span>"
            "<span style=\"font-size:7px;color:#6b7280;text-transform:uppercase;display:block;margin-top:2px;\">USG%</span>"
            "</div>"
            "<div style=\"flex:1;padding:9px 0;text-align:center;\">"
            "<span style=\"font-size:13px;font-weight:500;color:#111827;display:block;\">" + p3 + "%</span>"
            "<span style=\"font-size:7px;color:#6b7280;text-transform:uppercase;display:block;margin-top:2px;\">3P%</span>"
            "</div>"
            "</div>"
        )

    def bar(label, val, color):
        return (
            "<div style=\"margin-bottom:6px;\">"
            "<div style=\"display:flex;justify-content:space-between;font-size:9px;text-transform:uppercase;color:#374151;margin-bottom:2px;\">"
            "<span>" + label + "</span>"
            "<span style=\"color:" + color + ";font-weight:600;\">" + str(val) + "</span>"
            "</div>"
            "<div style=\"background:#e5e7eb;border-radius:2px;height:5px;overflow:hidden;\">"
            "<div style=\"height:100%;width:" + str(val) + "%;background:" + color + ";border-radius:2px;\"></div>"
            "</div>"
            "</div>"
        )

    name       = player.get("name", "")
    height     = player.get("height", "")
    pos        = player.get("pos", "")
    cls        = player.get("cls", "")
    school     = player.get("school", "")
    tier       = player.get("tier", "")
    projection = player.get("projection", "")
    role       = player.get("role", "")

    return (
        "<div style=\"background:#ffffff;border:1px solid #dde2ee;border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08);margin-bottom:14px;\">"
        "<div style=\"padding:14px 16px 10px;border-bottom:1px solid #e5e7eb;\">"
        "<div style=\"display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:4px;\">"
        "<div>"
        "<div style=\"font-size:20px;font-weight:800;color:#111827;letter-spacing:.02em;\">" + name + "</div>"
        "<div style=\"font-size:10px;color:#6b7280;margin-top:3px;\">" + height + " &middot; " + pos + " &middot; " + cls + " &middot; " + school + "</div>"
        "</div>"
        "<span style=\"font-size:9px;padding:3px 9px;border-radius:3px;background:#fff7e0;border:1px solid #f9d98a;color:#92600a;font-weight:600;\">" + tier + "</span>"
        "</div>"
        "</div>"
        + stats_html +
        "<div style=\"padding:12px 16px 6px;\">"
        + bar("Shooting", player["shooting"], sh_c)
        + bar("Defense", player["defense"], df_c)
        + bar("Playmaking", player["playmaking"], pl_c)
        + bar("Rebounding", player["rebounding"], rb_c) +
        "</div>"
        "<div style=\"padding:0 16px 10px;\">" + tags_html + "</div>"
        "<div style=\"padding:10px 16px;border-top:1px solid #e5e7eb;background:#f9fafb;\">"
        "<div style=\"font-size:12px;font-weight:700;color:#111827;\">" + projection + "</div>"
        "<div style=\"font-size:9px;color:#2774AE;margin-top:2px;\">" + role + "</div>"
        "</div>"
        + writeup_html +
        "</div>"
    )


def score_comp(player, hist_row):
    """
    Torvik-style fingerprint scoring using df_all rows.
    df_all has clean HEIGHT strings already parsed by Trey's app.
    Hard filters: height +/-3in, then full stat fingerprint with dominant skill boost.
    """
    try:
        p_h = parse_height_inches(player.get("height", "6'6\""))
        h_h = parse_height_inches(str(hist_row.get("HEIGHT", "6'6\"")))
        if abs(p_h - h_h) > 3:
            return 0.0

        def nd(a, b, r):
            try:
                return max(0.0, 1.0 - abs(float(a) - float(b)) / r)
            except:
                return 0.0

        # Core stat comparisons against df_all columns
        p_ts  = float(player.get("ts", 58) or 58)
        p_usg = float(player.get("usg", 18) or 18)
        p_p3  = float(player.get("p3", 0) or 0)

        h_ts  = float(hist_row.get("TS", 55))
        h_ts  = h_ts * 100 if h_ts <= 1.0 else h_ts
        h_usg = float(hist_row.get("USG", 18))
        h_bpm = float(hist_row.get("BPM", 0))
        h_dbpm = float(hist_row.get("DBPM", 0))
        h_efg  = float(hist_row.get("EFG", 50))
        h_ast  = float(hist_row.get("AST", 15))
        h_orb  = float(hist_row.get("OR", 5))
        h_drb  = float(hist_row.get("DR", 10))
        h_blk  = float(hist_row.get("BLK", 3))
        h_stl  = float(hist_row.get("STL", 2))
        h_p3   = float(hist_row.get("THREE_P", 30)) if "THREE_P" in hist_row.index else p_p3

        # Skill ratings from card
        shooting   = float(player.get("shooting", 60))
        defense    = float(player.get("defense", 60))
        playmaking = float(player.get("playmaking", 60))
        rebounding = float(player.get("rebounding", 60))

        # Map card ratings to stat dimensions
        p_ts_mapped  = 45 + (shooting / 100) * 25
        p_efg_mapped = 40 + (shooting / 100) * 20
        p_dbpm_mapped = (defense - 50) / 10
        p_ast_mapped  = playmaking / 3.5
        p_orb_mapped  = (rebounding / 100) * 12
        p_drb_mapped  = (rebounding / 100) * 20
        p_blk_mapped  = (defense / 100) * 8
        p_stl_mapped  = (defense / 100) * 3.5

        # Fingerprint scores
        scores = {
            "ts":   nd(p_ts_mapped, h_ts, 8),
            "efg":  nd(p_efg_mapped, h_efg, 8),
            "usg":  nd(p_usg, h_usg, 6),
            "p3":   nd(p_p3, h_p3, 12),
            "ast":  nd(p_ast_mapped, h_ast, 7),
            "orb":  nd(p_orb_mapped, h_orb, 4),
            "drb":  nd(p_drb_mapped, h_drb, 6),
            "blk":  nd(p_blk_mapped, h_blk, 3),
            "stl":  nd(p_stl_mapped, h_stl, 1.5),
            "dbpm": nd(p_dbpm_mapped, h_dbpm, 2),
            "bpm":  nd(h_bpm, 0, 5),
            "ht":   nd(p_h, h_h, 2),
        }

        # Base weights
        w = {"ts":0.10,"efg":0.08,"usg":0.10,"p3":0.06,"ast":0.09,"orb":0.07,"drb":0.07,"blk":0.07,"stl":0.06,"dbpm":0.08,"bpm":0.06,"ht":0.16}

        # Dominant skill boost: double the relevant weights
        skills = {"shooting": shooting, "defense": defense, "playmaking": playmaking, "rebounding": rebounding}
        dominant = max(skills, key=skills.get)
        dom_val  = skills[dominant]

        if dom_val >= 75:
            if dominant == "shooting":
                w["ts"] = 0.18; w["efg"] = 0.14; w["p3"] = 0.12
                w["ast"] = 0.05; w["orb"] = 0.03; w["drb"] = 0.04; w["blk"] = 0.03; w["stl"] = 0.03
                w["usg"] = 0.08; w["dbpm"] = 0.04; w["bpm"] = 0.04; w["ht"] = 0.22
            elif dominant == "rebounding":
                w["orb"] = 0.14; w["drb"] = 0.14; w["blk"] = 0.08
                w["ts"] = 0.06; w["efg"] = 0.04; w["p3"] = 0.02
                w["ast"] = 0.04; w["usg"] = 0.07; w["dbpm"] = 0.06; w["stl"] = 0.04; w["bpm"] = 0.05; w["ht"] = 0.26
            elif dominant == "defense":
                w["dbpm"] = 0.16; w["blk"] = 0.13; w["stl"] = 0.11
                w["ts"] = 0.05; w["efg"] = 0.04; w["p3"] = 0.02
                w["ast"] = 0.05; w["orb"] = 0.05; w["drb"] = 0.06; w["usg"] = 0.06; w["bpm"] = 0.05; w["ht"] = 0.22
            elif dominant == "playmaking":
                w["ast"] = 0.20; w["usg"] = 0.12; w["bpm"] = 0.08
                w["ts"] = 0.07; w["efg"] = 0.05; w["p3"] = 0.04
                w["orb"] = 0.03; w["drb"] = 0.04; w["blk"] = 0.03; w["stl"] = 0.06; w["dbpm"] = 0.06; w["ht"] = 0.22

        return sum(scores[k] * w[k] for k in scores)
    except:
        return 0.0


with tab5:
    st.subheader("Player Card / Ranking System")
    st.caption("HoopsHub Scout grade cards with live historical comp matching from BartTorvik.")

    tier_options = sorted(list(set(p["tier"] for p in PORTAL_PLAYERS)))
    tier_filter = st.multiselect("Filter by Tier:", tier_options, default=tier_options)
    if not tier_filter:
        tier_filter = tier_options

    show_writeups = st.checkbox("Show scouting writeups", value=False)

    filtered_players = [p for p in PORTAL_PLAYERS if p["tier"] in tier_filter]
    seen = set()
    unique_players = []
    for p in filtered_players:
        if p["name"] not in seen:
            seen.add(p["name"])
            unique_players.append(p)

    st.write(f"**{len(unique_players)} players** in view")
    st.write("---")

    cols = st.columns(2)
    for i, player in enumerate(unique_players):
        with cols[i % 2]:
            st.markdown(render_card_html(player, show_writeup=show_writeups), unsafe_allow_html=True)

            if player.get("ts"):
                with st.expander(f"Find Historical Comps: {player['name']}"):
                    if df_all is None or df_all.empty:
                        st.warning("BartTorvik data unavailable.")
                    else:
                        scored_comps = []
                        for _, hist_row in df_all.iterrows():
                            s = score_comp(player, hist_row)
                            if s > 0.0:
                                scored_comps.append((s, hist_row))

                        scored_comps.sort(key=lambda x: x[0], reverse=True)
                        top_matches = scored_comps[:6]

                        st.write(f"**Top comps from {len(df_all):,} current-season players ({len(scored_comps)} passed height filter):**")

                        if not top_matches:
                            st.info("No close height matches found in the current season database.")
                        else:
                            for match_score, match_data in top_matches:
                                pct = round(match_score * 100, 1)
                                c_name = str(match_data.get("PLAYER", ""))
                                c_team = str(match_data.get("TEAM", ""))
                                c_conf = str(match_data.get("CONF", ""))
                                c_ht   = str(match_data.get("HEIGHT", ""))
                                c_bpm  = float(match_data.get("BPM", 0))
                                c_usg  = float(match_data.get("USG", 0))
                                c_efg  = float(match_data.get("EFG", 0))
                                c_ts   = float(match_data.get("TS", 0))
                                c_ts   = c_ts * 100 if c_ts <= 1.0 else c_ts
                                c_ast  = float(match_data.get("AST", 0))

                                html = (
                                    "<div style=\"background:#ffffff;border:1px solid #dde2ee;border-left:4px solid #2774AE;border-radius:8px;padding:12px 14px;margin-bottom:8px;\">"
                                    "<div style=\"display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px;\">"
                                    "<div>"
                                    "<div style=\"font-size:14px;font-weight:700;color:#111827;\">" + c_name + "</div>"
                                    "<div style=\"font-size:9px;color:#6b7280;margin-top:2px;\">" + c_ht + " &middot; " + c_team + " (" + c_conf + ")</div>"
                                    "</div>"
                                    "<span style=\"font-size:8px;font-weight:600;padding:4px 8px;border-radius:3px;background:#e8f1f9;color:#2774AE;border:1px solid #b8d3ec;\">" + str(pct) + "% match</span>"
                                    "</div>"
                                    "<div style=\"display:flex;background:#f9fafb;border:1px solid #e5e7eb;border-radius:5px;overflow:hidden;margin-bottom:6px;\">"
                                    "<div style=\"flex:1;padding:6px 0;text-align:center;border-right:1px solid #e5e7eb;\">"
                                    "<div style=\"font-size:11px;font-weight:500;color:#111827;\">" + f"{c_ts:.1f}%" + "</div>"
                                    "<div style=\"font-size:7px;color:#6b7280;text-transform:uppercase;\">TS%</div>"
                                    "</div>"
                                    "<div style=\"flex:1;padding:6px 0;text-align:center;border-right:1px solid #e5e7eb;\">"
                                    "<div style=\"font-size:11px;font-weight:500;color:#111827;\">" + f"{c_usg:.1f}%" + "</div>"
                                    "<div style=\"font-size:7px;color:#6b7280;text-transform:uppercase;\">USG%</div>"
                                    "</div>"
                                    "<div style=\"flex:1;padding:6px 0;text-align:center;border-right:1px solid #e5e7eb;\">"
                                    "<div style=\"font-size:11px;font-weight:500;color:#111827;\">" + f"{c_efg:.1f}%" + "</div>"
                                    "<div style=\"font-size:7px;color:#6b7280;text-transform:uppercase;\">eFG%</div>"
                                    "</div>"
                                    "<div style=\"flex:1;padding:6px 0;text-align:center;border-right:1px solid #e5e7eb;\">"
                                    "<div style=\"font-size:11px;font-weight:500;color:#111827;\">" + f"{c_bpm:.1f}" + "</div>"
                                    "<div style=\"font-size:7px;color:#6b7280;text-transform:uppercase;\">BPM</div>"
                                    "</div>"
                                    "<div style=\"flex:1;padding:6px 0;text-align:center;\">"
                                    "<div style=\"font-size:11px;font-weight:500;color:#111827;\">" + f"{c_ast:.1f}%" + "</div>"
                                    "<div style=\"font-size:7px;color:#6b7280;text-transform:uppercase;\">AST%</div>"
                                    "</div>"
                                    "</div>"
                                    "<div style=\"height:3px;background:#e5e7eb;border-radius:2px;\">"
                                    "<div style=\"height:100%;width:" + str(pct) + "%;background:#2774AE;border-radius:2px;\"></div>"
                                    "</div>"
                                    "</div>"
                                )
                                st.markdown(html, unsafe_allow_html=True)