import streamlit as st
import pandas as pd
import requests
import sqlite3
import urllib.parse
import re
import math
import json
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
# GLOBAL CSS - remove Streamlit whitespace + style header
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

/* UCLA header bar - negative margins bleed past block-container padding */
#ucla-header {
    background: #2D68C4;
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

/* Hide tab bar on Home tab; show on all others */
[data-baseweb="tab-list"]:has([data-baseweb="tab"]:first-child[aria-selected="true"]) {
    display: none !important;
}

/* Tab bar - negative margins bleed past block-container padding */
[data-testid="stTabs"] { margin-top: 0 !important; }
[data-baseweb="tab-list"] {
    background: #2D68C4 !important;
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
    color: #F2A900 !important;
    border-bottom: 3px solid #F2A900 !important;
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
    # Migrate player_notes tables created before value_tag / board_rank existed
    notes_cols = {row[1] for row in cursor.execute("PRAGMA table_info(player_notes)").fetchall()}
    if "value_tag" not in notes_cols:
        cursor.execute("ALTER TABLE player_notes ADD COLUMN value_tag TEXT")
    if "board_rank" not in notes_cols:
        # Manual up/down order within a position row on the Front Office Target Board.
        cursor.execute("ALTER TABLE player_notes ADD COLUMN board_rank INTEGER")
    if "onepager_notes" not in notes_cols:
        # Free-form "Staff Notes" block on the Print Out one-pager - separate from the
        # Scouting Report `notes` field so editing one doesn't silently overwrite the other.
        cursor.execute("ALTER TABLE player_notes ADD COLUMN onepager_notes TEXT")
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS player_evaluations
                   (
                       id          INTEGER PRIMARY KEY AUTOINCREMENT,
                       player_name TEXT,
                       scout_name  TEXT,
                       eval_date   TEXT,
                       note        TEXT,
                       created_at  TEXT
                   )
                   ''')
    # One-time migration: player_notes.notes used to be a single mutable field that the
    # next coach to save simply overwrote, losing whoever's opinion was there before.
    # Carry each player's existing note over as their first logged evaluation so nothing
    # is lost, then leave it alone - player_evaluations is append-only from here on.
    if cursor.execute("SELECT COUNT(*) FROM player_evaluations").fetchone()[0] == 0:
        for player_name, scout_name, eval_date, note in cursor.execute(
            "SELECT player_name, scout_name, eval_date, notes FROM player_notes "
            "WHERE notes IS NOT NULL AND TRIM(notes) != ''"
        ).fetchall():
            cursor.execute(
                "INSERT INTO player_evaluations (player_name, scout_name, eval_date, note, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (player_name, scout_name, eval_date, note, eval_date),
            )
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
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS recruit_surveys
                   (
                       player_name         TEXT PRIMARY KEY,
                       school              TEXT,
                       position            TEXT,
                       recruit_bucket      TEXT,
                       primary_evaluator   TEXT,
                       eval_date           TEXT,
                       self_awareness      INTEGER,
                       circle_alignment    INTEGER,
                       positional_fit      INTEGER,
                       financial_alignment INTEGER,
                       coachability        INTEGER,
                       physical_toughness  INTEGER,
                       representation      INTEGER,
                       info_influence      INTEGER,
                       market_value        TEXT,
                       best_info_source    TEXT,
                       best_influencer     TEXT,
                       relationship_owner  TEXT,
                       hidden_connections  TEXT,
                       recruiting_priority TEXT
                   )
                   ''')
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS international_players
                   (
                       id          INTEGER PRIMARY KEY AUTOINCREMENT,
                       player_name TEXT,
                       country     TEXT,
                       height      TEXT,
                       position    TEXT,
                       age         REAL,
                       class_yr    TEXT,
                       temperature TEXT,
                       agent       TEXT,
                       notes       TEXT,
                       profile_url TEXT,
                       source      TEXT,
                       scout_name  TEXT,
                       eval_date   TEXT
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
            ("OPEN",             "SF", 1, "Starting SF - TBD",             ""),
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
    """Fill in real height / class-year for the 26-27 roster. Idempotent - safe to run every startup."""
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


def seed_international_players_if_empty():
    """Pre-load the front office's FIBA U18 EuroBasket (A Division) report on first run only."""
    conn = sqlite3.connect('scouting_hub.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM international_players")
    count = cursor.fetchone()[0]
    if count == 0:
        src = "FIBA U18 EuroBasket - A Division"
        # (player_name, country, height, position, age, class_yr, temperature, agent, notes)
        seed = [
            ("Stefan Joksimovic", "Slovenia", "6'8\"", "1", 17.7, "2027", "Doubtful", "Sasa Zagorac",
             "Absolute no brainer, but likely will be a top 10 pick. Positional size and has every finish "
             "around the rim. NBA level pickups. Likely not going to college."),
            ("Ignas Stombergas", "Lithuania", "7'0\"", "5", 18.4, "2027", "See More", "Tadas Bulotas",
             "Slow start, wound up shining over the last two days. Best big man prospect in Europe for this "
             "age group. Legit size, light on his feet, soft hands, soft touch, can post or play as a roll "
             "man. Lacked great spacing around him, so hard to judge his offense in a real way, but clear "
             "case of - he is going to be really good, it's just a matter of if it's as a sophomore or as a "
             "senior. High ceiling. Entree cost trending towards being not worth it at this stage given what "
             "likely is his early return. Not a great scheme fit for a foot speed in space standpoint, as "
             "well as physicality currently. Best big prospect in Europe."),
            ("Maks Ciperle", "Slovenia", "6'7\"", "3", 17.8, "2027", "See More", "Sead Galijasevic",
             "Wing connector who has a HIGH feel. Legit 6'7 and growing with a size 16.5 shoe. NBA build. "
             "Concerns: Lateral quickness. Is he not a great mover because he has grown so fast? Shooting: "
             "Numbers are bad. Can his shot develop is the biggest swing on this eval. Decently high floor "
             "with how much he impacts the game, but still tough to gauge the true ceiling because of the "
             "shaky movement stuff and the shooting."),
            ("Fin Borczanowski", "Germany", "6'8\"", "3/4", 17.7, "2027", "Yes", "Milan Nikolic",
             "Ancillary modern wing who seems to be on a sharp upward trajectory. Baby face, closing in on "
             "6-10. Extremely quick off the floor (volleyball genes), tries to rebound everything and fit "
             "seamlessly next to really good players. Need to focus in on his shot more, as it'll be a big "
             "swing factor in regards to his ceiling. Monster ceiling as a pure defensive player both as an "
             "off ball guy as well as a point of attack guy given his size, foot speed and instincts. "
             "Physical maturation will be fascinating to track. Potential to really pop by the time CBB "
             "comes around."),
            ("Fabian Kayser", "Germany", "6'8\"", "2", 17.3, "2027", "Doubtful", "Tadas Bulotas",
             "Slow start, but strung together a productive few days. Second highest profile prospect on "
             "tap. Offensively, best fit as a secondary creator; been consistently underwhelmed with him as "
             "a primary. Tries to hit home runs every chance he can get. Better off attacking advantages to "
             "score or make a read. Mediocre defender; high hips, good instincts. Loves to grab and go. "
             "Doesn't talk much. Will play CBB. Would be shocked if entrance fee to CBB winds up worthwhile."),
            ("Anton Kemmer", "Germany", "6'8\"", "3/4", 17.7, "2027", "Yes", "Jan Jagla",
             "Strong few days; very interesting eval. Gets a whole lot done on both ends without, "
             "essentially, anything being drawn up for him. Athletic, high feel wing with size. Awesome off "
             "the ball as a cutter, relocation shooter and connector. Knows how to play with great players. "
             "Can go quiet for stretches of games at times for too long. High major player in time, whether "
             "it's year one or year two/three."),
            ("Chiek Diallo", "Spain", "6'9\"", "5", 18.0, "2026", "Yes", "Daniel Barbieri",
             "Impressive few days. LOUD first few days. Aggressive roller, elite athlete, good length, "
             "moves well in space, plays above the rim and blocks shots. Fast off the floor. Bad screener "
             "currently; doesn't hit guys, tries to pressure the rim and doesn't really know how to screen "
             "at all right now. Late to the game, clearly raw, but high level tools for a rim-running big. "
             "If he unlocks the screening, high major starting big potential."),
            ("Leonard Kroger", "Germany", "6'9\"", "5", 17.7, "2027", "Yes", "David Marek/Bennet Ahnfeldt",
             "German Jovic. Not quite the same level athlete in terms of power and pop, but a prototype "
             "undersized big as a guy who can defend in space, rebound at a high clip, emergency switch and "
             "combat height with physicality and energy. Elite motor. Constantly diving on the floor. "
             "Talks, brings juice, elevates a teams' floor. Scheme fit and personality fit."),
            ("Keny Vado", "France", "6'9\"", "5", 18.3, "2026", "See More", "David Condouant",
             "Undersized height wise but big body - some Luke Wilson? Very long arms, good feet. Does a "
             "great job putting his body on people. Showed great ball screen defense. Does not have a good "
             "feel on team defense, when to go over and block a shot vs when to grab rebound. Hopefully can "
             "grow a bit more. Monitor to see his development, as he has only been playing basketball for a "
             "few years."),
            ("Darius Karutasu", "Turkey", "6'9\"", "4", 17.3, "2027", "See More", "Tadas Bulotas",
             "One of the more naturally talented prospects on tap for his age. Big frame, super comfortable "
             "with the ball in his hands, and shoots it on the move. Looking to put the ball in the hoop "
             "every possession. Unique skillset for size. Needs strength and a better base in a real way "
             "over the next year to two in development. Takes some bad shots. Inconsistent defensively, but "
             "has flashes. Has some tunnel vision. High upside, low floor in terms of winning impact."),
            ("Humberto Ruiz", "Spain", "6'5\"", "3", 17.4, "2027", "Yes", "Igor Crespo",
             "First watch, new name. Major spark plug for Spain as their youngest guy. Came in with his "
             "hair on fire every chance he got. Talks, super competitive. Elite speed and impressive ball "
             "skills. Streaky shooter. Will mature physically; very light right now. But love the outlines "
             "of a two-way wing with an awesome motor, scoring chops and winning stuff. Fun."),
            ("Hugo Yimga", "France", "6'9\"", "4/3", 18.1, "2026", "Doubtful", "Bouna Ndiaye",
             "Highest profile prospect for the French team. Has hit a snag in his development in the last "
             "year as his counterparts catch up to him physically. Grown man frame, long, strong and "
             "relatively fluid. Pure scorer; doesn't impact the game in many other areas outside of the "
             "glass. Brutal shot diet and a slow processor. Looks the part of a strong defender, but real "
             "struggle to sink his hips and stay in front of guys. Doesn't plan to go to CBB, and don't "
             "think he'd be a strong investment to impact winning here early."),
            ("Kenan Youdom", "Germany", "6'7\"", "3/4", 16.7, "2028", "Yes", "Milan Nikolic",
             "Best pure defensive prospect here. Legit 6-7 athlete, who was the youngest dude on the floor "
             "most of the time, who could genuinely disrupt 1-5. Could take guys out of the game guarding "
             "individually. Elite work rate. Sneaky good handler. Shot isn't there right now. Swing skill. "
             "Development can go a lot of directions over next two years, but monster defensive ceiling."),
            ("Igor Stjepanovic", "Slovenia", "6'2\"", "1", 18.1, "2027", "See More", "Sasa Zagorac",
             "Undersized 1 who is great with the ball. Controlled the game all weekend. P/R reads were high "
             "level. Finished at the rim well vs bigs. Active hands on defense but not a switchable guard "
             "onto 4's. Luke Ertel lite -- slick lefty who can get where he wants and has scoring instincts."),
            ("Felix Kiehlneker", "Germany", "7'0\"", "5", 18.4, "2027", "See More", "Michael Canty",
             "Slow start, had some real worries, but grew on me steadily. Real size as a true five. Still "
             "clearly developing physically. Has natural ball skills, good feet for his size and knows what "
             "to do in his role as a roll guy, screener, rebounder. Just struggles playing in traffic and "
             "stringing together longer stretches of high level play. Classic case with a young big to me - "
             "want him when he's 20 / 21 years old - if the price is too high coming over, it's a hard "
             "sell. Needs time. High floor, high ceiling."),
            ("Lucas Sanchez", "Spain", "6'5\"", "1", 18.3, "2026", "See More", "Igor Crespo",
             "Spain's rock. Good frame and positional size. Game manager; smart, tough, gets guys in the "
             "right spots, physical with the ball in his hands. Little reminiscent to JJ Mandaquit, but "
             "bigger. Struggles dealing with great athletes. Lacks great lateral foot speed. Intangibles "
             "sell, plus a pretty high floor. Can he turn into a great shooter? Not sure the athleticism has "
             "much room to develop."),
            ("Luka Zivojinovic", "Serbia", "6'11\"", "5", 16.8, "2027", "See More", "Misko Radovic",
             "Huge. Good screener. Showed flashes of passing out of the post, making decisions on the "
             "perimeter. Good activity getting out on ball screens and talking defensively. Played some bad "
             "big men and was not GREAT, but solid. Question his general knack for the ball."),
            ("Lucai Anderson", "Germany", "6'4\"", "2", 17.4, "2027", "Doubtful", "Aaron Mintz",
             "Struggled early, picked it up late. Bad shot quality. Does not make his teammates better, bad "
             "passes were a norm. Not a great shooter by any means. Active defender. Moves great. Not for us."),
            ("Tauris Aliukonis", "Lithuania", "6'9\"", "5", 18.2, "2027", "See More", "Tadas Bulotas",
             "Seemed like a potential sleeper. Tricky fit for him with this group because he's asked to play "
             "alongside Stombergas. True size, good hands, knows how to play. Inconsistent against "
             "physicality. Relatively light in his lower body; gets displaced too often. Someone to watch as "
             "he continues to mature physically. Seems like a guy a high major will take as a development guy."),
            ("Andrej Bjelic", "Serbia", "6'5\"", "2", 18.4, "2026", "Doubtful", "Andrej Ilic",
             "Bad physical profile, but if he gets to his spots he is good. Skilled. Hard time getting past "
             "his body, but someone to lightly monitor."),
            ("Cheickh Niang", "Italy", "6'6\"", "3", 17.9, "2027", "Doubtful", "Andrea Grossi",
             "Best pure athlete in the tournament. Does not have understanding of the game, does not have a "
             "position. Shoots on the move 3's but did not see the ability to shoot 30%+. Ability to be a "
             "point of attack defender. Will monitor, but not for us."),
            ("Diego Niebla", "Spain", "6'9\"", "4", 18.5, "2027", "See More", "Juanjo Bernabe",
             "Positionally sized 4 who can move well laterally. Question what position he is, his IQ & "
             "shooting ability. Tangibles are there, so someone to monitor. Has shown ability to play on the "
             "perimeter and handle. Production is there, just a matter of seeing more."),
            ("Kerem Corumlular", "Turkey", "6'5\"", "2", 18.3, "2027", "See More", "",
             "Great body and positional size. Connective 2 man who has a HIGH IQ. Good looking shot but the "
             "numbers are not good. Has shown high defensive production. Need to see more of his quickness."),
            ("Sten-Markus Adamson", "Estonia", "6'6\"", "3", 18.0, "2027", "See More", "Deimantas Baziukas",
             "Got hurt after a few days, but really interesting profile as a big, smooth wing who can "
             "process and score. Strong positional rebounder. Does a great job playing with his head up and "
             "making decisions. Super smooth with the ball in his hands; great footwork on drives, advanced "
             "gathers, great tempo with the ball to draw fouls and create angles. Tunnel vision and not sure "
             "he can guard anyone? Want to see more."),
            ("Antonio Barra", "Italy", "6'8\"", "3", 18.1, "2027", "See More", "",
             "Flashes. No substance yet. Looks the part of a shot-making wing. Moves well, will fill out "
             "well, light on his feet, smooth stroke. Doesn't do very much at all besides shoot and move off "
             "the ball. Name to monitor, little to show to this point."),
            ("Thomas Acunzo", "Italy", "6'10\"", "5", 18.3, "2027", "Doubtful", "",
             "Does not fit the athletic profile of HM basketball. Has pick & pop skill. Understands the "
             "game, when to seal, when to slip. Unfortunately the athletic ceiling is low, and he doesn't "
             "have enough skill to make up for it."),
            ("Vuk Danilovic", "Serbia", "6'5\"", "2", 18.6, "2026", "Doubtful", "Drazen Zlovaric",
             "Movement shooter with strength and size. Did not show ability to do much else. Son of one of "
             "the best players ever in Europe Sasha Danilovic. Probably not for us because of lateral "
             "quickness & one dimensional."),
            ("Louka Letailleur", "France", "6'7\"", "3", 18.2, "2026", "Doubtful", "Ayite Ajavon",
             "Lefty wing who has great athletic ability. Went up to block shots on bigs. Fearless. Shot "
             "doesn't look bad but not there yet. Will monitor just because of his athletic ability and "
             "toughness. Largely the catalyst for France, on a bad French roster."),
        ]
        cursor.executemany(
            "INSERT INTO international_players "
            "(player_name, country, height, position, age, class_yr, temperature, agent, notes, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [row + (src,) for row in seed]
        )
        conn.commit()
    conn.close()


init_db()
seed_roster_if_empty()
backfill_roster_bio()
seed_international_players_if_empty()


# ==========================================
# HEADSHOT FETCHER
# ==========================================
@st.cache_data(ttl=86400)
def fetch_espn_headshot(player_name: str, team_espn_id: str = "", team_name_hint: str = "") -> str:
    """Fetch player headshot from ESPN search API by player name. ESPN's search mixes in
    same-named athletes from every sport/league (an NBA "Brandon Williams" can outrank the
    UCLA one), so results are restricted to men's college basketball only, and further
    narrowed to team_name_hint's subtitle text (e.g. "UCLA") when multiple candidates remain."""
    if not player_name:
        return ""
    try:
        url = f"https://site.api.espn.com/apis/search/v2?query={urllib.parse.quote(player_name)}&limit=10&type=player"
        r = requests.get(url, timeout=5)
        if r.status_code != 200:
            return ""
        name_lower = player_name.lower().strip()
        hint_lower = team_name_hint.lower().strip()
        candidates = []
        for result in r.json().get("results", []):
            for c in result.get("contents", []):
                if c.get("displayName", "").lower().strip() != name_lower:
                    continue
                if c.get("defaultLeagueSlug") != "mens-college-basketball":
                    continue
                candidates.append(c)
        if hint_lower:
            hinted = [c for c in candidates if hint_lower in c.get("subtitle", "").lower()]
            if hinted:
                candidates = hinted
        for c in candidates:
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
    # Legacy stub - ESPN roster lookup is now used instead
    return ""


@st.cache_data(ttl=3600)
def get_player_headshot(player_name: str, team_espn_id: str = "", team_name_hint: str = "") -> str:
    """DB-cached headshot lookup: player_notes.photo_url first, then ESPN as a fallback
    - and persists the ESPN result so future loads don't re-hit the network for it."""
    try:
        conn = sqlite3.connect("scouting_hub.db")
        row = conn.execute(
            "SELECT photo_url FROM player_notes WHERE player_name = ?", (player_name,)
        ).fetchone()
        if row and row[0]:
            conn.close()
            return row[0]
        photo = fetch_espn_headshot(player_name, team_espn_id, team_name_hint)
        if photo:
            conn.execute(
                "INSERT INTO player_notes (player_name, photo_url) VALUES (?, ?) "
                "ON CONFLICT(player_name) DO UPDATE SET photo_url=excluded.photo_url",
                (player_name, photo),
            )
            conn.commit()
        conn.close()
        return photo
    except Exception:
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
                            "jersey": a.get("jersey", ""),
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
                                    "jersey": ath.get("jersey", ""),
                                }
    except Exception:
        pass

    return {}


@st.cache_data(ttl=86400)
def fetch_ucla_jersey_numbers():
    """UCLA's own roster (ESPN team id 26), keyed by lowercased display name.

    Transfers' BartTorvik rows carry their previous school's team_espn_id (their most
    recent season was played there, not at UCLA yet) - looking up jersey number via that
    ID silently finds nothing, since they've already left that roster. UCLA's roster
    always has the right team regardless of where a player's stat line came from.
    """
    try:
        r = requests.get(
            "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/26/roster",
            timeout=8,
        )
        if r.status_code == 200:
            return {
                a.get("displayName", "").lower().strip(): a.get("jersey", "")
                for a in r.json().get("athletes", [])
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
    """Reads the season player-stat table from the local db (built by
    build_torvik_season.py) instead of calling BartTorvik live on every app startup.
    Every coach running their own local copy is a separate process with its own cache -
    several people opening the app around the same time used to mean several
    near-simultaneous live hits to Torvik, which is what triggered rate limiting. Falls
    back to a live fetch only if the table hasn't been built yet, and writes that result
    into the db so the next startup doesn't need to hit Torvik again either.
    """
    try:
        conn = sqlite3.connect("scouting_hub.db")
        df = pd.read_sql_query("SELECT * FROM torvik_player_season", conn)
        conn.close()
        if not df.empty:
            return df
    except Exception:
        pass

    df = fetch_barttorvik_safe(top_filter=None)
    if df is not None and not df.empty:
        try:
            conn = sqlite3.connect("scouting_hub.db")
            df.to_sql("torvik_player_season", conn, index=False, if_exists="replace")
            conn.close()
        except Exception:
            pass
    return df


@st.cache_data(ttl=3600)
def build_team_conf_map(df_all: pd.DataFrame) -> dict:
    """{team_espn_id: CONF} - lets game logs (which only have opponent_espn_id) be matched
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
    exclude_conf_ids=True - used for conference vs. non-conference splits).
    Joins player_game_logs with game_team_stats for rate stats (USG, AST, ORB, DRB, BLK, STL).
    Same formula for All Games / Top 100 / Top 50 - fully comparable currency.
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
        # in) - fall back to NULL on fresh installs instead of crashing on "no such column".
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
                SUM(p.fg3_made)                                                  AS THREE_M_TOTAL,
                ROUND(SUM(p.pf)*40.0 / NULLIF(SUM(p.min_played), 0), 1)          AS PF_PER40,
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
                    NULLIF(
                        (SUM(CASE WHEN t.fga IS NOT NULL THEN p.min_played END)*1.0 /
                         NULLIF(SUM(CASE WHEN t.fga IS NOT NULL THEN tm.team_mp END)/5.0, 0))
                        * (SUM(t.fga)+0.44*SUM(t.fta)+SUM(t.tov)),
                    0), 1) AS USG,
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


@st.cache_data(ttl=3600)
def load_recent_form(player_name: str, n_games: int = 8):
    """Last N games (by date) vs. the player's full-season averages - the real signal
    behind a 'late riser' / 'better lately' tag: is he playing at a notably higher level
    right now than his season line alone would suggest, mid-season. Returns None if there
    isn't enough game-log history to make the comparison meaningful."""
    try:
        conn = sqlite3.connect("scouting_hub.db")
        df = pd.read_sql_query(
            "SELECT game_date, min_played, pts, fg_made, fg_att, fg3_made, ft_made, ft_att "
            "FROM player_game_logs WHERE player_name = ? AND min_played >= 1 "
            "ORDER BY game_date ASC",
            conn, params=(player_name,),
        )
        conn.close()
        if len(df) < n_games + 4:
            return None

        def _ts(rows):
            fga = rows["fg_att"].sum()
            fta = rows["ft_att"].sum()
            pts = rows["pts"].sum()
            denom = 2 * (fga + 0.44 * fta)
            return (pts / denom * 100) if denom > 0 else None

        recent = df.tail(n_games)
        season_ppg = df["pts"].mean()
        recent_ppg = recent["pts"].mean()
        season_ts = _ts(df)
        recent_ts = _ts(recent)
        return {
            "season_ppg": season_ppg, "recent_ppg": recent_ppg,
            "season_ts": season_ts, "recent_ts": recent_ts,
            "n_games": n_games,
        }
    except Exception:
        return None


def normalize_name(name: str) -> str:
    """Loose match key for a player name across data sources that don't spell it the same
    way - CJ vs C.J., Jr/III present or not, accented characters. Strips punctuation, drops
    Jr/Sr/II/III/IV suffixes, strips accents, lowercases. Used only as a fallback when an
    exact-string match against another table comes up empty - never replaces the exact
    match, since it's a lossier key (e.g. it would conflate two genuinely different players
    who happen to share a normalized name)."""
    if not name:
        return ""
    import unicodedata
    n = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii")
    n = n.lower()
    n = re.sub(r"[.\-']", "", n)
    n = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def find_name_match(target_name: str, candidate_names) -> str:
    """Exact match against candidate_names if present, else the unique normalized match
    (CJ/C.J., Jr/no-Jr, accents). Returns None if neither resolves to exactly one name -
    a normalized collision between two different real players is left unresolved rather
    than guessed at."""
    if target_name in candidate_names:
        return target_name
    target_key = normalize_name(target_name)
    if not target_key:
        return None
    matches = [c for c in candidate_names if normalize_name(c) == target_key]
    return matches[0] if len(matches) == 1 else None


def get_pct(val, sorted_vals: list):
    if not sorted_vals or val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    rank = bisect.bisect_left(sorted_vals, val)
    return 100.0 * rank / len(sorted_vals)


def pct_color(pct):
    """Blue (0th pct) → Grey (50th pct) → Gold (100th pct). Returns (bg_hex, text_hex)."""
    if pct is None:
        return "#EAECF0", "#1A1A1A"
    t = max(0.0, min(100.0, pct)) / 100.0
    # Midpoint: grey #A8A8A8
    MR, MG, MB = 168, 168, 168
    if t <= 0.5:
        # UCLA Blue (#2D68C4) → Grey (#A8A8A8)
        s = t / 0.5
        r = int(45  + (MR - 45)  * s)
        g = int(104 + (MG - 104) * s)
        b = int(196 + (MB - 196) * s)
    else:
        # Grey (#A8A8A8) → UCLA Gold (#F2A900)
        s = (t - 0.5) / 0.5
        r = int(MR + (242 - MR) * s)
        g = int(MG + (169 - MG) * s)
        b = int(MB + (0   - MB) * s)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    text = "#FFFFFF" if lum < 120 else "#000000"
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


@st.cache_data(ttl=3600)
def load_cbb_player_agg() -> pd.DataFrame:
    """Load cbb_player_agg for season=2026 from scouting_hub.db."""
    try:
        conn = sqlite3.connect("scouting_hub.db")
        df = pd.read_sql_query(
            "SELECT * FROM cbb_player_agg WHERE season = 2026",
            conn,
        )
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_cbb_pbp_zones() -> pd.DataFrame:
    """Load cbb_player_agg_pbp for season=2026 from scouting_hub.db."""
    try:
        conn = sqlite3.connect("scouting_hub.db")
        df = pd.read_sql_query(
            "SELECT * FROM cbb_player_agg_pbp WHERE season = 2026",
            conn,
        )
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def build_pbp_benchmarks() -> dict:
    """
    Build sorted value lists for shot-zone stats from all season-scope PBP rows
    with meaningful shot volume. Used for percentile coloring on the player card.
    """
    try:
        conn = sqlite3.connect("scouting_hub.db")
        df = pd.read_sql_query(
            "SELECT * FROM cbb_player_agg_pbp WHERE scope='season' AND fga > 20",
            conn,
        )
        conn.close()
    except Exception:
        return {}

    out = {}
    for col in ["atr2_fg_pct", "atr2_fga_freq", "mid2_fg_pct", "mid2_fga_freq",
                "fg3_pct", "fga3_rate", "ft_pct"]:
        vals = df[col].dropna().astype(float).tolist()
        if vals:
            out[col] = sorted(vals)
    return out


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
    if zone == "Rim":
        lo, hi = 50.0, 78.0
    elif zone == "Paint":
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
        "Paint":            (25.0, 12.5),
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

    def _zone_patch(zone, bg, alpha=0.9):
        # A visible seam between zones (instead of linewidth=0) is what actually reads as
        # "these are distinct regions" rather than one gradient blob - same idea as the
        # court lines, just thinner so it doesn't compete with them.
        kw = dict(facecolor=bg, edgecolor="#0b1c30", linewidth=1.6, alpha=alpha, zorder=2)

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
        ax.text(cx, cy + 1.3, f"{stats['pct']:.0f}%",
                ha="center", va="center", color=fg,
                fontsize=11, fontweight="bold", zorder=6)
        ax.text(cx, cy - 1.3, f"{stats['made']}/{stats['total']}",
                ha="center", va="center", color=fg,
                fontsize=8.5, zorder=6)

    # Redraw court lines on top of zone fills
    _draw_half_court(ax)

    # Extra room below the court for the FG line + color key
    ax.set_xlim(0, 50)
    ax.set_ylim(-7.5, 47)
    ax.set_aspect("equal")
    ax.axis("off")

    total = len(shots_df)
    makes = int(shots_df["made"].sum())
    pct   = makes / total * 100 if total else 0
    ax.text(25, -1.6, f"{makes}/{total} FG  ({pct:.1f}%)",
            ha="center", va="top", color="#eeeeee", fontsize=9, fontweight="bold", zorder=7)

    # Color key: every zone's % is colored relative to a realistic FG% range for that zone
    # type, not to a fixed 0-100 scale - blue means cold for that zone, gold means hot.
    key_y = -5.4
    for kx, color, label in [
        (6.0,  "#1e50c8", "Below Average"),
        (23.0, "#f2f2f2", "Average"),
        (36.0, "#ffa000", "Above Average"),
    ]:
        ax.add_patch(Rectangle((kx - 0.8, key_y - 0.6), 1.6, 1.2, facecolor=color,
                                edgecolor="#666666", linewidth=0.6, zorder=7))
        ax.text(kx + 1.4, key_y, label, ha="left", va="center", color="#f5f5f5",
                fontsize=8.5, fontweight="bold", zorder=7)

    if title:
        ax.set_title(title, color="white", fontsize=12, fontweight="bold", pad=6)

    plt.tight_layout(pad=0.3)
    return fig


def draw_shot_zone_profile(zone_agg: dict, title: str = "") -> plt.Figure:
    """Same wedge-court style as draw_shot_chart, fed by aggregate PBP zone rates
    (rim/paint/mid/corner3/atb3 - what's actually available for most players) instead of
    shot-by-shot data. Restored after the rectangular SVG version replaced it - the
    request was explicitly to go back to this look, just with cleaner, bigger, bolder
    text than draw_shot_chart's original sizing.

    zone_agg: {"rim"|"paint"|"mid"|"corner3"|"atb3": {"pct": 0-100, "made": int, "total": int}}
    Mid/Corner3/ATB3 each cover multiple wedges on the real court but only one aggregate
    number exists for them, so the same value is drawn into every wedge it spans -
    matches how the SVG version handled the same data-granularity limit.
    """
    fig, ax = plt.subplots(figsize=(5.8, 6.2))
    fig.patch.set_facecolor("#111827")
    _draw_half_court(ax)

    BX, BY = _BX, _BY
    R3 = _R3
    CXL, CXR, CY = _CXL, _CXR, _CY

    zone_centers = {
        "Paint":            (25.0, 12.5),
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
    # Which aggregate stat feeds each wedge.
    _feed = {
        "Paint": "paint",
        "Mid Left": "mid", "Mid Center-Left": "mid", "Mid Center-Right": "mid", "Mid Right": "mid",
        "Corner Left": "corner3", "Corner Right": "corner3",
        "Wing Left": "atb3", "Top": "atb3", "Wing Right": "atb3",
    }

    _ang_r = math.atan2(CY - BY, CXR - BX)
    _ang_l = math.atan2(CY - BY, CXL - BX)

    def _arc_pts(a_start, a_end, n=200):
        th = np.linspace(a_start, a_end, n)
        return list(zip(BX + R3 * np.cos(th), BY + R3 * np.sin(th)))

    def _ray_pt(deg, length=60):
        a = math.radians(deg)
        return BX + length * math.cos(a), BY + length * math.sin(a)

    def _zone_patch(zone, bg, alpha=0.92):
        kw = dict(facecolor=bg, edgecolor="#0b1c30", linewidth=1.8, alpha=alpha, zorder=2)
        if zone == "Paint":
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
            a115 = math.radians(115)
            arc = _arc_pts(_ang_l, a115)
            verts = [(0, CY), (CXL, CY)] + arc + [_ray_pt(115, 55), (0, 47)]
            ax.add_patch(plt.Polygon(verts, **kw))
        elif zone == "Top":
            a115, a65 = math.radians(115), math.radians(65)
            arc = _arc_pts(a115, a65)
            rx_l, ry_l = _ray_pt(115, 55)
            rx_r, ry_r = _ray_pt(65, 55)
            verts = [(rx_l, ry_l)] + arc + [(rx_r, ry_r), (rx_r, 47), (rx_l, 47)]
            ax.add_patch(plt.Polygon(verts, **kw))
        elif zone == "Wing Right":
            a65 = math.radians(65)
            arc = _arc_pts(a65, _ang_r)
            verts = [_ray_pt(65, 55)] + arc + [(CXR, CY), (50, CY), (50, 47), (25, 47)]
            ax.add_patch(plt.Polygon(verts, **kw))
        elif zone == "Mid Left":
            a135 = math.radians(135)
            arc = _arc_pts(_ang_l, a135)
            verts = [(CXL, CY)] + arc + [_ray_pt(135), (BX, BY)]
            ax.add_patch(plt.Polygon(verts, **kw))
        elif zone == "Mid Center-Left":
            a135, a90 = math.radians(135), math.radians(90)
            arc = _arc_pts(a135, a90)
            verts = [(BX, BY), _ray_pt(135)] + arc + [_ray_pt(90)]
            ax.add_patch(plt.Polygon(verts, **kw))
        elif zone == "Mid Center-Right":
            a90, a45 = math.radians(90), math.radians(45)
            arc = _arc_pts(a90, a45)
            verts = [(BX, BY), _ray_pt(90)] + arc + [_ray_pt(45)]
            ax.add_patch(plt.Polygon(verts, **kw))
        elif zone == "Mid Right":
            a45 = math.radians(45)
            arc = _arc_pts(a45, _ang_r)
            verts = [(BX, BY), _ray_pt(45)] + arc + [(CXR, CY)]
            ax.add_patch(plt.Polygon(verts, **kw))

    for zone, (cx, cy) in zone_centers.items():
        stats = zone_agg.get(_feed[zone])
        if not stats or not stats.get("total"):
            continue
        bg, fg = _zone_fg_color(stats["pct"], zone)
        _zone_patch(zone, bg)
        ax.text(cx, cy + 1.5, f"{stats['pct']:.0f}%", ha="center", va="center",
                color=fg, fontsize=15, fontweight="bold", zorder=6)
        ax.text(cx, cy - 1.6, f"{stats['made']}/{stats['total']}", ha="center", va="center",
                color=fg, fontsize=11, fontweight="bold", zorder=6)

    # Rim: drawn last so it punches a distinct circle through the middle of the Paint
    # wedge instead of being folded into that one broader "any 2 near the rim" number.
    _rim = zone_agg.get("rim")
    if _rim and _rim.get("total"):
        bg, fg = _zone_fg_color(_rim["pct"], "Rim")
        th = np.linspace(0, 2 * math.pi, 100)
        ax.add_patch(plt.Polygon(list(zip(BX + 4.0 * np.cos(th), BY + 4.0 * np.sin(th))),
                                  facecolor=bg, edgecolor="#0b1c30", linewidth=1.8, alpha=0.96, zorder=3))
        ax.text(BX, BY + 1.6, f"{_rim['pct']:.0f}%", ha="center", va="center",
                color=fg, fontsize=14, fontweight="bold", zorder=6)
        ax.text(BX, BY - 1.3, f"{_rim['made']}/{_rim['total']}", ha="center", va="center",
                color=fg, fontsize=10, fontweight="bold", zorder=6)

    _draw_half_court(ax)
    ax.set_xlim(0, 50)
    ax.set_ylim(-7.5, 47)
    ax.set_aspect("equal")
    ax.axis("off")

    _all_m = sum(zone_agg[k]["made"] for k in ("rim", "paint", "mid", "corner3", "atb3") if zone_agg.get(k))
    _all_a = sum(zone_agg[k]["total"] for k in ("rim", "paint", "mid", "corner3", "atb3") if zone_agg.get(k))
    _all_pct = _all_m / _all_a * 100 if _all_a else 0
    ax.text(25, -1.8, f"{_all_m}/{_all_a} FG  ({_all_pct:.1f}%)", ha="center", va="top",
            color="#eeeeee", fontsize=11, fontweight="bold", zorder=7)

    key_y = -5.8
    for kx, color, label in [
        (5.0,  "#1e50c8", "Below Average"),
        (23.0, "#f2f2f2", "Average"),
        (39.0, "#ffa000", "Above Average"),
    ]:
        ax.add_patch(Rectangle((kx - 0.9, key_y - 0.7), 1.8, 1.4, facecolor=color,
                                edgecolor="#666666", linewidth=0.6, zorder=7))
        ax.text(kx + 1.6, key_y, label, ha="left", va="center", color="#f5f5f5",
                fontsize=10, fontweight="bold", zorder=7)

    if title:
        ax.set_title(title, color="white", fontsize=13, fontweight="bold", pad=8)

    plt.tight_layout(pad=0.3)
    return fig


def fmt(val, decimals=1, suffix=""):
    """Format a numeric stat value for display."""
    if val is None or val == 0.0 or (isinstance(val, float) and math.isnan(val)):
        return "-"
    if decimals == 0:
        return f"{int(round(val))}{suffix}"
    return f"{round(float(val), decimals)}{suffix}"


def ordinal(n):
    """91 -> '91st', 42 -> '42nd', 11 -> '11th' (teens are always 'th')."""
    n = int(round(n))
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


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
    (efficiency) - i.e. both where they score from and how well. Used to make the comp finder
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
    """df_all + shot-zone columns where available (NaN elsewhere - handled gracefully downstream)."""
    zone_profile = build_shot_zone_profiles()
    if zone_profile.empty:
        return df_all
    return df_all.merge(
        zone_profile[["PLAYER", "TEAM"] + SHOT_ZONE_STATS],
        on=["PLAYER", "TEAM"], how="left"
    )


def get_player_shot_zone_dict(player_name, team_name=None):
    """PCT_RIM/PCT_MID/PCT_THREE (+ each zone's FG%) for one player, from real shot-chart
    data - used to feed shot-selection auto-tags (3PT Specialist, Rim Attacker, etc.) into
    build_auto_skill_tags for callers that only have a plain BartTorvik row on hand."""
    zone_profile = build_shot_zone_profiles()
    if zone_profile.empty:
        return {}
    match = zone_profile[zone_profile["PLAYER"] == player_name]
    if team_name is not None and len(match) > 1:
        _tm = match[match["TEAM"] == team_name]
        if not _tm.empty:
            match = _tm
    if match.empty:
        return {}
    row = match.iloc[0]
    return {col: row[col] for col in SHOT_ZONE_STATS if col in row.index and pd.notna(row[col])}


@st.cache_data(ttl=3600)
def build_synergy_playtype_profiles():
    """Per-player play-type mix (share of possessions run as spot-up, isolation, post-up,
    PnR, etc.) from Synergy - lets the comp finder compare *how* two players get their
    offense, not just their aggregate box-score shape.

    Synergy coverage in this database is whatever season(s) got scraped into
    synergy_playtypes - if that doesn't overlap the current comp pool's season, this simply
    returns no match for those players (playtype_mix_similarity returns None) and the comp
    score falls back to box stats + shot zones alone, exactly as before this existed.
    """
    try:
        conn = sqlite3.connect("scouting_hub.db")
        df = pd.read_sql_query(
            "SELECT player_name, play_type, time_percent FROM synergy_playtypes "
            "WHERE possessions > 0 AND time_percent IS NOT NULL",
            conn,
        )
        conn.close()
        if df.empty:
            return {}
        return {
            name: dict(zip(grp["play_type"], grp["time_percent"]))
            for name, grp in df.groupby("player_name")
        }
    except Exception:
        return {}


def playtype_mix_similarity(profile_a, profile_b):
    """Cosine similarity (0-1) between two play-type mix vectors - 1.0 means they get their
    offense the same way (same play types, same share of each). None if either player has
    no Synergy profile loaded, so callers can skip the term instead of treating it as 0."""
    if not profile_a or not profile_b:
        return None
    keys = set(profile_a) | set(profile_b)
    va = [profile_a.get(k, 0.0) for k in keys]
    vb = [profile_b.get(k, 0.0) for k in keys]
    na = math.sqrt(sum(a * a for a in va))
    nb = math.sqrt(sum(b * b for b in vb))
    if na == 0 or nb == 0:
        return None
    return sum(a * b for a, b in zip(va, vb)) / (na * nb)


@st.cache_data(ttl=3600)
def build_team_strength() -> pd.DataFrame:
    """Real team strength (KenPom-derived AdjEM) per BartTorvik team name - a continuous
    measure of level of competition, used instead of a blunt P5/non-P5 conference binary."""
    try:
        conn = sqlite3.connect("scouting_hub.db")
        df = pd.read_sql_query("SELECT bart_name AS TEAM, adj_em AS TEAM_ADJ_EM FROM team_rankings", conn)
        conn.close()
        return df.dropna(subset=["TEAM"])
    except Exception:
        return pd.DataFrame()


def add_derived_comp_stats(df_all: pd.DataFrame) -> pd.DataFrame:
    """df_all + shot-zone profile, team-strength (AdjEM), and AST/TO ratio - the extra
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
def _p5_filter(df: pd.DataFrame) -> pd.DataFrame:
    """Return only players from Power Five conferences."""
    if "CONF" in df.columns:
        return df[df["CONF"].isin(P5_CONFS)]
    return df


@st.cache_data(ttl=3600)
def build_national_benchmarks(df_all: pd.DataFrame) -> dict:
    """Sorted P5-only value lists per stat, used to percentile-rank any player for the tile card.
    Restricted to real rotation players (same GP/MIN_PCT floor as the comp finder) - without
    it, a benchmark pool packed with one-game garbage-time scrubs sitting at 0 on every stat
    drags the whole distribution down and inflates everyone else's percentile."""
    d = add_derived_comp_stats(_p5_filter(df_all))
    if "GP" in d.columns and "MIN_PCT" in d.columns:
        d = d[(d["GP"] >= COMP_MIN_GP) & (d["MIN_PCT"] >= COMP_MIN_MIN_PCT)]
    benchmarks = {}
    for col in NATIONAL_PCT_STATS + DERIVED_PCT_STATS + ["THREE_P_100"]:
        if col in d.columns:
            benchmarks[col] = sorted(d[col].dropna().tolist())
    return benchmarks


@st.cache_data(ttl=3600)
def build_position_benchmarks(df_all: pd.DataFrame, box_df: pd.DataFrame) -> dict:
    """Per-position sorted value lists (P5 only) for both BartTorvik and boxscore stats.
    Returns {position_group: {stat: sorted_list}} for Guard, Wing, Big. Restricted to real
    rotation players (same GP/MIN_PCT floor as the comp finder) for the same reason as
    build_national_benchmarks - garbage-time scrubs otherwise skew every percentile in the app."""
    try:
        conn = sqlite3.connect("scouting_hub.db")
        pos_df = pd.read_sql_query("SELECT player_name, position_group FROM player_positions", conn)
        conn.close()
    except Exception:
        pos_df = pd.DataFrame(columns=["player_name", "position_group"])

    df_p5 = _p5_filter(df_all)
    if "GP" in df_p5.columns and "MIN_PCT" in df_p5.columns:
        df_p5 = df_p5[(df_p5["GP"] >= COMP_MIN_GP) & (df_p5["MIN_PCT"] >= COMP_MIN_MIN_PCT)]
    _p5_names = set(df_p5["PLAYER"].tolist()) if not df_p5.empty else set()
    box_p5 = box_df[box_df["PLAYER"].isin(_p5_names)] if not box_df.empty else box_df
    if "GP" in box_p5.columns:
        box_p5 = box_p5[box_p5["GP"] >= COMP_MIN_GP]

    # Position group per player - prefer BartTorvik's own POS_TAG (real,
    # granular scouting-style data - covers nearly every P5 rotation player)
    # over the player_positions table. player_positions is NOT a manual coach
    # override - it's auto-scraped from ESPN's roster API, which only stores
    # a coarse G/F/C letter, exactly the kind of generic label that lists a
    # 6'7" combo forward as "Guard". Anyone missing from player_positions
    # used to be silently dropped from EVERY benchmark pool instead of
    # falling back to a real signal that was sitting right there.
    _player_group = {}
    if not pos_df.empty:
        for _name, _grp in zip(pos_df["player_name"], pos_df["position_group"]):
            _player_group[_name] = _grp
    if not df_p5.empty and "POS_TAG" in df_p5.columns:
        for _, _row in df_p5[["PLAYER", "POS_TAG"]].iterrows():
            _bucket = POS_TAG_BUCKET.get(_row["POS_TAG"])
            if _bucket:
                _player_group[_row["PLAYER"]] = _bucket

    result = {}
    for grp in ("Guard", "Wing", "Big"):
        names = {n for n, g in _player_group.items() if g == grp}

        # BartTorvik stats - P5 rotation players in this position group
        d = merge_shot_zones(df_p5[df_p5["PLAYER"].isin(names)].copy())
        if "AST" in d.columns and "TO" in d.columns:
            d["AST_TO"] = d.apply(lambda r: (r["AST"] / r["TO"]) if r["TO"] else None, axis=1)
        bm = {}
        for col in NATIONAL_PCT_STATS + ["AST_TO", "THREE_P_100"] + SHOT_ZONE_STATS:
            if col in d.columns:
                bm[col] = sorted(d[col].dropna().tolist())

        # Boxscore stats
        b = box_p5[box_p5["PLAYER"].isin(names)].copy()
        for col in ["PPG", "RPG", "APG", "SPG", "BPG", "FG_PCT", "TS", "EFG", "TWO_P",
                    "THREE_P", "FT_PCT", "FTR", "USG", "AST_PCT", "TOV_PCT", "AST_TO",
                    "OR_PCT", "DR_PCT", "STL_PCT", "BLK_PCT"]:
            if col in b.columns:
                bm[col] = sorted(b[col].dropna().tolist())

        result[grp] = bm
    return result


def build_advanced_stats_html(player_name, df_all, hdr_box=None, pos_benchmarks=None):
    """Same six-category (Efficiency/Impact/Playmaking/Shot Types/Rebounding/Defense)
    percentile-slider block as the Individual Player Stats 'Advanced Stats' expander,
    factored out so it can be reused anywhere a player's full profile is needed (e.g.
    the UCLA Roster page) without duplicating the whole player-card flow. Returns
    (position_group, left_column_html, right_column_html), or None if this player has
    no BartTorvik row or no box-score header row to build the card from."""
    p_matches = df_all[df_all["PLAYER"] == player_name]
    if p_matches.empty:
        # Fallback for spelling drift between the roster and BartTorvik (CJ vs C.J., Jr
        # present or not, accents) before giving up on this player entirely.
        _matched_name = find_name_match(player_name, df_all["PLAYER"].unique())
        if _matched_name is not None:
            p_matches = df_all[df_all["PLAYER"] == _matched_name]
    if p_matches.empty:
        return None
    p_data = p_matches.iloc[0]

    hdr_box = hdr_box if hdr_box is not None else load_consistent_boxscore_stats()
    hdr_row = hdr_box[hdr_box["PLAYER"] == player_name]
    if len(hdr_row) > 1:
        team_match = hdr_row[hdr_row["TEAM"].str.contains(str(p_data["TEAM"]), case=False, na=False)]
        if not team_match.empty:
            hdr_row = team_match
    hdr = hdr_row.iloc[0] if not hdr_row.empty else None
    if hdr is None:
        return None

    pos_benchmarks = pos_benchmarks if pos_benchmarks is not None else build_position_benchmarks(df_all, hdr_box)

    player_pos_group = "Guard"
    try:
        conn = sqlite3.connect("scouting_hub.db")
        pg_row = conn.execute(
            "SELECT position_group FROM player_positions WHERE player_name = ?", (player_name,)
        ).fetchone()
        conn.close()
        if pg_row:
            player_pos_group = pg_row[0]
    except Exception:
        pass

    active_bm = pos_benchmarks.get(player_pos_group, {})
    BOX_LOWER = {"TOV_PCT"}
    BT_LOWER = {"TO"}

    def _fmt(val, dec=1):
        try:
            return f"{float(val):.{dec}f}" if val is not None and str(val) not in ("", "nan", "None") else "-"
        except Exception:
            return "-"

    def _box_pct(col, val):
        vals = active_bm.get(col)
        if not vals or val is None:
            return None
        try:
            v = float(val)
            if math.isnan(v):
                return None
        except Exception:
            return None
        p = get_pct(v, vals)
        return (100 - p) if col in BOX_LOWER else p

    def _stat_row_colored(label, val, pct, suffix="", dec=1, accent="#2D68C4"):
        bg, bubble_fg = pct_color(pct)
        disp = _fmt(val, dec)
        val_str = f"{disp}{suffix}" if disp != "-" else "-"
        if pct is not None:
            fill_w = f"{pct:.1f}%"
            pct_num = f"{pct:.0f}"
            bubble = (
                f"<div style='position:absolute;top:50%;left:{fill_w};transform:translate(-50%,-50%);background:{bg};"
                f"color:{bubble_fg};font-size:0.62rem;font-weight:900;border-radius:50%;width:20px;height:20px;"
                f"display:flex;align-items:center;justify-content:center;z-index:2;border:1.5px solid rgba(0,0,0,0.25)'>{pct_num}</div>"
            )
            fill = f"<div style='position:absolute;top:0;left:0;height:100%;width:{fill_w};background:{bg};border-radius:4px'></div>"
        else:
            fill = bubble = ""
        label_fg = "#0F172A" if accent == "#F2A900" else "#FFFFFF"
        return (
            f"<div style='display:flex;align-items:center;margin-bottom:6px;gap:10px'>"
            f"<span style='display:inline-block;font-size:0.78rem;font-weight:900;letter-spacing:0.02em;"
            f"color:{label_fg};background:{accent};padding:4px 8px;border-radius:4px;min-width:64px;"
            f"text-align:center;flex-shrink:0'>{label}</span>"
            f"<div style='flex:1;position:relative;height:20px;border-radius:4px;overflow:visible;background:#e0e0e0'>"
            f"{fill}{bubble}"
            f"</div>"
            f"<span style='font-size:0.95rem;font-weight:900;color:#111;min-width:42px;text-align:right;flex-shrink:0'>{val_str}</span>"
            f"</div>"
        )

    def _cat_table(title, rows_html):
        return (
            f"<div style='margin-bottom:20px'>"
            f"<div style='font-size:1.05rem;font-weight:900;text-transform:uppercase;"
            f"letter-spacing:0.08em;margin-bottom:8px;color:#111;"
            f"border-bottom:2px solid #ddd;padding-bottom:4px'>{title}</div>"
            f"{''.join(rows_html)}"
            f"</div>"
        )

    def _divider_row():
        return "<div style='height:1px;background:#e8eaed;margin:14px 0 10px'></div>"

    def _shot_group(group_label, rows):
        def _bar_row(stat_label, val, pct, suffix=""):
            bg, bubble_fg = pct_color(pct)
            disp = _fmt(val)
            val_str = f"{disp}{suffix}" if disp != "-" else "-"
            if pct is not None:
                fill_w = f"{pct:.1f}%"
                pct_num = f"{pct:.0f}"
                bubble = (
                    f"<div style='position:absolute;top:50%;left:{fill_w};transform:translate(-50%,-50%);background:{bg};"
                    f"color:{bubble_fg};font-size:0.62rem;font-weight:900;border-radius:50%;width:20px;height:20px;"
                    f"display:flex;align-items:center;justify-content:center;z-index:2;border:1.5px solid rgba(0,0,0,0.25)'>{pct_num}</div>"
                )
                fill = f"<div style='position:absolute;top:0;left:0;height:100%;width:{fill_w};background:{bg};border-radius:4px'></div>"
            else:
                fill = bubble = ""
            return (
                f"<div style='display:flex;align-items:center;margin-bottom:6px;gap:10px'>"
                f"<span style='font-size:0.82rem;font-weight:800;color:#111;min-width:36px;text-align:right;flex-shrink:0'>{stat_label}</span>"
                f"<div style='flex:1;position:relative;height:20px;border-radius:4px;overflow:visible;background:#e0e0e0'>"
                f"{fill}{bubble}"
                f"</div>"
                f"<span style='font-size:0.95rem;font-weight:900;color:#111;min-width:42px;text-align:right;flex-shrink:0'>{val_str}</span>"
                f"</div>"
            )
        bars = "".join(_bar_row(*r) for r in rows)
        return (
            f"<div style='margin-bottom:8px'>"
            f"<span style='display:inline-block;font-size:0.72rem;font-weight:900;letter-spacing:0.06em;"
            f"text-transform:uppercase;color:#fff;background:#2D68C4;padding:2px 10px;"
            f"border-radius:4px;margin-bottom:6px'>{group_label}</span>"
            f"<div>{bars}</div>"
            f"</div>"
        )

    card_benchmarks = build_national_benchmarks(df_all)
    bt = p_data

    def _bt_pct(col, val):
        vals = active_bm.get(col)
        if vals:
            if not val or (isinstance(val, float) and math.isnan(val)):
                return None
            try:
                p = get_pct(float(val), vals)
                return (100 - p) if col in BT_LOWER else p
            except Exception:
                return None
        return national_pct(col, val, card_benchmarks)

    pbp_all = load_cbb_pbp_zones()
    pbp_bm = build_pbp_benchmarks()
    pbp_pe = pbp_all[
        (pbp_all["player_name"] == player_name) & (pbp_all["scope"] == "season")
    ] if not pbp_all.empty else pd.DataFrame()
    if not pbp_pe.empty:
        if len(pbp_pe) > 1 and "fga" in pbp_pe.columns:
            pbp_pe = pbp_pe.sort_values("fga", ascending=False)
        pbp_re = pbp_pe.iloc[0]

        def _pval(col):
            try:
                v = pbp_re.get(col)
                return float(v) if v is not None and str(v) not in ("", "nan", "None") else None
            except (TypeError, ValueError):
                return None

        def _pbp_pct(col):
            v = _pval(col)
            vals = pbp_bm.get(col)
            if v is None or not vals:
                return None
            return get_pct(v, vals)
        sc_rim_pct  = (_pval("atr2_fg_pct")   or 0) * 100
        sc_rim_freq = (_pval("atr2_fga_freq") or 0) * 100
        sc_mid_pct  = (_pval("mid2_fg_pct")   or 0) * 100
        sc_mid_freq = (_pval("mid2_fga_freq") or 0) * 100
        sc_3p_freq  = (_pval("fga3_rate")     or 0) * 100
        sc_ft_pct   = (_pval("ft_pct")        or 0) * 100
    else:
        _pval = lambda col: None
        _pbp_pct = lambda col: None
        sc_rim_pct = sc_rim_freq = sc_mid_pct = sc_mid_freq = sc_3p_freq = sc_ft_pct = None

    eff_html = _cat_table("Efficiency", [
        _stat_row_colored("ORTG",  bt.get("ORTG"),  _bt_pct("ORTG",  bt.get("ORTG"))),
        _stat_row_colored("USG%",  hdr.get("USG"),  _box_pct("USG",  hdr.get("USG")),  "%"),
        _stat_row_colored("TS%",   hdr.get("TS"),   _box_pct("TS",   hdr.get("TS")),   "%"),
        _stat_row_colored("OBPM",  p_data.get("OBPM"), _bt_pct("OBPM", p_data.get("OBPM")), "", 1),
    ])

    cbb_agg_all = load_cbb_player_agg()
    cbb_ir = cbb_agg_all[
        (cbb_agg_all["player_name"] == player_name) & (cbb_agg_all["scope"] == "season")
    ]
    cbb_impact = cbb_ir.iloc[0].to_dict() if not cbb_ir.empty else {}

    def _rapm_pct(val, lo=-5, hi=5):
        try:
            return max(0.0, min(100.0, (float(val) - lo) / (hi - lo) * 100))
        except (TypeError, ValueError):
            return None

    imp_html = _cat_table("Impact", [
        _stat_row_colored("RAPM",  cbb_impact.get("rapm"),  _rapm_pct(cbb_impact.get("rapm")), accent="#1B3E76"),
        _stat_row_colored("oRAPM", cbb_impact.get("orapm"), _rapm_pct(cbb_impact.get("orapm")), accent="#1B3E76"),
        _stat_row_colored("dRAPM", cbb_impact.get("drapm"), _rapm_pct(cbb_impact.get("drapm")), accent="#1B3E76"),
        _stat_row_colored("BPM",   p_data.get("BPM"),        _box_pct("BPM",  p_data.get("BPM")),  "", 1, accent="#1B3E76"),
    ])

    play_html = _cat_table("Playmaking", [
        _stat_row_colored("AST%",   hdr.get("AST_PCT"), _box_pct("AST_PCT", hdr.get("AST_PCT")), "%", accent="#F2A900"),
        _stat_row_colored("TOV%",   hdr.get("TOV_PCT"), _box_pct("TOV_PCT", hdr.get("TOV_PCT")), "%", accent="#F2A900"),
        _stat_row_colored("AST/TO", hdr.get("AST_TO"),  _box_pct("AST_TO",  hdr.get("AST_TO")),  "", 2, accent="#F2A900"),
        _stat_row_colored("USG%",   hdr.get("USG"),     _box_pct("USG",     hdr.get("USG")),     "%", accent="#F2A900"),
    ])

    ft_pct_val = sc_ft_pct if sc_ft_pct is not None else hdr.get("FT_PCT")
    ft_pct_col = _pbp_pct("ft_pct") or _box_pct("FT_PCT", hdr.get("FT_PCT"))
    shoot_html = _cat_table("Shot Types", [
        _shot_group("Rim", [
            ("FG%",  sc_rim_pct,  _pbp_pct("atr2_fg_pct"),   "%"),
            ("Freq", sc_rim_freq, _pbp_pct("atr2_fga_freq"), "%"),
        ]),
        _divider_row(),
        _shot_group("Mid", [
            ("FG%",  sc_mid_pct,  _pbp_pct("mid2_fg_pct"),   "%"),
            ("Freq", sc_mid_freq, _pbp_pct("mid2_fga_freq"), "%"),
        ]),
        _divider_row(),
        _shot_group("3PT", [
            ("FG%",  hdr.get("THREE_P"), _box_pct("THREE_P", hdr.get("THREE_P")), "%"),
            ("Freq", sc_3p_freq,          _pbp_pct("fga3_rate"),                    "%"),
        ]),
        _divider_row(),
        _shot_group("FT", [
            ("FT%",  ft_pct_val, ft_pct_col, "%"),
            ("Freq", hdr.get("FTR"), _box_pct("FTR", hdr.get("FTR")), "%"),
        ]),
    ])

    reb_html = _cat_table("Rebounding", [
        _stat_row_colored("OREB%", hdr.get("OR_PCT"), _box_pct("OR_PCT", hdr.get("OR_PCT")), "%", accent="#B8860B"),
        _stat_row_colored("DREB%", hdr.get("DR_PCT"), _box_pct("DR_PCT", hdr.get("DR_PCT")), "%", accent="#B8860B"),
        _stat_row_colored("RPG",   hdr.get("RPG"),    _box_pct("RPG",    hdr.get("RPG")), accent="#B8860B"),
    ])

    def_html = _cat_table("Defense", [
        _stat_row_colored("STL%",  hdr.get("STL_PCT"), _box_pct("STL_PCT", hdr.get("STL_PCT")), "%", accent="#334155"),
        _stat_row_colored("BLK%",  hdr.get("BLK_PCT"), _box_pct("BLK_PCT", hdr.get("BLK_PCT")), "%", accent="#334155"),
        _stat_row_colored("DBPM",  bt.get("DBPM"),     _bt_pct("DBPM",     bt.get("DBPM")), accent="#334155"),
        _stat_row_colored("SPG",   hdr.get("SPG"),     _box_pct("SPG",     hdr.get("SPG")), accent="#334155"),
        _stat_row_colored("BPG",   hdr.get("BPG"),     _box_pct("BPG",     hdr.get("BPG")), accent="#334155"),
    ])

    return player_pos_group, {
        "eff": eff_html, "imp": imp_html, "play": play_html,
        "shoot": shoot_html, "reb": reb_html, "def": def_html,
    }


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
            display = "-"
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
            ("A/TO", f"{a_to:.1f}" if a_to is not None else "-", a_to_pct if a_to_pct is not None else 50.0),
            t("MIN_PCT", "MIN%"),
        ]),
        ("REB / DEFENSE", [t("OR", "OR%"), t("DR", "DR%"), t("BLK", "BLK%"), t("STL", "STL%")]),
    ]


# ---- Auto-generated skill tags: real percentile stats, not hand-typed labels ----
# (stat, elite_label, decent_label, absolute_floor). The floor is a plain-English sanity
# check: a percentile alone can call a number "elite" just because it's compared against a
# position that doesn't do much of that thing (5.7% OR% reads as "85th percentile" next to
# other shooting guards, but isn't an elite rebounding number in any real sense). TO is
# lower-is-better, so its floor is treated as a ceiling instead of a minimum.
AUTO_TAG_STATS = [
    ("THREE_P", "Knockdown Shooter",              "Solid Three-Point Shooter",      34.0),
    ("FT_PCT",  "Automatic at the Line",          "Reliable Free-Throw Shooter",    72.0),
    ("TWO_P",   "Efficient Inside the Arc",       "Solid Two-Point Finisher",       48.0),
    ("TS",      "High-Efficiency Scorer",         "Efficient Scorer",              54.0),
    ("EFG",     "Elite Shot Selection",           "Good Shot Selection",           50.0),
    ("USG",     "High-Usage Focal Point",         "Featured Scoring Option",       20.0),
    ("AST",     "Playmaker",                      "Secondary Playmaker",           16.0),
    ("TO",      "Low-Mistake Ball-Handler",       "Takes Care of the Ball",        16.0),
    ("OR",      "Elite Offensive Rebounder",      "Decent Offensive Rebounder",     7.0),
    ("DR",      "Defensive Rebounding Anchor",    "Solid Defensive Rebounder",     14.0),
    ("BLK",     "Rim Protector",                  "Occasional Shot Blocker",        3.0),
    ("STL",     "Disruptive Defender",            "Active Hands on Defense",        1.8),
    ("BPM",     "High-Impact Winner",             "Positive Impact Player",         3.0),
    ("OBPM",    "Offensive Engine",               "Solid Offensive Contributor",    2.0),
    ("DBPM",    "Defensive Menace",               "Solid Defensive Contributor",    2.0),
    ("FTR",     "Draws Contact / Gets to the Line","Gets to the Line Some",        30.0),
    # Shot-selection tags - real shot-chart zone frequency (share of a player's own FGA
    # from that zone), not accuracy. A high PCT_THREE means they live behind the arc,
    # regardless of whether they're shooting well from there this season.
    ("PCT_THREE", "3PT Specialist",               "Three-Point Leaning",           40.0),
    ("PCT_RIM",   "Rim Attacker",                 "Rim-Conscious Scorer",          40.0),
    ("PCT_MID",   "Mid-Range Operator",            "Occasional Mid-Range Shooter", 25.0),
]

AUTO_TAG_ELITE_PCT = 93.0  # below this (but still >= threshold) gets the softer label


def build_auto_skill_tags(stats_row, benchmarks, top_n=4, threshold=80.0):
    """Tags generated from real percentiles, with two safeguards against overselling a
    stat: (1) the wording itself downgrades to "Decent"/"Solid" below AUTO_TAG_ELITE_PCT
    even when the percentile clears `threshold`, and (2) an absolute floor - a percentile
    can't earn ANY tag if the raw number wouldn't read as good in a plain scouting sense,
    no matter how favorable the position comparison is."""
    scored = []
    for stat, elite_label, decent_label, floor in AUTO_TAG_STATS:
        raw = stats_row.get(stat)
        pct = national_pct(stat, raw, benchmarks)
        if pct is None or pct < threshold:
            continue
        try:
            raw_val = float(raw)
        except (TypeError, ValueError):
            continue
        if stat in NATIONAL_LOWER_IS_BETTER:
            if raw_val > floor:  # floor doubles as a ceiling for lower-is-better stats
                continue
        elif raw_val < floor:
            continue
        label = elite_label if pct >= AUTO_TAG_ELITE_PCT else decent_label
        scored.append((pct, label))
    scored.sort(key=lambda x: -x[0])
    return [label for _, label in scored[:top_n]]


def build_volume_tags(box_row):
    """Absolute-count tags, independent of shooting percentage - a player can earn this
    even with a merely solid (not elite) shooting percentage, because a real season total
    of makes is a weapon on its own (e.g. a 35% three-point shooter who still buries 90
    threes a year is a threat defenses have to account for, regardless of percentile)."""
    tags = []
    if box_row is None:
        return tags
    try:
        made_3s = float(box_row.get("THREE_M_TOTAL"))
        if made_3s >= 60:
            tags.append("High-Volume 3PT Scorer")
    except (TypeError, ValueError):
        pass
    return tags


@st.cache_data(ttl=3600)
def build_all_player_tags(df_all: pd.DataFrame) -> dict:
    """{player_name: [every auto-generated skill/volume tag they qualify for]} for the
    whole player pool - the same tags shown on a Player Card's hero bar, computed once
    for everyone instead of a coach having to guess which raw stat threshold a tag like
    "Rim Protector" corresponds to. Used to power the Portal Discovery Engine's tag
    filter. top_n is set high (not the usual 4 shown on a card) so a player who
    qualifies for a tag isn't excluded just because it's not one of their top 4."""
    benchmarks = build_national_benchmarks(df_all)
    merged = merge_shot_zones(df_all)
    box_df = load_consistent_boxscore_stats()
    box_by_player = {}
    if not box_df.empty:
        for rec in box_df.to_dict("records"):
            box_by_player.setdefault(rec.get("PLAYER"), rec)

    result = {}
    for rec in merged.to_dict("records"):
        tags = build_auto_skill_tags(rec, benchmarks, top_n=len(AUTO_TAG_STATS), threshold=80.0)
        for vt in build_volume_tags(box_by_player.get(rec.get("PLAYER"))):
            if vt not in tags:
                tags.append(vt)
        if tags:
            result[rec.get("PLAYER")] = tags
    return result


def build_combo_tags(stats_row, benchmarks, position_group, box_row=None, top50_row=None,
                      recent_form=None, pos_benchmarks=None):
    """Multi-stat tags that no single percentile column can capture on its own - each one
    combines a role/position with a real number, the same way a scout would actually talk
    about a player instead of citing one stat in isolation."""
    tags = []

    def _pct(stat, val):
        return national_pct(stat, val, benchmarks)

    def _raw(stat):
        v = stats_row.get(stat)
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    # Stretch Big: a real big who's a live outside-shooting threat, not just a rim-runner -
    # needs both a real share of his shots from three (not token attempts) and a real
    # floor on the percentage, so a big jacking bad triples doesn't qualify. The 3-bucket
    # position system (Guard/Wing/Big) sometimes calls a 6'9" combo forward a "Wing," so
    # this checks real height too instead of trusting the bucket label alone - and always
    # compares his three-point share against true bigs specifically (not his own bucket),
    # since "unusual for a big" is the whole point and a Wing-vs-Wing comparison would
    # just measure whether he shoots as much as a normal wing does.
    height_in = parse_height_inches(stats_row.get("HEIGHT", "6-6"))
    if position_group in ("Wing", "Big") and height_in >= 80:
        pct_three = _raw("PCT_THREE")
        three_p = _raw("THREE_P")
        big_bm = (pos_benchmarks or {}).get("Big", benchmarks)
        pct_three_pctile = national_pct("PCT_THREE", pct_three, big_bm)
        if pct_three_pctile is not None and pct_three_pctile >= 60 and three_p is not None and three_p >= 30.0:
            tags.append("Stretch Big")

    # Turnover-Prone: heavy usage AND a genuinely high turnover rate together - a real risk
    # flag, not just a compliment paired with a caveat.
    usg_pctile = _pct("USG", _raw("USG"))
    to_raw = _raw("TO")
    if usg_pctile is not None and usg_pctile >= 70 and to_raw is not None and to_raw >= 18.0:
        tags.append("Turnover-Prone")

    # Point-of-Attack Defender: guards/wings who both get their hands on the ball AND move
    # the needle on defense overall - not just a steals compiler racking up gambles.
    if position_group in ("Guard", "Wing"):
        stl_pctile = _pct("STL", _raw("STL"))
        dbpm_pctile = _pct("DBPM", _raw("DBPM"))
        if stl_pctile is not None and stl_pctile >= 80 and dbpm_pctile is not None and dbpm_pctile >= 70:
            tags.append("Point-of-Attack Defender")

    # Foul-Prone: a plain rate stat, not percentile-based - fouling out is fouling out
    # regardless of what position peers around the country average.
    if box_row is not None:
        try:
            pf40 = float(box_row.get("PF_PER40"))
            if pf40 >= 4.0:
                tags.append("Foul-Prone")
        except (TypeError, ValueError):
            pass

    # Trusted in Big Games: plays MORE, not less, against ranked opponents - a real signal
    # of what the coaching staff actually trusts him with, instead of a season average that
    # blends in cupcake non-conference minutes.
    if box_row is not None and top50_row is not None:
        try:
            season_mpg = float(box_row.get("MPG"))
            top50_mpg = float(top50_row.get("MPG"))
            if top50_mpg - season_mpg >= 3.0:
                tags.append("Trusted in Big Games")
        except (TypeError, ValueError):
            pass

    # Late Riser: playing at a notably higher level right now than the season line alone
    # would suggest - useful mid-season, since a slow start can still be dragging the
    # average down even after the player has clearly turned a corner. Requires the scoring
    # bump NOT to be coming purely from a efficiency collapse (garbage volume).
    if recent_form is not None:
        s_ppg, r_ppg = recent_form.get("season_ppg"), recent_form.get("recent_ppg")
        s_ts, r_ts = recent_form.get("season_ts"), recent_form.get("recent_ts")
        if s_ppg is not None and r_ppg is not None and r_ppg - s_ppg >= 2.5:
            if s_ts is None or r_ts is None or r_ts >= s_ts - 2.0:
                tags.append("Late Riser")

    # 3-and-D: real perimeter shooting AND real defensive activity together - neither the
    # shooting tag nor the defense tag alone captures the actual archetype, only both at once.
    if position_group in ("Guard", "Wing"):
        three_p_pctile = _pct("THREE_P", _raw("THREE_P"))
        stl_pctile_3d = _pct("STL", _raw("STL"))
        dbpm_pctile_3d = _pct("DBPM", _raw("DBPM"))
        def_pctile_3d = max([p for p in (stl_pctile_3d, dbpm_pctile_3d) if p is not None], default=None)
        if three_p_pctile is not None and three_p_pctile >= 60 and def_pctile_3d is not None and def_pctile_3d >= 65:
            tags.append("3-and-D")

    # Low-Usage Efficient Shooter: doesn't need the ball to be effective - a low share of
    # team possessions paired with a real shooting percentile, the "plays within himself"
    # role guy, the opposite end of the spectrum from High-Usage Focal Point.
    ts_pctile_lu = _pct("TS", _raw("TS"))
    three_p_pctile_lu = _pct("THREE_P", _raw("THREE_P"))
    if (usg_pctile is not None and usg_pctile <= 30
            and ((ts_pctile_lu is not None and ts_pctile_lu >= 75)
                 or (three_p_pctile_lu is not None and three_p_pctile_lu >= 75))):
        tags.append("Low-Usage Efficient Shooter")

    # Score-First Combo Guard: real usage but not really setting up others - a caution/role
    # flag same as Turnover-Prone, not a compliment on its own.
    if position_group == "Guard":
        ast_pctile_sf = _pct("AST", _raw("AST"))
        if usg_pctile is not None and usg_pctile >= 75 and ast_pctile_sf is not None and ast_pctile_sf <= 40:
            tags.append("Score-First Combo Guard")

    # Live-Ball Rebounder: a big who rebounds at a real rate AND has real AST% for his
    # bucket - grabs it and pushes/creates rather than just kicking it out and standing still.
    if position_group == "Big":
        or_pctile_lb = _pct("OR", _raw("OR"))
        dr_pctile_lb = _pct("DR", _raw("DR"))
        reb_pctile_lb = max([p for p in (or_pctile_lb, dr_pctile_lb) if p is not None], default=None)
        big_bm_lb = (pos_benchmarks or {}).get("Big", benchmarks)
        ast_pctile_big = national_pct("AST", _raw("AST"), big_bm_lb)
        if reb_pctile_lb is not None and reb_pctile_lb >= 70 and ast_pctile_big is not None and ast_pctile_big >= 70:
            tags.append("Live-Ball Rebounder")

    # Secondary Rim Protector: a forward who blocks shots at a real rate without being the
    # team's primary rim protector (that's the Big-bucket "Rim Protector" tag) - decent, not
    # elite, is the point, so this sits below the single-stat tag's own threshold on purpose.
    if position_group == "Wing":
        wing_bm_srp = (pos_benchmarks or {}).get("Wing", benchmarks)
        blk_pctile_wing = national_pct("BLK", _raw("BLK"), wing_bm_srp)
        if blk_pctile_wing is not None and 50 <= blk_pctile_wing < 80:
            tags.append("Secondary Rim Protector")

    # Havoc Defender: real steal rate AND real block rate together, both compared within
    # his own position bucket - a versatile disruptor, not a one-trick defender.
    stl_pctile_hv = _pct("STL", _raw("STL"))
    blk_pctile_hv = _pct("BLK", _raw("BLK"))
    if stl_pctile_hv is not None and stl_pctile_hv >= 65 and blk_pctile_hv is not None and blk_pctile_hv >= 65:
        tags.append("Havoc Defender")

    # Undersized Producer: shorter than what's typical for his bucket but still producing
    # at an elite level anyway - a real "plays bigger than his size" signal.
    _undersized_ht = {"Guard": 71, "Wing": 76, "Big": 79}.get(position_group)
    if _undersized_ht is not None and height_in <= _undersized_ht:
        bpm_pctile_up = _pct("BPM", _raw("BPM"))
        prpg_pctile_up = _pct("PRPG", _raw("PRPG"))
        prod_pctile_up = max([p for p in (bpm_pctile_up, prpg_pctile_up) if p is not None], default=None)
        if prod_pctile_up is not None and prod_pctile_up >= 75:
            tags.append("Undersized Producer")

    # Veteran Presence: purely informational, not a skill claim - Sr/Graduate class year,
    # the "proven vet" context coaches actually reference in real conversations.
    _class_raw = str(stats_row.get("CLASS", "") or "").strip()
    if _class_raw in ("Sr", "Graduate"):
        tags.append("Veteran Presence")

    # Do-It-All Utility Player: no single loud carrying trait, but genuinely solid across
    # several categories at once - the steady glue guy who doesn't show up in any single-stat
    # tag because nothing he does is truly elite, yet he's a plus almost everywhere.
    _util_cat_avgs = []
    for _util_cat in ("Shooting", "Playmaking", "Rebounding", "Defense"):
        _util_stats = COMP_BOOST_STATS.get(_util_cat, [])
        _util_pcts = [p for p in (_pct(s, _raw(s)) for s in _util_stats) if p is not None]
        if _util_pcts:
            _util_cat_avgs.append(sum(_util_pcts) / len(_util_pcts))
    _util_solid = sum(1 for a in _util_cat_avgs if 55 <= a < 90)
    if _util_cat_avgs and _util_solid >= 3 and all(a < 90 for a in _util_cat_avgs):
        tags.append("Do-It-All Utility Player")

    # Outkicking His Team: elite personal impact despite playing for a team that isn't
    # very good - easy to miss in raw box stats, since team weakness usually shows up as
    # empty-looking team success, not suppressed individual numbers.
    _team_strength_df = build_team_strength()
    _team_adj_em = None
    if not _team_strength_df.empty:
        _team_row = _team_strength_df[_team_strength_df["TEAM"] == stats_row.get("TEAM")]
        if not _team_row.empty:
            _team_adj_em = _team_row.iloc[0]["TEAM_ADJ_EM"]
    bpm_pctile_ok = _pct("BPM", _raw("BPM"))
    if _team_adj_em is not None and _team_adj_em <= 8.0 and bpm_pctile_ok is not None and bpm_pctile_ok >= 85:
        tags.append("Outkicking His Team")

    return tags


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


@st.cache_data(ttl=3600)
def build_synergy_archetype_tags(player_name, freq_threshold=0.15, ppp_pct_threshold=65.0):
    """Named-play-type archetype tags that need both real frequency AND real efficiency in
    one specific Synergy action - build_synergy_auto_tags only looks at whichever action a
    player uses most or is most efficient at overall, not whether a specific named action
    (Spot Up, Off Screen) clears a real bar on both counts at once."""
    tags = []
    try:
        conn = sqlite3.connect("scouting_hub.db")
        for play_type, label in (("SpotUp", "Catch-and-Shoot Specialist"), ("OffScreen", "Movement Shooter")):
            row = conn.execute(
                "SELECT ppp, time_percent FROM synergy_playtypes WHERE player_name = ? AND play_type = ?",
                (player_name, play_type),
            ).fetchone()
            if not row or row[0] is None or row[1] is None or row[1] < freq_threshold:
                continue
            ppp = row[0]
            bench = sorted(r[0] for r in conn.execute(
                "SELECT ppp FROM synergy_playtypes WHERE play_type = ? AND ppp IS NOT NULL", (play_type,)
            ).fetchall())
            pct = get_pct(ppp, bench) if bench else None
            if pct is not None and pct >= ppp_pct_threshold:
                tags.append(label)
        conn.close()
    except Exception:
        pass
    return tags


# ---- Synergy back-of-card (uses the real synergy_playtypes / synergy_shots tables built by
#      build_synergy_playtypes.py / build_synergy_enriched.py - empty/graceful until those are run) ----
@st.cache_data(ttl=3600)
def get_synergy_card_data(player_name: str):
    try:
        conn = sqlite3.connect("scouting_hub.db")
        play_rows = conn.execute(
            "SELECT play_type, ppp, time_percent FROM synergy_playtypes "
            "WHERE player_name = ? AND time_percent > 0 ORDER BY time_percent DESC",
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
    pct_label = f'<div class="p" style="color:{fg};opacity:.7;">({ordinal(pct)})</div>' if pct is not None else ""
    return (f'<div class="tile" style="background:{bg}">'
            f'<div class="k" style="color:{fg};opacity:.72;">{label}</div>'
            f'<div class="v" style="color:{fg};">{value}</div>{pct_label}</div>')


# Friendly display names for Synergy play types
_PLAYTYPE_LABELS = {
    "PandRBallHandler": "PnR Ball Handler",
    "PandRRollMan":     "PnR Roll Man",
    "Iso":              "Isolation",
    "PostUp":           "Post Up",
    "SpotUp":           "Spot Up",
    "Cut":              "Cut",
    "OffScreen":        "Off Screen",
    "HandOff":          "Hand Off",
    "Transition":       "Transition",
}

# Stats to show per play type (column, label, suffix, decimals, lower_is_better)
_PLAYTYPE_STATS = [
    ("ppp",       "PPP",      "",  2, False),
    ("fg_pct",    "FG%",      "%", 1, False),
    ("turnover",  "TOV%",     "%", 1, True),
    ("possessions","Poss",    "",  0, False),
]

@st.cache_data(ttl=3600)
def get_synergy_playtype_rows(player_name: str, position_group: str):
    """
    Return a list of (play_type_label, stat_rows) for play types where the player
    has qualifying volume, with percentile ranks vs their position group.
    stat_rows: list of (stat_label, val, pct, suffix, dec)
    """
    try:
        conn = sqlite3.connect("scouting_hub.db")
        pt_rows = conn.execute(
            "SELECT play_type, possessions, ppp, fg_pct, fg_pct_eff, turnover, time_percent "
            "FROM synergy_playtypes WHERE player_name = ? AND possessions > 0 "
            "ORDER BY time_percent DESC NULLS LAST",
            (player_name,)
        ).fetchall()

        result = []
        for play_type, poss, ppp, fg_pct, fg_pct_eff, tov, time_pct in pt_rows:
            label = _PLAYTYPE_LABELS.get(play_type, play_type)

            def _synergy_pct(stat_col, val, lower_better=False):
                if val is None:
                    return None
                bench_row = conn.execute(
                    "SELECT sorted_values FROM synergy_percentiles "
                    "WHERE play_type=? AND position_group=? AND stat=?",
                    (play_type, position_group, stat_col)
                ).fetchone()
                if not bench_row:
                    return None
                bench = json.loads(bench_row[0])
                p = get_pct(val, bench)
                return (100 - p) if lower_better else p

            # TOV% = turnovers / possessions (raw count → rate for display & percentile)
            tov_rate = (tov / poss) if (tov is not None and poss and poss > 0) else None

            stat_rows = []
            for col, stat_label, suffix, dec, lower in _PLAYTYPE_STATS:
                if col == "fg_pct":
                    # DB stores as 0–1 fraction
                    display_val = fg_pct * 100 if fg_pct is not None else None
                    pct_val = fg_pct
                elif col == "turnover":
                    # bench now stores tov/poss rates; compare on the same scale
                    display_val = tov_rate * 100 if tov_rate is not None else None
                    pct_val = tov_rate
                elif col == "possessions":
                    display_val = poss
                    pct_val = poss
                else:
                    display_val = {"ppp": ppp}.get(col)
                    pct_val = display_val
                pct = _synergy_pct(col, pct_val, lower)
                stat_rows.append((stat_label, display_val, pct, suffix, dec))

            result.append((label, time_pct, stat_rows))

        conn.close()
        return result
    except Exception:
        return []


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
# FRONT OFFICE TARGET BOARD - position rows (per front office request: PG, CG, Wing,
# Four, Big), used to group the board and tag a player's primary position grouping in
# their scouting report.
# ==========================================
BOARD_POSITIONS = ["PG", "CG", "Wing", "Four", "Big"]

# International scouting notes use numeric positions (1-5, e.g. "3/4") - map those onto
# the same 6-bucket Big Board taxonomy so a report can go straight onto the board. Newer
# boards label position by section name instead of a number - map those too so both
# formats coexist in the same column without breaking "+ Add to Big Board".
_INTL_POS_TO_BOARD = {
    "1": "PG", "2": "CG", "3": "Wing", "4": "Four", "5": "Big",
    "3/4": "Wing", "4/3": "Four",
    "ON BALL GUARD": "PG", "COMBO GUARD": "CG", "WING": "Wing",
    "FOURS": "Four", "BIGS": "Big", "SHOOTING BIGS": "Big",
}


def _intl_pos_to_board(pos: str) -> str:
    return _INTL_POS_TO_BOARD.get(str(pos).strip(), "Wing")
# Scouting reports saved before the 6-bucket taxonomy used a smaller position set -
# fold those old values into the closest new bucket instead of losing the target.
LEGACY_BOARD_POS_MAP = {"W": "Wing", "F": "Four", "C": "Big"}

# BartTorvik's own position tag, mapped onto the 5-bucket board taxonomy.
_POS_TAG_TO_BOARD = {
    "Pure PG": "PG", "Scoring PG": "PG",
    "Combo G": "CG",
    "Wing G": "Wing", "Wing F": "Wing",
    "Stretch 4": "Four",
    "PF/C": "Big", "C": "Big",
}


def infer_board_position(p_data) -> str:
    """Best real-data guess at a player's Big Board position bucket - used whenever a
    player lands on the board without ever having had a position explicitly set, instead
    of silently defaulting everyone to PG regardless of whether they're actually a 6'10"
    center. Prefers BartTorvik's own position tag; falls back to height."""
    try:
        raw_tag = str(p_data.get("POS_TAG", "")) if p_data is not None else ""
    except Exception:
        raw_tag = ""
    if raw_tag in _POS_TAG_TO_BOARD:
        return _POS_TAG_TO_BOARD[raw_tag]
    try:
        height_in = parse_height_inches(p_data.get("HEIGHT", "")) if p_data is not None else None
    except Exception:
        height_in = None
    if height_in:
        if height_in >= 82:   # 6'10"+
            return "Big"
        if height_in >= 79:   # 6'7"-6'9"
            return "Four"
        if height_in >= 76:   # 6'4"-6'6"
            return "Wing"
    return "CG"

TIER_OPTIONS = ["High Priority", "Mid Priority", "Low Priority"]
VALUE_TAG_OPTIONS = ["Undervalued", "Properly Valued", "Overvalued"]
TIER_BADGE_COLORS = {"High Priority": "#F2A900", "Mid Priority": "#2D68C4", "Low Priority": "#94A3B8"}
VALUE_TAG_COLORS = {"Undervalued": "#16a34a", "Overvalued": "#dc2626", "Properly Valued": "#64748B"}

# ==========================================
# RECRUIT ALIGNMENT SURVEY (Max Feldman's pre-recruiting evaluation form)
# ==========================================
RECRUIT_BUCKETS = [
    "Tier A Transfer ($2.5M+ - one of three best players)",
    "Tier B Transfer (Role Player)",
    "Instant Impact High School Recruit",
    "Developmental High School Recruit",
]

RECRUIT_PRIORITY_OPTIONS = [
    "Tier 1 Priority (All-in pursuit)",
    "Tier 2 Priority (Strong pursuit)",
    "Continue Evaluating",
    "Monitor",
    "Pass",
]

SURVEY_PRIORITY_COLORS = {
    "Tier 1 Priority (All-in pursuit)": "#F2A900",
    "Tier 2 Priority (Strong pursuit)": "#2D68C4",
    "Continue Evaluating": "#64748B",
    "Monitor": "#94A3B8",
    "Pass": "#dc2626",
}

# (db column, short label for tags, full question, rung labels for 1-5)
SURVEY_CATEGORIES = [
    ("self_awareness", "Self-Awareness Alignment",
     "Does the player's perception of himself match our evaluation?",
     ["Major Disconnect", "Some Disconnect", "Mostly Aligned", "Strong Alignment", "Complete Alignment"]),
    ("circle_alignment", "Circle Alignment",
     "Does the player's support system see him similarly to how we evaluate him from a timeline perspective?",
     ["Completely Misaligned", "Mostly Misaligned", "Mixed", "Mostly Aligned", "Fully Aligned"]),
    ("positional_fit", "Positional Archetype Fit",
     "Does he fit the UCLA positional archetype?",
     ["Poor Fit", "Below Average", "Adequate", "Strong Fit", "Elite Fit"]),
    ("financial_alignment", "Financial Alignment",
     "Does their financial expectation match our valuation?",
     ["Extremely Far Apart", "Significant Gap", "Negotiable", "Mostly Aligned", "Fully Aligned"]),
    ("coachability", "Coachability / Infrastructure Fit",
     "Can this player thrive inside our program from a mental toughness standpoint?",
     ["Poor Fit", "Concerns", "Neutral", "Strong Fit", "Elite Fit"]),
    ("physical_toughness", "Physical Toughness", "",
     ["Soft", "Below Average", "Average", "Tough", "Elite Toughness"]),
    ("representation", "Representation Evaluation",
     "Does the player's representation serve as a positive or negative natural filter towards our principles?",
     ["Significant Concern", "Some Concern", "Neutral", "Positive", "Excellent Partner"]),
    ("info_influence", "Information & Influence Network",
     "Do we have an \"in\"?",
     ["None", "Weak", "Moderate", "Strong", "Excellent Access"]),
]


# ==========================================
# UNIVERSAL COMP FINDER - works for any player, not just curated portal targets.
# Similarity is computed in percentile space (same national percentiles used for the
# tile card / auto-tags), weighted by position bucket, with the weight boosted toward
# whichever real-stat category the player is genuinely elite in. Level of competition is
# handled via TEAM_ADJ_EM (real KenPom team strength) in the weights below, not a blunt
# P5/non-P5 binary - a strong non-P5 team and a weak P5 team should score differently.
# ==========================================
COMP_CATEGORY_STATS = {
    "Shooting":     ["THREE_P", "TWO_P", "TS", "EFG", "FT_PCT"],
    "Playmaking":   ["AST", "TO", "AST_TO"],
    "Rebounding":   ["OR", "DR"],
    "Defense":      ["BLK", "STL", "DBPM"],
    "Shot Profile": SHOT_ZONE_STATS,
}

# Stats that actually get the dominant-category boost - usually the same as COMP_CATEGORY_STATS,
# except Playmaking excludes raw TO%: it's usage-inflated (high-usage playmakers naturally cough
# it up more even when highly efficient), so boosting it alongside AST%/AST_TO would amplify a
# mismatch that has nothing to do with the actual "elite playmaker" trait being matched on.
COMP_BOOST_STATS = {**COMP_CATEGORY_STATS, "Playmaking": ["AST", "AST_TO"]}

# PCT_RIM/PCT_MID/PCT_THREE = shot-selection profile (where a player actually scores from), and
# *_FG_PCT = their real FG% from each of those zones (how well) - both from real shot-chart data.
# A real comp needs to account for this, not just overall shooting %.
COMP_BASE_WEIGHTS = {
    "Guard": {"ORTG": 0.13, "AST": 0.12, "TO": 0.09, "STL": 0.09, "MIN_PCT": 0.07, "THREE_P": 0.08,
              "TS": 0.06, "BPM": 0.06, "USG": 0.05, "EFG": 0.04, "OBPM": 0.03, "DBPM": 0.03,
              "OR": 0.02, "DR": 0.03, "BLK": 0.02, "FTR": 0.02, "FT_PCT": 0.02, "TWO_P": 0.02, "HEIGHT": 0.08,
              "PCT_THREE": 0.06, "PCT_RIM": 0.03, "PCT_MID": 0.02,
              "THREE_FG_PCT": 0.04, "RIM_FG_PCT": 0.02, "MID_FG_PCT": 0.02,
              "PRPG": 0.07, "AST_TO": 0.05, "TEAM_ADJ_EM": 0.09},
    "Wing":  {"BPM": 0.13, "DBPM": 0.09, "STL": 0.09, "BLK": 0.09, "DR": 0.09, "OR": 0.07,
              "TS": 0.05, "EFG": 0.04, "THREE_P": 0.05, "AST": 0.04, "USG": 0.04, "ORTG": 0.04,
              "TO": 0.03, "OBPM": 0.04, "MIN_PCT": 0.04, "FTR": 0.02, "FT_PCT": 0.02, "TWO_P": 0.02, "HEIGHT": 0.08,
              "PCT_THREE": 0.05, "PCT_RIM": 0.04, "PCT_MID": 0.02,
              "THREE_FG_PCT": 0.03, "RIM_FG_PCT": 0.03, "MID_FG_PCT": 0.02,
              "PRPG": 0.06, "AST_TO": 0.03, "TEAM_ADJ_EM": 0.09},
    "Big":   {"ORTG": 0.11, "OR": 0.11, "DR": 0.11, "BLK": 0.09, "AST": 0.07, "TO": 0.06,
              "MIN_PCT": 0.06, "BPM": 0.06, "TS": 0.05, "USG": 0.04, "EFG": 0.03, "STL": 0.03,
              "DBPM": 0.03, "OBPM": 0.03, "THREE_P": 0.02, "FTR": 0.02, "FT_PCT": 0.02, "TWO_P": 0.02, "HEIGHT": 0.08,
              "PCT_RIM": 0.07, "PCT_MID": 0.03, "PCT_THREE": 0.03,
              "RIM_FG_PCT": 0.05, "MID_FG_PCT": 0.02, "THREE_FG_PCT": 0.02,
              "PRPG": 0.06, "AST_TO": 0.02, "TEAM_ADJ_EM": 0.09},
}

DOMINANT_CATEGORY_BOOST = 3.0       # max multiplier, reached at the 100th percentile
DOMINANT_CATEGORY_RAMP_START = 50.0  # below this, no boost at all (multiplier 1.0)
DOMINANT_CATEGORY_MIN_PCT = 70.0    # bar for the "matched on X" UI label, not for weighting
# A real playmaking outlier (elite AST%) shouldn't get matched against someone who
# barely passes, even if their efficiency numbers happen to line up - that's a
# different player. Only kicks in once one side clears the outlier bar.
PLAYMAKING_OUTLIER_PCT = 85.0
PLAYMAKING_OUTLIER_GAP = 35.0
COMP_MIN_GP = 8       # exclude tiny/early-season samples from being potential comps
COMP_MIN_MIN_PCT = 20  # exclude garbage-time/deep-bench players (real signal is too noisy)
# Real sanity bound so a stat profile alone can never fully paper over a wildly different
# build (e.g. a 5'9" guard vs. a 7'0" center) - COMP_HEIGHT_SOFT_RANGE is deliberately wider
# than this used to be tied 1-for-1 to it, which meant a candidate at 5.4in off was
# excluded outright while one at 4.9in off got full credit. Decoupling the two removes that
# cliff: the hard bound stays sane, and the soft term inside the score does the smooth work.
COMP_HEIGHT_HARD_CUTOFF = 10
COMP_HEIGHT_SOFT_RANGE = 8
# How much weight real Synergy play-type mix gets in the final comp score, when both the
# target and a candidate actually have a Synergy profile loaded. Box stats + shot zones
# still carry the rest (1 - this) so the score stays fully explainable either way.
SYNERGY_MIX_WEIGHT = 0.18
# A comp score built on too little actual overlapping data (most stats missing for one
# side) isn't reliable even after renormalizing - require at least this fraction of the
# weighted stat set to have real values for both players before trusting the score at all.
COMP_MIN_WEIGHT_COVERAGE = 0.5


def find_player_dominant_category(stats_row, benchmarks):
    """Which real-stat category (Shooting/Playmaking/Rebounding/Defense) is this player's
    best, and how strong it is (0-100 avg percentile) - always returns both, since the
    strength is now used to scale the weighting boost continuously rather than as a hard
    on/off switch. Callers that need "is this a genuine standout" for UI purposes should
    compare the returned strength against DOMINANT_CATEGORY_MIN_PCT themselves."""
    cat_avgs = {}
    for cat, stats in COMP_CATEGORY_STATS.items():
        pcts = [p for p in (national_pct(s, stats_row.get(s), benchmarks) for s in stats) if p is not None]
        cat_avgs[cat] = sum(pcts) / len(pcts) if pcts else 0.0
    best_cat = max(cat_avgs, key=cat_avgs.get)
    return best_cat, cat_avgs[best_cat]


def build_comp_weights(bucket, dominant_category, dominant_strength=0.0):
    """dominant_strength (0-100 percentile in that category) scales the boost continuously
    from 1x at DOMINANT_CATEGORY_RAMP_START up to DOMINANT_CATEGORY_BOOST at the 100th
    percentile, instead of jumping straight to a 3x multiplier the instant a player crosses
    70 - two players a point apart on either side of that line used to get radically
    different weighting profiles for no real reason."""
    weights = dict(COMP_BASE_WEIGHTS.get(bucket, COMP_BASE_WEIGHTS["Wing"]))
    if dominant_category and dominant_strength > DOMINANT_CATEGORY_RAMP_START:
        t = min(1.0, (dominant_strength - DOMINANT_CATEGORY_RAMP_START) / (100.0 - DOMINANT_CATEGORY_RAMP_START))
        boost = 1.0 + t * (DOMINANT_CATEGORY_BOOST - 1.0)
        for stat in COMP_BOOST_STATS.get(dominant_category, []):
            if stat in weights:
                weights[stat] *= boost
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
    best_cat, best_cat_strength = find_player_dominant_category(target, benchmarks)
    weights = build_comp_weights(bucket, best_cat, best_cat_strength)
    total_weight = sum(weights.values())
    # Still gated at the real bar for the UI "matched on X" label - the continuous ramp
    # above only affects how the score is weighted, not when it's honest to call something
    # a genuine standout on the card.
    dominant_category = best_cat if best_cat_strength >= DOMINANT_CATEGORY_MIN_PCT else None

    target_name = str(target["PLAYER"])
    target_team = str(target["TEAM"])

    # Small samples are noisy - a candidate matching on 5 games of variance isn't a real comp.
    candidates = df_all[(df_all["GP"] >= COMP_MIN_GP) & (df_all["MIN_PCT"] >= COMP_MIN_MIN_PCT)]

    synergy_profiles = build_synergy_playtype_profiles()
    target_synergy = synergy_profiles.get(target_name)

    results = []
    for _, row in candidates.iterrows():
        if str(row["PLAYER"]) == target_name and str(row["TEAM"]) == target_team:
            continue
        cand_ht = parse_height_inches(row.get("HEIGHT", "6-6"))
        if abs(target_ht - cand_ht) > COMP_HEIGHT_HARD_CUTOFF:
            continue

        # Hard-disqualify a genuine playmaking outlier from being matched with someone
        # who isn't one, even if efficiency stats otherwise line up - that's not the
        # same kind of player, no matter how similar their scoring profile looks.
        t_ast_pct = national_pct("AST", target.get("AST"), benchmarks)
        c_ast_pct = national_pct("AST", row.get("AST"), benchmarks)
        if (t_ast_pct is not None and c_ast_pct is not None
                and max(t_ast_pct, c_ast_pct) >= PLAYMAKING_OUTLIER_PCT
                and abs(t_ast_pct - c_ast_pct) > PLAYMAKING_OUTLIER_GAP):
            continue

        score = 0.0
        weight_used = 0.0
        for stat, w in weights.items():
            if stat == "HEIGHT":
                score += w * max(0.0, 1 - abs(target_ht - cand_ht) / COMP_HEIGHT_SOFT_RANGE)
                weight_used += w
                continue
            t_pct = national_pct(stat, target.get(stat), benchmarks)
            c_pct = national_pct(stat, row.get(stat), benchmarks)
            if t_pct is None or c_pct is None:
                continue
            score += w * (1 - abs(t_pct - c_pct) / 100.0)
            weight_used += w

        # A candidate missing most of the weighted stat set (no shot-zone data, etc.)
        # shouldn't be capped below everyone else just for having a thinner profile than
        # what he does have shouldn't be judged against the full stat set's total weight -
        # renormalize over only the stats that actually had real values for both players,
        # but require a real amount of overlap before trusting the result at all.
        coverage = weight_used / total_weight if total_weight else 0.0
        if coverage < COMP_MIN_WEIGHT_COVERAGE:
            continue
        score = score / weight_used if weight_used else 0.0
        score = max(0.0, min(1.0, score))

        # Real Synergy play-type mix, when both players have one loaded - do they actually
        # get their offense the same way (spot-up vs. isolation vs. PnR), not just look
        # similar in the box score.
        pt_sim = playtype_mix_similarity(target_synergy, synergy_profiles.get(str(row["PLAYER"])))
        if pt_sim is not None:
            score = score * (1 - SYNERGY_MIX_WEIGHT) + pt_sim * SYNERGY_MIX_WEIGHT

        results.append((score, row))

    results.sort(key=lambda x: -x[0])
    return results[:n], dominant_category


def build_general_tiles(stats_row):
    """Basic per-game counting stats - no percentile benchmark for these, shown plain."""
    def plain(stat_key, label):
        try:
            v = float(stats_row[stat_key])
            if math.isnan(v):
                raise ValueError
        except (TypeError, ValueError, KeyError):
            return (label, "-", None)
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
    # BartTorvik category breakdown, then Synergy, then tags. No flip needed - the two
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
    for t in build_synergy_archetype_tags(name):
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
  :root{{--card:#ffffff;--edge:#dde2ee;--ink:#0F172A;--dim:#64748B;--faint:#94A3B8;--gold:#B8860B;--blue:#2D68C4;}}
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
  .tagchip{{background:#e8f1f9;color:#2D68C4;font-family:'DM Mono',monospace;font-size:10.5px;
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

# Reclassify forwards by height: Wing >= 6'9" (81 in) → Big, Big < 81 in → Wing.
# Runs once at startup; idempotent.
def _reclassify_positions_by_height(df):
    try:
        conn = sqlite3.connect("scouting_hub.db")
        cur = conn.cursor()
        cur.execute("SELECT player_name, position_group FROM player_positions")
        rows = cur.fetchall()
        name_to_pos = {r[0]: r[1] for r in rows}

        # Build a lookup: PLAYER → HEIGHT from BartTorvik
        ht_lookup = {}
        for _, row in df.iterrows():
            pname = row.get("PLAYER", "")
            ht = row.get("HEIGHT", "")
            if pname and ht:
                ht_lookup[pname] = ht

        updates = []
        for pname, cur_pos in name_to_pos.items():
            ht_str = ht_lookup.get(pname)
            if not ht_str:
                continue
            ht_in = parse_height_inches(ht_str)
            if cur_pos == "Wing" and ht_in >= 81:
                updates.append(("Big", pname))
            elif cur_pos == "Big" and ht_in < 81:
                updates.append(("Wing", pname))

        if updates:
            cur.executemany(
                "UPDATE player_positions SET position_group = ? WHERE player_name = ?",
                updates,
            )
            conn.commit()
    except Exception:
        pass  # Non-fatal; percentiles still work with old classifications

_reclassify_positions_by_height(df_all)

all_player_names = sorted(list(df_all["PLAYER"].unique()))

if "active_player" not in st.session_state:
    st.session_state.active_player = None
if "active_player_team" not in st.session_state:
    # Some player names collide across schools (e.g. two different "Michael Cooper"s in
    # the same season) - when navigation knows the specific team (comp cards, Portal
    # Discovery Engine, Target Board), it's stored here so the Player Card can pick the
    # right row instead of silently grabbing whichever match happens to come first.
    st.session_state.active_player_team = None
if "go_to_profile" not in st.session_state:
    st.session_state.go_to_profile = False
if "go_to_tab" not in st.session_state:
    # Generic "jump to this tab index on the next rerun" - go_to_profile above is the
    # older, single-purpose version of this (always index 1). New cross-tab jumps (e.g.
    # International Players -> Recruit Alignment Survey) use this instead of adding a
    # new one-off boolean flag per destination tab.
    st.session_state.go_to_tab = None

# ==========================================
# HEADER
# ==========================================
st.markdown("""
<div id="ucla-header">
  <img src="https://cdn.freebiesupply.com/logos/large/2x/ucla-bruins-1-logo-png-transparent.png" alt="UCLA Logo">
  <div id="ucla-header-title">UCLA Basketball Analytics</div>
</div>
""", unsafe_allow_html=True)

tab_home, tab_card, tab_depth, tab_onepager, tab2, tab3, tab4, tab_synergy, tab_intl, tab_evals = st.tabs([
    "Home",
    "Individual Player Stats",
    "UCLA Roster",
    "Print Out",
    "Portal Discovery Engine",
    "Front Office Target Board",
    "Recruit Alignment Survey",
    "Synergy Play Types",
    "International Players",
    "Player Evaluations",
])

import streamlit.components.v1 as components
_go_to_profile = st.session_state.go_to_profile
if _go_to_profile:
    st.session_state.go_to_profile = False
_go_to_tab = st.session_state.go_to_tab
if _go_to_tab is not None:
    st.session_state.go_to_tab = None

components.html(f"""
<script>
(function() {{
    var goToProfile = {'true' if _go_to_profile else 'false'};
    var goToTabIdx = {_go_to_tab if _go_to_tab is not None else 'null'};
    // v2: Home tab added at index 0 - wipe any stale saved index so we default to Home
    if (localStorage.getItem('uclaTabVersion') !== '2') {{
        localStorage.removeItem('uclaActiveTab');
        localStorage.setItem('uclaTabVersion', '2');
    }}
    var savedTab = goToProfile ? 1 : (goToTabIdx !== null ? goToTabIdx : parseInt(localStorage.getItem('uclaActiveTab') || '0'));

    function attachListeners(tabs) {{
        tabs.forEach(function(tab, i) {{
            tab.addEventListener('click', function() {{
                localStorage.setItem('uclaActiveTab', i);
            }});
        }});
    }}

    function tryRestore() {{
        var tabs = window.parent.document.querySelectorAll('[data-baseweb="tab"]');
        if (tabs.length >= 9) {{
            attachListeners(tabs);
            if (goToProfile || goToTabIdx !== null || savedTab > 0) {{
                tabs[savedTab].click();
                if (goToProfile) {{ localStorage.setItem('uclaActiveTab', '1'); }}
                else if (goToTabIdx !== null) {{ localStorage.setItem('uclaActiveTab', String(goToTabIdx)); }}
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
                }} else if (evt.data && evt.data.type === 'nav_click') {{
                    var tabIdx = evt.data.tab;
                    var tabs = window.parent.document.querySelectorAll('[data-baseweb="tab"]');
                    if (tabs.length > tabIdx) {{
                        tabs[tabIdx].click();
                        localStorage.setItem('uclaActiveTab', tabIdx);
                    }}
                }}
            }});
        }} catch(e) {{ console.warn('postMessage listener failed:', e); }}
    }}
}})();
</script>
""", height=0, width=0)

# ==========================================
# LINEUP ANALYZER - helpers (used in depth chart tab)
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


def _rank_players(query, names):
    q = query.lower().strip()
    if not q:
        return names
    results = []
    for name in names:
        nl = name.lower()
        words = nl.split()
        # Score 0: full name starts with query (e.g. "jamar" → "Jamar Brown")
        if nl.startswith(q):
            score = 0
        # Score 1: any word starts with query AND it's a close match length-wise
        elif any(w.startswith(q) for w in words):
            # prefer first-name matches over last-name matches
            if words[0].startswith(q):
                score = 1
            else:
                score = 2
        # Score 3: query is a substring of any word (e.g. "mar" inside "Jamar")
        elif any(q in w for w in words):
            score = 3
        # Score 4: query appears anywhere in the full name
        elif q in nl:
            score = 4
        else:
            continue
        results.append((score, name))
    results.sort(key=lambda x: (x[0], x[1]))
    return [n for _, n in results]


# ==========================================
# TAB: DEPTH CHART (FRONT PAGE)
# ==========================================
with tab_depth:
    st.subheader("26-27 UCLA Roster")

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

    _ucla_jerseys = fetch_ucla_jersey_numbers()

    # ---- Rim efficiency (CBB Analytics PBP zone data) for cards below - same
    # percentile-bar slider language as the Individual Player Stats card. ----
    _pbp_season_all = load_cbb_pbp_zones()
    _pbp_bm_roster = build_pbp_benchmarks()
    _rim_stats = {}
    if not _pbp_season_all.empty:
        for _, _pr in _pbp_season_all[_pbp_season_all["scope"] == "season"].iterrows():
            try:
                _rim_fga = float(_pr.get("atr2_fga") or 0)
            except (TypeError, ValueError):
                _rim_fga = 0
            if _rim_fga <= 0:
                continue
            _rim_fg_raw = _pr.get("atr2_fg_pct")
            _rim_freq_raw = _pr.get("atr2_fga_freq")
            _rim_stats[_pr["player_name"]] = {
                "pct":       float(_rim_fg_raw or 0) * 100,
                "freq":      float(_rim_freq_raw or 0) * 100,
                "pct_rank":  get_pct(float(_rim_fg_raw), _pbp_bm_roster.get("atr2_fg_pct", [])) if _rim_fg_raw is not None else None,
                "freq_rank": get_pct(float(_rim_freq_raw), _pbp_bm_roster.get("atr2_fga_freq", [])) if _rim_freq_raw is not None else None,
            }

    def _mini_slider(label, val_str, pct_rank):
        bg, fg = pct_color(pct_rank)
        if pct_rank is not None:
            fill_w = f"{pct_rank:.1f}%"
            bubble = (
                f"<div style='position:absolute;top:50%;left:{fill_w};transform:translate(-50%,-50%);"
                f"background:{bg};color:{fg};font-size:8px;font-weight:900;border-radius:50%;width:14px;height:14px;"
                f"display:flex;align-items:center;justify-content:center;z-index:2;border:1px solid rgba(0,0,0,0.25)'>{pct_rank:.0f}</div>"
            )
            fill = f"<div style='position:absolute;top:0;left:0;height:100%;width:{fill_w};background:{bg};border-radius:3px'></div>"
        else:
            fill = bubble = ""
        return (
            "<div style='display:flex;align-items:center;gap:6px;margin-top:4px;'>"
            f"<span style='font-size:9px;font-weight:800;color:#475569;min-width:52px;flex-shrink:0;'>{label}</span>"
            "<div style='flex:1;position:relative;height:12px;border-radius:3px;overflow:visible;background:#e0e0e0;'>"
            f"{fill}{bubble}"
            "</div>"
            f"<span style='font-size:10px;font-weight:800;color:#0F172A;min-width:28px;text-align:right;flex-shrink:0;'>{val_str}</span>"
            "</div>"
        )

    # ---- Shot Types (CBB Analytics PBP zone data) + headshot for every UCLA player
    # we have CBB data for - the roster page's job now is fast access to real shot
    # profile at a glance, not the full player-card stat dump. ----
    st.markdown("#### Player Shot Profile (CBB Analytics)")
    _hdr_box_roster = load_consistent_boxscore_stats()
    _pos_bm_roster = build_position_benchmarks(df_all, _hdr_box_roster)
    _cbb_agg_all_roster = load_cbb_player_agg()
    _cbb_names_available = (
        set(_cbb_agg_all_roster[_cbb_agg_all_roster["scope"] == "season"]["player_name"])
        if not _cbb_agg_all_roster.empty else set()
    )
    _adv_conn = sqlite3.connect("scouting_hub.db")
    _roster_names_df = pd.read_sql_query(
        "SELECT player_name, bt_name FROM roster WHERE player_name != 'OPEN' ORDER BY player_name",
        _adv_conn,
    )
    _adv_conn.close()

    _adv_shown = 0
    for _, _rn in _roster_names_df.iterrows():
        _rp_name = _rn["player_name"]
        if _rp_name not in _cbb_names_available:
            # Fallback for spelling drift (CJ vs C.J., Jr present or not, accents) between
            # the roster and the CBB Analytics pull before assuming there's no data for him.
            _cbb_match = find_name_match(_rp_name, _cbb_names_available)
            if _cbb_match is None:
                continue
            _rp_name = _cbb_match
        _lookup_name = _rn["bt_name"] if _rn["bt_name"] else _rp_name
        _adv = build_advanced_stats_html(_lookup_name, df_all, _hdr_box_roster, _pos_bm_roster)
        if _adv is None:
            continue
        _adv_shown += 1
        _pos_group, _cats = _adv

        _p_match = df_all[df_all["PLAYER"] == _lookup_name]
        _team_espn_id = (
            str(_p_match.iloc[0]["team_espn_id"])
            if not _p_match.empty and pd.notna(_p_match.iloc[0].get("team_espn_id"))
            else ""
        )
        _headshot = get_player_headshot(_rp_name, _team_espn_id, "UCLA")

        with st.container(border=True):
            st.markdown(f"**{_rp_name}**")
            _adv_c1, _adv_c2 = st.columns([1, 3])
            with _adv_c1:
                if _headshot:
                    st.image(_headshot, use_container_width=True)
                else:
                    st.caption("No headshot")
            with _adv_c2:
                st.markdown(_cats["shoot"], unsafe_allow_html=True)
    if _adv_shown == 0:
        st.caption("No UCLA players with CBB Analytics data loaded yet - run fetch_cbb_analytics.py.")

    st.divider()

    # ---- VISUAL DEPTH CHART ----
    conn = sqlite3.connect('scouting_hub.db')
    chart_df = pd.read_sql_query(
        "SELECT player_name, position, depth, descriptor, bt_name, height, class_yr FROM roster ORDER BY depth",
        conn
    )
    conn.close()

    POSITIONS = [("PG", "Point Guard"), ("CG", "Combo Guard"), ("SF", "Small Forward"),
                 ("PF", "Power Forward"), ("C", "Center")]
    POSITION_CODES = [p[0] for p in POSITIONS]

    def _roster_swap_depth(name_a, name_b):
        conn = sqlite3.connect('scouting_hub.db')
        cur = conn.cursor()
        da = cur.execute("SELECT depth FROM roster WHERE player_name=?", (name_a,)).fetchone()[0]
        db_ = cur.execute("SELECT depth FROM roster WHERE player_name=?", (name_b,)).fetchone()[0]
        cur.execute("UPDATE roster SET depth=? WHERE player_name=?", (db_, name_a))
        cur.execute("UPDATE roster SET depth=? WHERE player_name=?", (da, name_b))
        conn.commit()
        conn.close()

    def _roster_move_position(name, new_pos_code):
        conn = sqlite3.connect('scouting_hub.db')
        cur = conn.cursor()
        max_depth = cur.execute(
            "SELECT MAX(depth) FROM roster WHERE position=?", (new_pos_code,)
        ).fetchone()[0]
        cur.execute(
            "UPDATE roster SET position=?, depth=? WHERE player_name=?",
            (new_pos_code, (max_depth or 0) + 1, name),
        )
        conn.commit()
        conn.close()

    # Shared "trading card" styling for every roster card rendered directly on the page
    # (the clickable ones live in their own iframe below and carry their own copy of this,
    # since an iframe is a separate document and can't inherit page-level <style>).
    # The card visual (name/stats/jersey watermark) is now borderless/shadowless on its
    # own - a single st.container(border=True) per player is the one visual boundary,
    # holding both the card AND its move arrows so they read as one unit instead of a
    # card with orphaned icons floating underneath it.
    ROSTER_CARD_CSS = """
      .card { position:relative; overflow:hidden; padding:2px 4px 6px; background:#FFFFFF; }
      .card.starter { border-left:4px solid #F2A900; padding-left:12px; margin-left:-8px; }
      .card .top { display:flex; justify-content:space-between; align-items:center; position:relative; z-index:1; }
      .card .name { font-size:19.5px; font-weight:800; color:#0F172A; }
      .card .starter-badge { font-size:8.5px; background:#F2A900; color:#0F172A; font-weight:800;
        padding:2px 7px; border-radius:3px; letter-spacing:0.4px; }
      .card .stat-line { font-size:16.5px; font-weight:800; color:#1B3E76; margin-top:7px; position:relative; z-index:1; }
      .card .stat-line-adv { font-size:13.5px; font-weight:600; color:#475569; margin-top:4px; position:relative; z-index:1; }
      .card .meta { font-size:11px; color:#94A3B8; margin-top:6px; position:relative; z-index:1; }
    """
    st.markdown(f"<style>{ROSTER_CARD_CSS}</style>", unsafe_allow_html=True)
    # Move arrows sit inside the same bordered container as the card, right below it -
    # kept visually quiet (no border/background of their own) so the card stays the
    # focal point and the arrows read as a toolbar for it, not a separate element.
    st.markdown("""
<style>
div.element-container:has(.roster-arrow-marker) + div[data-testid="stLayoutWrapper"] div[data-testid="stHorizontalBlock"] button {
    border: none !important; background: transparent !important; color: #94A3B8 !important;
    font-size: 12px !important; min-height: 24px !important; height: 24px !important;
    padding: 0 !important; box-shadow: none !important;
}
div.element-container:has(.roster-arrow-marker) + div[data-testid="stLayoutWrapper"] div[data-testid="stHorizontalBlock"] button:hover {
    color: #2D68C4 !important; background: #F1F5F9 !important;
}
div.element-container:has(.roster-arrow-marker) + div[data-testid="stLayoutWrapper"] div[data-testid="stHorizontalBlock"] {
    gap: 0 !important; margin-top: -8px;
}
</style>
""", unsafe_allow_html=True)

    pos_cols = st.columns(5)

    for i, (pos_code, pos_label) in enumerate(POSITIONS):
        with pos_cols[i]:
            st.markdown(f"""
                <div style='background-color:#2D68C4; color:white; font-weight:bold;
                            text-align:center; padding:8px; border-radius:6px; margin-bottom:10px;
                            font-size:13px; letter-spacing:0.5px;'>
                    {pos_code}<br><span style='font-size:9px; font-weight:400; opacity:0.85;'>{pos_label}</span>
                </div>
            """, unsafe_allow_html=True)

            group = chart_df[chart_df["position"] == pos_code].sort_values("depth")

            if group.empty:
                continue

            ordered_names_in_col = group["player_name"].tolist()

            for row_idx, (_, pl) in enumerate(group.iterrows()):
                pname = pl["player_name"]
                descriptor = pl["descriptor"] if pl["descriptor"] else ""
                bt_name = pl["bt_name"] if pl["bt_name"] else ""
                roster_ht = pl["height"] if pl.get("height") else ""
                roster_cl = pl["class_yr"] if pl.get("class_yr") else ""
                is_open = pname.strip().upper() == "OPEN"
                is_starter = int(pl["depth"]) == 1

                if is_open:
                    st.markdown(
                        "<div style=\"border:2px dashed #F2A900;border-radius:8px;padding:12px 10px;"
                        "margin-bottom:8px;background-color:rgba(255,209,0,0.06);text-align:center;\">"
                        "<div style=\"font-size:13px;font-weight:bold;color:#F2A900;\">OPEN</div>"
                        "<div style=\"font-size:10px;color:#F2A900;opacity:0.85;margin-top:2px;\">" + descriptor + "</div>"
                        "</div>",
                        unsafe_allow_html=True
                    )
                    continue

                import re as _re
                card_key = _re.sub(r'[^a-zA-Z0-9_]', '', f"dc_{pos_code}_{pname.replace(' ', '_')}")
                pos_idx = POSITION_CODES.index(pos_code)

                starter_badge = "<span class='starter-badge'>STARTER</span>" if is_starter else ""
                starter_class = " starter" if is_starter else ""

                ppg_v = apg_v = rpg_v = usg_v = bpm_v = ts_v = "-"
                height_class = ""
                jersey = _ucla_jerseys.get(pname.lower().strip(), "")
                pg = _pg_stats.get(pname, {})

                if bt_name:
                    bt_match = df_all[df_all["PLAYER"] == bt_name]
                    if not bt_match.empty:
                        s = bt_match.iloc[0]
                        ppg_v = f"{pg['ppg']:.1f}" if pg.get('ppg') is not None else f"{s['PPG']:.1f}"
                        apg_v = f"{pg['apg']:.1f}" if pg.get('apg') is not None else (f"{s['APG']:.1f}" if s.get('APG', 0) else "-")
                        rpg_v = f"{pg['rpg']:.1f}" if pg.get('rpg') is not None else (f"{s['RPG']:.1f}" if s.get('RPG', 0) else "-")
                        usg_v = f"{s['USG']:.0f}%" if s.get('USG', 0) else "-"
                        bpm_v = f"{s['BPM']:+.1f}" if s.get('BPM', 0) else "-"
                        ts_v  = f"{s['TS']:.0f}%"  if s.get('TS', 0)  else "-"
                        ht = s.get('HEIGHT', '') or ''
                        cl = s.get('CLASS', '') or ''
                        if ht or cl:
                            height_class = f"{ht}{'  ·  ' if ht and cl else ''}{cl}"
                elif pg:
                    # In game logs but no BartTorvik - show what we have
                    ppg_v = f"{pg['ppg']:.1f}"
                    apg_v = f"{pg['apg']:.1f}"
                    rpg_v = f"{pg['rpg']:.1f}"
                    if roster_ht or roster_cl:
                        height_class = f"{roster_ht}{'  ·  ' if roster_ht and roster_cl else ''}{roster_cl}"
                else:
                    # No BartTorvik, no game logs - show height/class from roster if available
                    if roster_ht or roster_cl:
                        height_class = f"{roster_ht}{'  ·  ' if roster_ht and roster_cl else ''}{roster_cl}"

                has_stats = ppg_v != "-" or apg_v != "-" or rpg_v != "-"
                jersey_html = f"<div class='jersey'>{jersey}</div>" if jersey else ""
                stat_line = (
                    f"<div class='stat-line'>{ppg_v} PPG &middot; {apg_v} APG &middot; {rpg_v} RPG</div>"
                    if has_stats else ""
                )
                adv_line = (
                    f"<div class='stat-line-adv'>{usg_v} USG &middot; {bpm_v} BPM &middot; {ts_v} TS%</div>"
                    if has_stats else ""
                )
                _rim = _rim_stats.get(pname)
                rim_line = (
                    _mini_slider("RIM FG%", f"{_rim['pct']:.0f}%", _rim["pct_rank"])
                    + _mini_slider("RIM FREQ", f"{_rim['freq']:.0f}%", _rim["freq_rank"])
                    if _rim else ""
                )
                meta_line = f"<div class='meta'>{height_class}</div>" if height_class else ""

                card_inner = (
                    f"{jersey_html}"
                    f"<div class='top'><span class='name'>{pname}</span>{starter_badge}</div>"
                    f"{stat_line}{adv_line}{rim_line}{meta_line}"
                )

                # Every card opens the Player Card on double-click now (single click is the
                # move arrows above) - even bench players without a matched BartTorvik stat
                # line still take you to a search on their name, which is more useful than a
                # dead end.
                open_target = bt_name if bt_name else pname
                btn_trigger = f"__dc__{card_key}"
                card_height = (152 if height_class else 136) if has_stats else 64
                if _rim:
                    card_height += 40

                with st.container(border=True):
                    components.html(f"""
<style>
  body {{ margin:0; padding:0; overflow:hidden; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
  {ROSTER_CARD_CSS}
  .card {{ cursor:pointer; user-select:none; }}
</style>
<div class="card{starter_class}" ondblclick="window.parent.postMessage({{type:'dc_click',key:'{btn_trigger}'}}, '*')" title="Double-click to open">
  {card_inner}
</div>
""", height=card_height, scrolling=False)
                    # Hidden trigger button - zero height, caught by postMessage listener
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
                        st.session_state.active_player = open_target
                        st.session_state.go_to_profile = True
                        st.rerun()

                    # Move arrows, inside the same bordered box as the card, right below it -
                    # up/down swaps depth order within this position column, left/right hands
                    # the player to the adjacent position column entirely.
                    st.markdown("<div class='roster-arrow-marker'></div>", unsafe_allow_html=True)
                    a_up, a_dn, a_left, a_right = st.columns(4)
                    if a_up.button("↑", key=f"ru_{card_key}", disabled=(row_idx == 0), help="Move up"):
                        _roster_swap_depth(pname, ordered_names_in_col[row_idx - 1])
                        st.rerun()
                    if a_dn.button("↓", key=f"rd_{card_key}", disabled=(row_idx == len(ordered_names_in_col) - 1), help="Move down"):
                        _roster_swap_depth(pname, ordered_names_in_col[row_idx + 1])
                        st.rerun()
                    if a_left.button("←", key=f"rl_{card_key}", disabled=(pos_idx == 0), help="Move to previous position"):
                        _roster_move_position(pname, POSITION_CODES[pos_idx - 1])
                        st.rerun()
                    if a_right.button("→", key=f"rr_{card_key}", disabled=(pos_idx == len(POSITION_CODES) - 1), help="Move to next position"):
                        _roster_move_position(pname, POSITION_CODES[pos_idx + 1])
                        st.rerun()

    st.divider()

    # ==========================================
    # MOST COMMON 5-MAN LINEUPS
    # ==========================================
    with st.expander("Most Used 5-Man Lineups", expanded=False):

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
            def _short_name(full):
                parts = full.split()
                if len(parts) >= 2 and parts[-1].lower() in ("jr.", "jr", "ii", "iii", "iv"):
                    return " ".join(parts[-2:])
                return parts[-1] if parts else full

            _top_lu["Lineup"] = _top_lu["Lineup"].apply(
                lambda s: " · ".join(_short_name(n) for n in s.split(" · "))
            )

            # Same blue-grey-gold percentile language as the tiles below and everywhere else
            # on the site, instead of a plain black-on-white export-style table.
            _LINEUP_TABLE_KEY_MAP = {
                "Net": "net_rtg", "Off Rtg": "ortg", "TS%": "ts", "3P%": "three_pct",
                "TOV%": "tov_rate", "Def Rtg": "drtg", "Opp TS%": "opp_ts",
                "Opp TOV%": "opp_tov_rate", "DReb%": "drb_pct",
            }

            def _lineup_table_style(col):
                key = _LINEUP_TABLE_KEY_MAP.get(col.name)
                if not key:
                    return [""] * len(col)
                styles = []
                for val in col:
                    pct = lineup_pct(key, val)
                    if pct is None:
                        styles.append("")
                        continue
                    bg, fg = pct_color(pct)
                    styles.append(f"background-color:{bg};color:{fg};font-weight:700;")
                return styles

            _styled_top_lu = _top_lu.style.apply(_lineup_table_style, subset=list(_LINEUP_TABLE_KEY_MAP.keys()))

            st.dataframe(
                _styled_top_lu,
                hide_index=True,
                use_container_width=True,
                height=460,
                column_config={
                    "Lineup":    st.column_config.TextColumn("Lineup"),
                    "Min":       st.column_config.NumberColumn("Min", format="%.0f"),
                    "Net":       st.column_config.NumberColumn("Net", format="%+.1f"),
                    "Off Rtg":   st.column_config.NumberColumn("Off Rtg", format="%.1f"),
                    "TS%":       st.column_config.NumberColumn("TS%", format="%.1f%%"),
                    "3P%":       st.column_config.NumberColumn("3P%", format="%.1f%%"),
                    "TOV%":      st.column_config.NumberColumn("TOV%", format="%.1f%%"),
                    "Def Rtg":   st.column_config.NumberColumn("Def Rtg", format="%.1f"),
                    "Opp TS%":   st.column_config.NumberColumn("Opp TS%", format="%.1f%%"),
                    "Opp TOV%":  st.column_config.NumberColumn("Opp TOV%", format="%.1f%%"),
                    "DReb%":     st.column_config.NumberColumn("DReb%", format="%.1f%%"),
                },
            )

    st.divider()

    # ==========================================
    # LINEUP ANALYZER
    # ==========================================
    with st.expander("Player On/Off Impact", expanded=False):
        st.caption("2025-26 season · team efficiency with each player on vs. off the court")

        @st.cache_data(ttl=3600)
        def load_on_off_segments():
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
                return df.dropna(subset=["p1","p2","p3","p4","p5"])
            except Exception:
                return pd.DataFrame()

        def _seg_stats(segs):
            if segs.empty:
                return None
            t_fga  = segs["team_fga"].sum()
            t_fg3a = segs["team_fg3a"].sum()
            t_fg3m = segs["team_fg3m"].sum()
            t_fta  = segs["team_fta"].sum()
            t_pts  = segs["team_pts"].sum()
            t_tov  = segs["team_tov"].sum()
            t_orb  = segs["team_orb"].sum()
            t_drb  = segs["team_drb"].sum()
            o_fga  = segs["opp_fga"].sum()
            o_fta  = segs["opp_fta"].sum()
            o_pts  = segs["opp_pts"].sum()
            o_tov  = segs["opp_tov"].sum()
            o_orb  = segs["opp_orb"].sum()
            mins   = segs["seconds"].sum() / 60
            t_poss = t_fga + 0.44*t_fta + t_tov - t_orb
            o_poss = o_fga + 0.44*o_fta + o_tov - o_orb
            poss   = (t_poss + o_poss) / 2 if (t_poss + o_poss) > 0 else 1
            ortg   = round(t_pts / poss * 100, 1)
            drtg   = round(o_pts / poss * 100, 1)
            ts_d   = 2 * (t_fga + 0.44 * t_fta)
            ts     = round(t_pts / ts_d * 100, 1) if ts_d > 0 else 0.0
            tov_r  = round(t_tov / t_poss * 100, 1) if t_poss > 0 else 0.0
            fg3_pct = round(t_fg3m / t_fg3a * 100, 1) if t_fg3a > 0 else 0.0
            fg3_r  = round(t_fg3a / t_fga * 100, 1)   if t_fga  > 0 else 0.0
            drb_pct = round(t_drb / (t_drb + o_orb) * 100, 1) if (t_drb + o_orb) > 0 else 0.0
            orb_pct = round(t_orb / (t_orb + (segs["opp_drb"].sum())) * 100, 1) if (t_orb + segs["opp_drb"].sum()) > 0 else 0.0
            return dict(mins=round(mins,1), ortg=ortg, drtg=drtg, net=round(ortg-drtg,1),
                        ts=ts, tov_r=tov_r, fg3_pct=fg3_pct, fg3_r=fg3_r,
                        drb_pct=drb_pct, orb_pct=orb_pct)

        _oo_segs = load_on_off_segments()

        if _oo_segs.empty:
            st.info("No lineup segment data found.")
        else:
            _all_players = sorted(pd.concat([
                _oo_segs["p1"],_oo_segs["p2"],_oo_segs["p3"],_oo_segs["p4"],_oo_segs["p5"]
            ]).dropna().unique().tolist())

            _selected_oo = st.multiselect(
                "Select players:",
                options=_all_players,
                default=[],
                placeholder="Search players...",
                label_visibility="collapsed",
            )

            if _selected_oo:
                # (label, key, higher_is_better, fmt, diff_range)
                # diff_range = (bad_end, good_end) → maps to blue→gold
                # Inverted range for lower-is-better stats
                STATS = [
                    ("ORtg",  "ortg",    True,  ".1f",  (-15, +15)),
                    ("DRtg",  "drtg",    False, ".1f",  (+15, -15)),
                    ("Net",   "net",     True,  "+.1f", (-20, +20)),
                    ("TS%",   "ts",      True,  ".1f",  (-8,  +8)),
                    ("TOV%",  "tov_r",   False, ".1f",  (+5,  -5)),
                    ("3P%",   "fg3_pct", True,  ".1f",  (-8,  +8)),
                    ("3PR",   "fg3_r",   True,  ".1f",  (-8,  +8)),
                    ("DReb%", "drb_pct", True,  ".1f",  (-10, +10)),
                    ("OReb%", "orb_pct", True,  ".1f",  (-10, +10)),
                ]

                def _diff_pct_abs(diff, bad_end, good_end):
                    span = good_end - bad_end
                    if span == 0:
                        return 50.0
                    return max(0.0, min(100.0, (diff - bad_end) / span * 100))

                def _player_display(name):
                    parts = name.split()
                    suffixes = {"jr.", "sr.", "ii", "iii", "iv"}
                    last_norm = parts[-1].lower().rstrip(".")
                    if len(parts) >= 3 and (last_norm + "." in suffixes or last_norm in suffixes):
                        return " ".join(parts[1:])
                    return parts[-1]

                def _build_card(s_on, s_off, title):
                    header_cells = "<td style='width:64px;'></td>"
                    for label, key, hib, fmt, drange in STATS:
                        header_cells += f"<th style='font-family:\"DM Mono\",monospace;font-size:12px;font-weight:800;letter-spacing:0.08em;color:#475569;text-align:center;padding:0 6px 10px;white-space:nowrap;'>{label}</th>"

                    on_cells = "<td style='font-family:\"DM Mono\",monospace;font-size:12px;font-weight:800;letter-spacing:0.06em;color:#2D68C4;padding:8px 10px 8px 0;'>ON</td>"
                    for label, key, hib, fmt, drange in STATS:
                        fmt_str = f"{{:{fmt}}}"
                        on_cells += f"<td style='font-family:\"DM Mono\",monospace;font-size:18px;font-weight:800;color:#2D68C4;text-align:center;padding:7px;'>{fmt_str.format(s_on[key])}</td>"

                    off_cells = "<td style='font-family:\"DM Mono\",monospace;font-size:12px;font-weight:800;letter-spacing:0.06em;color:#64748B;padding:8px 10px 8px 0;'>OFF</td>"
                    for label, key, hib, fmt, drange in STATS:
                        fmt_str = f"{{:{fmt}}}"
                        off_cells += f"<td style='font-family:\"DM Mono\",monospace;font-size:18px;font-weight:800;color:#475569;text-align:center;padding:7px;'>{fmt_str.format(s_off[key])}</td>"

                    diff_cells = "<td style='font-family:\"DM Mono\",monospace;font-size:12px;font-weight:800;letter-spacing:0.06em;color:#94A3B8;padding:8px 10px 8px 0;'>+/&minus;</td>"
                    for label, key, hib, fmt, drange in STATS:
                        diff = s_on[key] - s_off[key]
                        bg, fg = pct_color(_diff_pct_abs(diff, drange[0], drange[1]))
                        sign = "+" if diff >= 0 else ""
                        diff_cells += f"<td style='text-align:center;padding:6px;'><span style='background:{bg};color:{fg};font-family:\"DM Mono\",monospace;font-size:15px;font-weight:800;border-radius:5px;padding:4px 9px;display:inline-block;'>{sign}{diff:.1f}</span></td>"

                    return f"""
                    <div style="font-family:system-ui,sans-serif;background:#fff;border:1px solid #dde2ee;
                                border-radius:10px;padding:16px 18px 14px;margin-bottom:2px;">
                      <div style="display:flex;align-items:baseline;justify-content:space-between;margin-bottom:12px;">
                        <div style="font-size:19px;font-weight:800;color:#0F172A;">{title}</div>
                        <div style="font-family:'DM Mono',monospace;font-size:12px;color:#64748B;letter-spacing:0.04em;">
                          {s_on['mins']:.0f} MIN ON &nbsp;·&nbsp; {s_off['mins']:.0f} MIN OFF
                        </div>
                      </div>
                      <table style="width:100%;border-collapse:collapse;">
                        <thead><tr>{header_cells}</tr></thead>
                        <tbody>
                          <tr style="border-top:1px solid #f1f5f9;">{on_cells}</tr>
                          <tr style="border-top:1px solid #f1f5f9;">{off_cells}</tr>
                          <tr style="border-top:1px solid #e2e8f0;">{diff_cells}</tr>
                        </tbody>
                      </table>
                    </div>"""

                # Combination card: all selected players on the floor together
                def _combo_mask(segs, players):
                    return segs.apply(
                        lambda r: all(p in (r.p1, r.p2, r.p3, r.p4, r.p5) for p in players),
                        axis=1,
                    )

                combo_mask = _combo_mask(_oo_segs, _selected_oo)
                s_on  = _seg_stats(_oo_segs[combo_mask])
                s_off = _seg_stats(_oo_segs[~combo_mask])

                if not s_on or not s_off:
                    st.info("Not enough data for that combination.")
                else:
                    names = " + ".join(_player_display(p) for p in _selected_oo)
                    components.html(_build_card(s_on, s_off, names), height=185, scrolling=False)

    st.divider()

    # ---- ROSTER EDITOR (bottom) ----
    with st.expander("Edit Roster", expanded=False):
        st.caption(
            "**Position** must be one of PG / CG / SF / PF / C. "
            "**Depth** sets stacking order (1 = starter). **BT Name** must match exact BartTorvik spelling - leave blank for freshmen / walk-ons."
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
# TAB: HOME
# ==========================================

# Tab index map - must match the st.tabs order (0=Home, so cards start at 1)
_TAB_INDEX = {
    "Individual Player Stats": 1,
    "UCLA Roster": 2,
    "Print Out": 3,
    "Portal Discovery Engine": 4,
    "Front Office Target Board": 5,
    "Recruit Alignment Survey": 6,
    "Synergy Play Types": 7,
    "International Players": 8,
    "Player Evaluations": 9,
}

_HOME_CARDS = [
    {
        "title": "Individual Player Stats",
        "desc": "Full individual profile: advanced stats, shot chart, percentile bars, and comp finder.",
        "img": "static/card_player.jpg",
    },
    {
        "title": "UCLA Roster",
        "desc": "Team depth by position with advanced metrics and eligibility status.",
        "img": "static/card_depth.jpg",
    },
    {
        "title": "Front Office Target Board",
        "desc": "The Big Board: priority-ranked recruiting targets by position, with NIL and scouting notes.",
        "img": "static/card_targetboard.jpg",
    },
    {
        "title": "Portal Discovery Engine",
        "desc": "Search and filter transfer portal targets by position, metrics, and fit.",
        "img": "static/card_portal.jpg",
    },
    {
        "title": "Print Out",
        "desc": "Printable one-page player summary for coaching staff and recruiting meetings.",
        "img": "static/card_onepager.jpg",
    },
    {
        "title": "Recruit Alignment Survey",
        "desc": "Pre-recruiting staff evaluation form for transfer portal and high school targets.",
        "img": "static/card_survey.jpg",
    },
    {
        "title": "Synergy Play Types",
        "desc": "PnR, isolation, spot-up, and 6 more play type breakdowns with position-group percentiles.",
        "img": "static/card_synergy.jpg",
    },
    {
        "title": "International Players",
        "desc": "International scouting reports - browse by country and temperature, add new prospects.",
        "img": "static/card_international.jpg",
    },
    {
        "title": "Player Evaluations",
        "desc": "Search any player to see their Big Board status and every coach's evaluation on file.",
    },
]

# If a card was clicked last run, inject JS to switch to that tab index
_nav_to = st.query_params.get("nav")
if _nav_to is not None:
    try:
        _nav_idx = int(_nav_to)
        st.components.v1.html(f"""
<script>
(function() {{
    function clickTab() {{
        var tabs = window.parent.document.querySelectorAll('[data-baseweb="tab"]');
        if (tabs.length > {_nav_idx}) {{
            tabs[{_nav_idx}].click();
            var url = new URL(window.parent.location.href);
            url.searchParams.delete('nav');
            window.parent.history.replaceState(null, '', url.toString());
        }} else {{
            setTimeout(clickTab, 100);
        }}
    }}
    setTimeout(clickTab, 200);
}})();
</script>
""", height=0)
    except (ValueError, TypeError):
        pass

with tab_home:
    import os, base64

    def _b64_img(path):
        if not os.path.exists(path):
            return None
        ext = path.rsplit(".", 1)[-1].lower()
        mime = "image/jpeg" if ext in ("jpg","jpeg") else f"image/{ext}"
        b64 = base64.b64encode(open(path,"rb").read()).decode()
        return f"data:{mime};base64,{b64}"

    # Build card data with base64 images so the iframe can render them
    _card_data = []
    for card in _HOME_CARDS:
        _card_data.append({
            "title": card["title"],
            "desc":  card["desc"],
            "img":   _b64_img(card["img"]) if card.get("img") else None,
            "tab":   _TAB_INDEX[card["title"]],
        })

    # Hidden Streamlit buttons - one per card, triggered by JS card clicks
    # CSS injected into parent to hide them

    # Build the full card grid as a single HTML component
    import json as _json
    _cards_json = _json.dumps(_card_data)
    components.html(f"""
<style>
  body {{ margin:0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:transparent; }}
  .grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:18px; padding:4px 4px 20px; }}
  .card {{
    border-radius:12px; overflow:hidden; border:1.5px solid #e2e8f0;
    background:#fff; cursor:pointer;
    transition: box-shadow 0.18s, transform 0.18s, border-color 0.18s;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  }}
  .card:hover {{
    box-shadow: 0 8px 28px rgba(39,116,174,0.22);
    transform: translateY(-3px);
    border-color: #2D68C4;
  }}
  .card img {{ width:100%; height:190px; object-fit:cover; display:block; }}
  .placeholder {{
    width:100%; height:190px;
    background: linear-gradient(135deg,#2D68C4 0%,#1a5c8a 100%);
    display:flex; align-items:center; justify-content:center;
    color:rgba(255,255,255,0.18); font-size:1.8rem; font-weight:900;
  }}
  .body {{ padding:14px 16px 16px; }}
  .title {{ font-size:1.05rem; font-weight:800; color:#2D68C4; margin-bottom:5px; line-height:1.2; }}
  .desc  {{ font-size:0.82rem; color:#475569; line-height:1.4; }}
</style>
<div class="grid" id="grid"></div>
<script>
var cards = {_cards_json};
var grid  = document.getElementById('grid');
cards.forEach(function(c, i) {{
  var el = document.createElement('div');
  el.className = 'card';
  var imgStyle = (c.tab === 'UCLA Roster') ? "object-fit:contain;background:#2D68C4;" : "";
  el.innerHTML =
    (c.img
      ? "<img src='" + c.img + "' style='" + imgStyle + "'>"
      : "<div class='placeholder'>UCLA</div>") +
    "<div class='body'>" +
      "<div class='title'>" + c.title + "</div>" +
      "<div class='desc'>"  + c.desc  + "</div>" +
    "</div>";
  el.addEventListener('click', function() {{
    window.parent.postMessage({{type: 'nav_click', tab: c.tab}}, '*');
  }});
  grid.appendChild(el);
}});
</script>
""", height=740, scrolling=False)


def render_add_evaluation_form(current_player, key_prefix="card"):
    """Log a new evaluation for this player, plus a Position Group selector (auto-saves
    on change, independent of the note below) - the only remaining manual override for a
    player's Big Board position group now that Priority/Value Tag have been fully
    replaced by the Recruit Alignment Survey.
    """
    conn = sqlite3.connect('scouting_hub.db')
    _last_scout_row = conn.execute(
        "SELECT scout_name FROM player_evaluations WHERE player_name = ? ORDER BY id DESC LIMIT 1",
        (current_player,)
    ).fetchone()
    if _last_scout_row and _last_scout_row[0]:
        _default_scout = _last_scout_row[0]
    else:
        _nb_row = conn.execute(
            "SELECT scout_name FROM player_notes WHERE player_name = ?", (current_player,)
        ).fetchone()
        _default_scout = _nb_row[0] if _nb_row and _nb_row[0] else ""
    _pos_row = conn.execute(
        "SELECT position FROM player_notes WHERE player_name = ?", (current_player,)
    ).fetchone()
    conn.close()

    _p_match = df_all[df_all["PLAYER"] == current_player]
    _team_for_save = str(_p_match.iloc[0]["TEAM"]) if not _p_match.empty else ""
    _saved_pos = (_pos_row[0] if _pos_row and _pos_row[0] else None) or \
        infer_board_position(_p_match.iloc[0] if not _p_match.empty else None)

    def _save_position_group(_player=current_player, _team=_team_for_save, _sel_key=None):
        _conn = sqlite3.connect('scouting_hub.db')
        _conn.execute('''
                       INSERT INTO player_notes (player_name, team_name, position)
                       VALUES (?, ?, ?) ON CONFLICT(player_name) DO
                       UPDATE SET team_name=excluded.team_name, position=excluded.position
                       ''', (_player, _team, st.session_state.get(_sel_key)))
        _conn.commit()
        _conn.close()

    st.write("**Add Evaluation**")
    _eval_form_v = st.session_state.setdefault(f"eval_form_v_{current_player}", 0)
    _new_eval_scout = st.text_input(
        "Your name:", value=_default_scout,
        key=f"{key_prefix}_new_eval_scout_{current_player}_{_eval_form_v}",
    )
    _new_eval_date = st.date_input(
        "Date:", value=datetime.now(), key=f"{key_prefix}_new_eval_date_{current_player}_{_eval_form_v}"
    )
    _pos_key = f"{key_prefix}_new_eval_pos_{current_player}_{_eval_form_v}"
    st.selectbox(
        "Position Group:", BOARD_POSITIONS,
        index=BOARD_POSITIONS.index(_saved_pos) if _saved_pos in BOARD_POSITIONS else 0,
        key=_pos_key,
        on_change=_save_position_group, kwargs={"_sel_key": _pos_key},
        help="Auto-saves immediately - separate from the evaluation note below.",
    )
    _new_eval_note = st.text_area(
        "Background intel, character evaluation, or general notes:",
        value="", height=150, key=f"{key_prefix}_new_eval_note_{current_player}_{_eval_form_v}",
    )
    if st.button("Add Evaluation", key=f"{key_prefix}_add_eval_{current_player}_{_eval_form_v}"):
        if _new_eval_note.strip():
            _conn = sqlite3.connect('scouting_hub.db')
            _conn.execute(
                "INSERT INTO player_evaluations (player_name, scout_name, eval_date, note, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (current_player, _new_eval_scout, _new_eval_date.strftime("%Y-%m-%d"),
                 _new_eval_note.strip(), datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            _conn.commit()
            st.session_state[f"eval_form_v_{current_player}"] = _eval_form_v + 1
            _conn.close()
            st.success(f"Evaluation added for {current_player}.")
            st.rerun()
        else:
            st.warning("Write a note before adding it to the log.")


def render_player_notes_workspace(current_player, key_prefix="card"):
    """Representation/personnel info, the Recruit Alignment Survey summary, and the
    append-only evaluation log - everywhere one coach needs to look to
    see what every other coach thinks of a player, in one place. Shared between the
    bottom of the Player Card and the standalone Player Evaluations tab - both render
    every rerun regardless of which tab is visible, so key_prefix keeps their widget
    keys from colliding when the same player is active in both at once.
    """
    conn = sqlite3.connect('scouting_hub.db')
    conn.row_factory = sqlite3.Row
    _row = conn.execute(
        "SELECT priority_tier, position, role, value_tag, board_rank, team_name, "
        "agent, agency, rumored_nil, personal_val, photo_url, scout_name "
        "FROM player_notes WHERE player_name = ?", (current_player,)
    ).fetchone()
    _nb = dict(_row) if _row else {}
    player_evals = conn.execute(
        "SELECT id, scout_name, eval_date, note FROM player_evaluations "
        "WHERE player_name = ? ORDER BY id DESC", (current_player,)
    ).fetchall()
    _survey_row = conn.execute(
        "SELECT * FROM recruit_surveys WHERE player_name = ?", (current_player,)
    ).fetchone()
    conn.close()

    # ---- Notes: alignment survey, representation, evaluation log ----
    st.markdown("#### Notes")

    if _survey_row:
        _survey = dict(_survey_row)
        _survey_score = sum(int(_survey.get(k) or 0) for k, *_ in SURVEY_CATEGORIES)
        st.markdown(
            "<div style='padding:10px 14px;border-radius:8px;background:#fafbfc;border:1px solid #dde2ee;"
            "border-left:4px solid #2D68C4;margin:10px 0;'>"
            "<b>&#127919; Recruit Alignment Survey</b> &middot; "
            f"{_survey_score}/40 &middot; {_survey.get('recruit_bucket') or '-'} &middot; "
            f"{_survey.get('recruiting_priority') or '-'}"
            "<div style='font-size:11px;color:#6b7280;margin-top:4px;'>"
            f"Evaluator: {_survey.get('primary_evaluator') or '-'} &middot; {_survey.get('eval_date') or '-'}"
            "</div></div>",
            unsafe_allow_html=True,
        )
        with st.expander("Full survey responses"):
            for _key, _title, _q, _labels in SURVEY_CATEGORIES:
                st.write(f"**{_title}:** {_labels[int(_survey.get(_key) or 3) - 1]}")
            if _survey.get("market_value"):
                st.write(f"**Estimated Market Value:** {_survey['market_value']}")
            if _survey.get("best_info_source"):
                st.write(f"**Best information source:** {_survey['best_info_source']}")
            if _survey.get("best_influencer"):
                st.write(f"**Best influencer:** {_survey['best_influencer']}")
            if _survey.get("relationship_owner"):
                st.write(f"**Relationship owner:** {_survey['relationship_owner']}")
            if _survey.get("hidden_connections"):
                st.write(f"**Hidden connections:** {_survey['hidden_connections']}")
    else:
        st.caption("No Recruit Alignment Survey on file for this player.")
    if st.button("Open Alignment Survey", key=f"{key_prefix}_open_survey_{current_player}"):
        st.session_state.active_player = current_player
        st.session_state.go_to_tab = _TAB_INDEX["Recruit Alignment Survey"]
        st.rerun()

    with st.expander("Representation & Personnel Valuation", expanded=False):
        col_agent, col_agency, col_nil, col_val = st.columns(4)
        with col_agent:
            agent_input = st.text_input("Primary Agent:", value=_nb.get("agent") or "", key=f"{key_prefix}_rep_agent_{current_player}")
        with col_agency:
            agency_input = st.text_input("Agency:", value=_nb.get("agency") or "", key=f"{key_prefix}_rep_agency_{current_player}")
        with col_nil:
            nil_input = st.text_input("Rumored External NIL:", value=_nb.get("rumored_nil") or "", key=f"{key_prefix}_rep_nil_{current_player}")
        with col_val:
            val_input = st.text_input("Internal Staff Valuation:", value=_nb.get("personal_val") or "", key=f"{key_prefix}_rep_val_{current_player}")
        photo_input = st.text_input(
            "Headshot Image Link (optional manual override):",
            value=_nb.get("photo_url") or "", key=f"{key_prefix}_rep_photo_{current_player}",
        )
        if st.button("Save Representation Info", key=f"{key_prefix}_save_rep_{current_player}"):
            _conn = sqlite3.connect('scouting_hub.db')
            _conn.execute('''
                           INSERT INTO player_notes (player_name, agent, agency, rumored_nil, personal_val, photo_url)
                           VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(player_name) DO
                           UPDATE SET
                               agent=excluded.agent, agency=excluded.agency, rumored_nil=excluded.rumored_nil,
                               personal_val=excluded.personal_val,
                               photo_url=CASE WHEN excluded.photo_url != '' THEN excluded.photo_url ELSE player_notes.photo_url END
                           ''', (current_player, agent_input, agency_input, nil_input, val_input, photo_input))
            _conn.commit()
            _conn.close()
            st.success("Representation info saved.")
            st.rerun()

    st.write("**Evaluation Log**")
    st.caption("Every coach's read stays on the record — adding a new evaluation never overwrites someone else's.")
    if not player_evals:
        st.caption("No evaluations logged yet.")
    for _eval_id, _eval_scout, _eval_date, _eval_note in player_evals:
        _ev_head_col, _ev_del_col = st.columns([6, 1])
        with _ev_head_col:
            st.markdown(f"**{_eval_scout or 'Unknown scout'}** &nbsp;·&nbsp; {_eval_date or '-'}")
        st.write(_eval_note)
        with _ev_del_col:
            if st.button("Delete", key=f"{key_prefix}_del_eval_{current_player}_{_eval_id}"):
                _conn = sqlite3.connect('scouting_hub.db')
                _conn.execute("DELETE FROM player_evaluations WHERE id = ?", (_eval_id,))
                _conn.commit()
                _conn.close()
                st.rerun()
        st.divider()

    render_add_evaluation_form(current_player, key_prefix=key_prefix)


# ==========================================
# TAB: PLAYER CARD (Individual Profile + Advanced Card + Target Board link-up)
# ==========================================
with tab_card:
    st.subheader("Individual Player Stats")

    _card_opts = [None] + all_player_names
    # Once a keyed widget has rendered once, Streamlit uses its own stored value on
    # reruns and ignores `index=` - so an external update to active_player (e.g. a
    # row click on the Portal Discovery Engine) would otherwise get silently
    # overwritten back to whatever this selectbox last held. Sync the widget's own
    # state to match active_player before it renders so navigation actually sticks -
    # but only when active_player changed via some OTHER means since we last synced,
    # not when the change came from the user picking a new value in this selectbox
    # itself (that would stomp a fresh in-tab search right back to the old player).
    _card_external_nav = st.session_state.active_player != st.session_state.get("_card_last_synced")
    if _card_external_nav:
        if st.session_state.active_player in _card_opts:
            st.session_state["card_player_select"] = st.session_state.active_player
        st.session_state["_card_last_synced"] = st.session_state.active_player
    _card_search_col, _card_clear_col = st.columns([6, 1])
    with _card_search_col:
        _card_pick = st.selectbox(
            "Search player:",
            _card_opts,
            format_func=lambda x: "" if x is None else x,
            key="card_player_select",
            label_visibility="collapsed",
            placeholder="Type a name...",
        )
    with _card_clear_col:
        # The dropdown's own text field doesn't reliably clear on a highlighted-text
        # delete (a Streamlit/BaseWeb quirk, not something this app's Python code can
        # override) - this button is a guaranteed one-click reset instead. Streamlit
        # won't let a button callback write directly into an already-instantiated
        # widget's key, so this only touches active_player - the external-nav sync
        # block above (which runs before the selectbox on the next rerun) picks up
        # that active_player changed and resets card_player_select itself.
        if st.button("✕ Clear", key="card_clear_search"):
            st.session_state.active_player = None
            st.session_state.active_player_team = None
            st.rerun()
    if _card_pick:
        st.session_state.active_player = _card_pick
        if not _card_external_nav:
            # Only clear the team hint on a genuine user-driven pick in this box - an
            # external nav (Portal Discovery Engine, comp card, etc.) already set the
            # correct team above and this must not stomp it.
            st.session_state.active_player_team = None
        st.session_state["_card_last_synced"] = _card_pick

    current_player = st.session_state.active_player

    if current_player is None:
        st.markdown(
            "<div style='text-align:center;padding:80px 0;color:#94a3b8;font-size:1.1rem'>"
            "Search for a player above to view their card."
            "</div>",
            unsafe_allow_html=True
        )
    if current_player is not None:
        _p_matches = df_all[df_all["PLAYER"] == current_player]
        if len(_p_matches) > 1 and st.session_state.active_player_team:
            _p_team_match = _p_matches[_p_matches["TEAM"] == st.session_state.active_player_team]
            if not _p_team_match.empty:
                _p_matches = _p_team_match
        p_data = _p_matches.iloc[0]

        conn = sqlite3.connect('scouting_hub.db')
        cursor = conn.cursor()
        cursor.execute(
            "SELECT priority_tier, position, photo_url, value_tag FROM player_notes WHERE player_name = ?",
            (current_player,))
        db_row = cursor.fetchone()

        saved_tier      = db_row[0] if db_row and db_row[0] else "Mid Priority"
        saved_pos       = db_row[1] if db_row and db_row[1] else infer_board_position(p_data)
        saved_photo     = db_row[2] if db_row else ""
        saved_value_tag = db_row[3] if db_row and db_row[3] else "Properly Valued"

        if not saved_photo:
            _tid = str(p_data["team_espn_id"]) if "team_espn_id" in p_data.index and pd.notna(p_data["team_espn_id"]) else ""
            saved_photo = fetch_espn_headshot(current_player, _tid)
            if db_row and saved_photo:
                cursor.execute("UPDATE player_notes SET photo_url = ? WHERE player_name = ?", (saved_photo, current_player))
                conn.commit()

        # Most recent entry in the append-only evaluation log (see render_player_notes_workspace
        # further down) - just enough here to show a "last evaluation" date in the header.
        _latest_eval = cursor.execute(
            "SELECT eval_date FROM player_evaluations WHERE player_name = ? ORDER BY id DESC LIMIT 1",
            (current_player,)
        ).fetchone()
        saved_date = _latest_eval[0] if _latest_eval else "No previous evaluations logged"

        conn.close()

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

        # Determine position group for this player. Prefer, in order:
        # BartTorvik's own POS_TAG (real, granular scouting-style data - "Wing
        # F" correctly separates a 6'7" combo forward from an actual guard),
        # then player_positions (NOT a manual coach override - it's auto-
        # scraped from ESPN's roster API, which only stores a coarse G/F/C
        # letter and is exactly the kind of generic label that misclassifies
        # tweeners as "Guard"), then the ESPN bio position, then height as a
        # last resort - never silently default to Guard when a real signal
        # is available.
        _player_pos_group = "Guard"  # default
        try:
            _pg_conn = sqlite3.connect("scouting_hub.db")
            _pg_row = _pg_conn.execute(
                "SELECT position_group FROM player_positions WHERE player_name = ?", (current_player,)
            ).fetchone()
            _pg_conn.close()
            _pos_tag_bucket = POS_TAG_BUCKET.get(p_data.get("POS_TAG", "")) if hasattr(p_data, "get") else None
            if _pos_tag_bucket:
                _player_pos_group = _pos_tag_bucket
            elif _pg_row:
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
            else:
                _h_in = parse_height_inches(p_data.get("HEIGHT", "")) if hasattr(p_data, "get") else None
                if _h_in:
                    if _h_in >= 82:
                        _player_pos_group = "Big"
                    elif _h_in >= 78:
                        _player_pos_group = "Wing"
                    else:
                        _player_pos_group = "Guard"
        except Exception:
            pass

        _active_bm = _pos_benchmarks.get(_player_pos_group, {})
        # Display-only relabel - "Wing" stays the internal bucket key (used to
        # look up _pos_benchmarks above and everywhere else in the codebase),
        # but coaches read "Forward" more naturally than "Wing" on the card.
        _player_pos_label = "Forward" if _player_pos_group == "Wing" else _player_pos_group
        _BOX_LOWER = {"TOV_PCT"}
        _BT_LOWER  = {"TO"}

        def _fmt(val, dec=1):
            try:
                return f"{float(val):.{dec}f}" if val is not None and str(val) not in ("", "nan", "None") else "-"
            except Exception:
                return "-"

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
            if disp == "-":
                bg, fg = "#EAECF0", "#1A1A1A"
            val_str = f"{disp}{suffix}" if disp != "-" else "-"
            return (
                f"<div style='background:{bg};color:{fg};border-radius:6px;padding:5px 8px;"
                f"display:flex;flex-direction:column;min-width:70px'>"
                f"<span style='font-size:0.68rem;opacity:0.75'>{label}</span>"
                f"<span style='font-size:0.95rem;font-weight:700'>{val_str}</span>"
                f"</div>"
            )

        def _stat_row_colored(label, val, pct, suffix="", dec=1, accent="#2D68C4"):
            bg, bubble_fg = pct_color(pct)
            disp    = _fmt(val, dec)
            val_str = f"{disp}{suffix}" if disp != "-" else "-"
            if pct is not None:
                fill_w  = f"{pct:.1f}%"
                pct_num = f"{pct:.0f}"
                bubble = (
                    f"<div style='position:absolute;top:50%;left:{fill_w};transform:translate(-50%,-50%);background:{bg};"
                    f"color:{bubble_fg};font-size:0.62rem;font-weight:900;border-radius:50%;width:20px;height:20px;"
                    f"display:flex;align-items:center;justify-content:center;z-index:2;border:1.5px solid rgba(0,0,0,0.25)'>{pct_num}</div>"
                )
                fill = f"<div style='position:absolute;top:0;left:0;height:100%;width:{fill_w};background:{bg};border-radius:4px'></div>"
            else:
                fill   = ""
                bubble = ""
            label_fg = "#0F172A" if accent == "#F2A900" else "#FFFFFF"
            return (
                f"<div style='display:flex;align-items:center;margin-bottom:6px;gap:10px'>"
                f"<span style='display:inline-block;font-size:0.78rem;font-weight:900;letter-spacing:0.02em;"
                f"color:{label_fg};background:{accent};padding:4px 8px;border-radius:4px;min-width:64px;"
                f"text-align:center;flex-shrink:0'>{label}</span>"
                f"<div style='flex:1;position:relative;height:20px;border-radius:4px;overflow:visible;background:#e0e0e0'>"
                f"{fill}{bubble}"
                f"</div>"
                f"<span style='font-size:0.95rem;font-weight:900;color:#111;min-width:42px;text-align:right;flex-shrink:0'>{val_str}</span>"
                f"</div>"
            )

        def _cat_table(title, rows_html):
            return (
                f"<div style='margin-bottom:20px'>"
                f"<div style='font-size:1.05rem;font-weight:900;text-transform:uppercase;"
                f"letter-spacing:0.08em;margin-bottom:8px;color:#111;"
                f"border-bottom:2px solid #ddd;padding-bottom:4px'>{title}</div>"
                f"{''.join(rows_html)}"
                f"</div>"
            )

        def _divider_row():
            return "<div style='height:1px;background:#e8eaed;margin:14px 0 10px'></div>"

        def _shot_group(group_label, rows):
            """
            rows: list of (stat_label, val, pct, suffix)
            Group label sits as its own header pill above the FG%/Freq rows, instead of
            vertically centered beside them - centering it made it float in the gap between
            the two rows rather than clearly reading as "this is the Rim group."
            """
            def _bar_row(stat_label, val, pct, suffix=""):
                bg, bubble_fg = pct_color(pct)
                disp    = _fmt(val)
                val_str = f"{disp}{suffix}" if disp != "-" else "-"
                if pct is not None:
                    fill_w  = f"{pct:.1f}%"
                    pct_num = f"{pct:.0f}"
                    bubble = (
                        f"<div style='position:absolute;top:50%;left:{fill_w};transform:translate(-50%,-50%);background:{bg};"
                        f"color:{bubble_fg};font-size:0.62rem;font-weight:900;border-radius:50%;width:20px;height:20px;"
                        f"display:flex;align-items:center;justify-content:center;z-index:2;border:1.5px solid rgba(0,0,0,0.25)'>{pct_num}</div>"
                    )
                    fill = f"<div style='position:absolute;top:0;left:0;height:100%;width:{fill_w};background:{bg};border-radius:4px'></div>"
                else:
                    fill = bubble = ""
                return (
                    f"<div style='display:flex;align-items:center;margin-bottom:6px;gap:10px'>"
                    f"<span style='font-size:0.82rem;font-weight:800;color:#111;min-width:36px;text-align:right;flex-shrink:0'>{stat_label}</span>"
                    f"<div style='flex:1;position:relative;height:20px;border-radius:4px;overflow:visible;background:#e0e0e0'>"
                    f"{fill}{bubble}"
                    f"</div>"
                    f"<span style='font-size:0.95rem;font-weight:900;color:#111;min-width:42px;text-align:right;flex-shrink:0'>{val_str}</span>"
                    f"</div>"
                )
            bars = "".join(_bar_row(*r) for r in rows)
            return (
                f"<div style='margin-bottom:8px'>"
                f"<span style='display:inline-block;font-size:0.72rem;font-weight:900;letter-spacing:0.06em;"
                f"text-transform:uppercase;color:#fff;background:#2D68C4;padding:2px 10px;"
                f"border-radius:4px;margin-bottom:6px'>{group_label}</span>"
                f"<div>{bars}</div>"
                f"</div>"
            )

        col_img, col_info, col_action = st.columns([1, 3, 1])
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
            if _player_pos_group:
                bio_parts.append(_player_pos_label)
            if _display_class:
                bio_parts.append(_display_class)
            st.markdown("&nbsp;&nbsp;·&nbsp;&nbsp;".join(bio_parts))
            st.caption(f"Last evaluation: {saved_date}")

        with col_action:
            st.write("")
            if st.button("+ Add to Big Board", key=f"card_add_board_{current_player}", use_container_width=True):
                conn = sqlite3.connect('scouting_hub.db')
                cursor = conn.cursor()
                cursor.execute('''
                               INSERT INTO player_notes (player_name, team_name, position, priority_tier,
                                                         value_tag, eval_date)
                               VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(player_name) DO
                               UPDATE SET
                                   team_name=excluded.team_name, position=excluded.position,
                                   priority_tier=COALESCE(NULLIF(player_notes.priority_tier, ''), excluded.priority_tier),
                                   value_tag=COALESCE(NULLIF(player_notes.value_tag, ''), excluded.value_tag)
                               ''',
                               (current_player, p_data["TEAM"], saved_pos, saved_tier or "Mid Priority",
                                saved_value_tag or "Properly Valued", datetime.now().strftime("%Y-%m-%d")))
                conn.commit()
                conn.close()
                st.success(f"{current_player} added to the Front Office Target Board.")

        # Basic box score, right below the header - Season plus Conference/Non-Conference splits.
        _top50_row = None  # only ever set below when _hdr exists - the hero section further
        # down needs a defined name either way, since it runs whether or not _hdr is None.
        if _hdr is not None:
            def _row_num(v, d=1):
                try:
                    return f"{float(v):.{d}f}"
                except (TypeError, ValueError):
                    return "-"

            def _row_pct(v):
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    return "-"
                return f"{v:.1f}%" if v else "-"

            def _stats_table_row(row_label, r):
                if r is None:
                    return f"<tr><td>{row_label}</td>" + "<td>-</td>" * 12 + "</tr>"
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
                    f"<td>{_row_pct(r.get('TWO_P'))}</td>"
                    f"<td>{_row_pct(r.get('THREE_P'))}</td>"
                    f"<td>{_row_pct(r.get('EFG'))}</td>"
                    f"<td>{_row_pct(r.get('TS'))}</td>"
                    "</tr>"
                )

            # top50_row is used by build_combo_tags hero section below; set None since
            # we no longer load that split here (combo_tags handles None gracefully).
            _top50_row = None

            # USG%/AST%/OR%/DR% dropped from this table - they're already covered in
            # the Advanced Stats expander below. Fewer columns at the same table width
            # means each one gets more room, so bump padding/font-size up a notch too.
            _stats_table_style = (
                "<style>.card-stats-table{width:100%;border-collapse:separate;border-spacing:0;"
                "font-size:0.95rem;margin-top:10px;border:1px solid #E2E8F0;border-radius:8px;overflow:hidden;}"
                ".card-stats-table th{text-align:center;padding:12px 10px;color:#FFFFFF;font-size:0.74rem;"
                "font-weight:700;text-transform:uppercase;letter-spacing:0.05em;background:#2D68C4;}"
                ".card-stats-table td{text-align:center;padding:12px 10px;border-bottom:1px solid #F1F5F9;"
                "font-weight:600;color:#1B3E76;}"
                ".card-stats-table tr:last-child td{border-bottom:none;}"
                ".card-stats-table tr:nth-child(even) td{background:#F8FAFC;}"
                ".card-stats-table td:first-child{text-align:left;padding-left:14px;font-weight:800;color:#0F172A;}"
                "</style>"
                "<table class='card-stats-table'><thead><tr>"
                "<th></th><th>GP</th><th>MPG</th><th>PPG</th><th>RPG</th><th>APG</th><th>SPG</th><th>BPG</th>"
                "<th>FG%</th><th>2P%</th><th>3P%</th><th>EFG%</th><th>TS%</th>"
                "</tr></thead><tbody>"
            )

            # ── Four-row split table: Season / Quad 1 / Quad 1-2 / Conference ──
            # Season row uses _hdr (covers all players via game logs).
            # Quad/conf rows use cbb_player_agg (UCLA players only; dashes for others).
            _cbb_agg_all = load_cbb_player_agg()

            def _split_row_cbb(row_label, r):
                """Build a table row from a cbb_player_agg row (cumulative totals, divide by GP)."""
                if r is None:
                    return f"<tr><td>{row_label}</td>" + "<td>-</td>" * 16 + "</tr>"
                try:
                    gp = int(r.get("gp") or 0)
                except (TypeError, ValueError):
                    gp = 0
                if gp == 0:
                    return f"<tr><td>{row_label}</td>" + "<td>-</td>" * 16 + "</tr>"

                def _pg(col):
                    try:
                        return f"{float(r.get(col) or 0) / gp:.1f}"
                    except (TypeError, ValueError, ZeroDivisionError):
                        return "-"

                def _pf(col, scale=100):
                    try:
                        v = float(r.get(col))
                        return f"{v * scale:.1f}%"
                    except (TypeError, ValueError):
                        return "-"

                return (
                    f"<tr><td style='font-weight:700'>{row_label}</td>"
                    f"<td>{gp}</td>"
                    f"<td>{_pg('mins')}</td>"
                    f"<td>{_pg('pts')}</td>"
                    f"<td>{_pg('reb')}</td>"
                    f"<td>{_pg('ast')}</td>"
                    f"<td>{_pg('stl')}</td>"
                    f"<td>{_pg('blk')}</td>"
                    f"<td>{_pf('fg_pct')}</td>"
                    f"<td>{_pf('ts_pct')}</td>"
                    f"<td>{_pf('fg2_pct')}</td>"
                    f"<td>{_pf('fg3_pct')}</td>"
                    f"<td>{_pf('ft_pct')}</td>"
                    f"<td>{_pf('usage_pct')}</td>"
                    f"<td>{_pf('ast_pct')}</td>"
                    f"<td>{_pf('orb_pct')}</td>"
                    f"<td>{_pf('drb_pct')}</td>"
                    "</tr>"
                )

            def _get_cbb_row(scope):
                sdf = _cbb_agg_all[
                    (_cbb_agg_all["player_name"] == current_player) &
                    (_cbb_agg_all["scope"] == scope)
                ]
                return sdf.iloc[0].to_dict() if not sdf.empty else None

            # cbb_player_agg only covers UCLA players (that's what fetch_cbb_analytics.py
            # pulls) - everyone else (portal targets, opponents) keeps the plain
            # single-row Season table instead of a split table full of dashes.
            _cbb_season_row = _get_cbb_row("season")
            if _cbb_season_row is not None:
                _split_rows_html = (
                    _split_row_cbb("Season", _cbb_season_row)
                    + _split_row_cbb("Quad 1",     _get_cbb_row("quad1"))
                    + _split_row_cbb("Quad 1-2",   _get_cbb_row("quad12"))
                    + _split_row_cbb("Conference", _get_cbb_row("confAll"))
                )

                st.markdown(
                    "<style>.split-table{width:100%;border-collapse:separate;border-spacing:0;"
                    "font-size:0.83rem;margin-top:10px;border:1px solid #E2E8F0;border-radius:8px;overflow:hidden;}"
                    ".split-table th{text-align:center;padding:8px 5px;color:#fff;font-size:0.65rem;"
                    "font-weight:700;text-transform:uppercase;letter-spacing:0.05em;background:#2D68C4;}"
                    ".split-table td{text-align:center;padding:8px 5px;border-bottom:1px solid #F1F5F9;"
                    "font-weight:600;color:#1B3E76;}"
                    ".split-table tr:last-child td{border-bottom:none;}"
                    ".split-table tr:nth-child(even) td{background:#F8FAFC;}"
                    ".split-table td:first-child{text-align:left;padding-left:12px;font-weight:800;color:#0F172A;min-width:90px;}"
                    "</style>"
                    "<table class='split-table'><thead><tr>"
                    "<th></th><th>GP</th><th>MPG</th><th>PPG</th><th>RPG</th><th>APG</th>"
                    "<th>SPG</th><th>BPG</th><th>FG%</th><th>TS%</th>"
                    "<th>2P%</th><th>3P%</th><th>FT%</th><th>USG%</th><th>AST%</th><th>OR%</th><th>DR%</th>"
                    "</tr></thead><tbody>"
                    + _split_rows_html
                    + "</tbody></table>",
                    unsafe_allow_html=True,
                )
            else:
                # No CBB Analytics data (that's UCLA-only) - fall back to the same
                # Season / Conference / Non-Conf / vs Top 100 / vs Top 50 split
                # already used on the Print Out one-pager, computed from the same
                # box-score source, for whichever player is loaded. If a player's
                # own conference can't be resolved (e.g. no game logs at all),
                # falls back further to just the plain Season row.
                _card_conf_row = _card_nonconf_row = _card_top100_row = _card_top50_row = None
                try:
                    _card_conf_map = build_team_conf_map(df_all)
                    _card_own_conf = p_data["CONF"]
                    _card_in_conf_ids = tuple(sorted(
                        eid for eid, c in _card_conf_map.items() if c == _card_own_conf
                    ))
                    if _card_in_conf_ids:
                        _card_conf_box = load_consistent_boxscore_stats(conf_ids=_card_in_conf_ids)
                        _ccr = _card_conf_box[_card_conf_box["PLAYER"] == current_player]
                        _card_conf_row = _ccr.iloc[0] if not _ccr.empty else None

                        _card_nonconf_box = load_consistent_boxscore_stats(
                            conf_ids=_card_in_conf_ids, exclude_conf_ids=True)
                        _cncr = _card_nonconf_box[_card_nonconf_box["PLAYER"] == current_player]
                        _card_nonconf_row = _cncr.iloc[0] if not _cncr.empty else None

                    _card_top100_box = load_consistent_boxscore_stats(max_opp_rank=100)
                    _c100r = _card_top100_box[_card_top100_box["PLAYER"] == current_player]
                    _card_top100_row = _c100r.iloc[0] if not _c100r.empty else None

                    _card_top50_box = load_consistent_boxscore_stats(max_opp_rank=50)
                    _c50r = _card_top50_box[_card_top50_box["PLAYER"] == current_player]
                    _card_top50_row = _c50r.iloc[0] if not _c50r.empty else None
                except Exception:
                    pass

                if _card_conf_row is not None or _card_nonconf_row is not None:
                    st.markdown(
                        _stats_table_style
                        + _stats_table_row("Season", _hdr)
                        + _stats_table_row("Conference", _card_conf_row)
                        + _stats_table_row("Non-Conf", _card_nonconf_row)
                        + _stats_table_row("vs Top 100", _card_top100_row)
                        + _stats_table_row("vs Top 50", _card_top50_row)
                        + "</tbody></table>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        _stats_table_style
                        + _stats_table_row("Season", _hdr)
                        + "</tbody></table>",
                        unsafe_allow_html=True,
                    )

        # ── HERO: the one number and the auto-generated strengths a coach sees first,
        # after the main stat line and splits. PPG because it's the one stat every coach
        # already reads fluently; the percentile badge and skill tags give it context fast.
        _hero_ppg = _hdr.get("PPG") if _hdr is not None else None
        _hero_pct = national_pct("PPG", _hero_ppg, _active_bm) if _hero_ppg is not None else None
        _hero_bg, _hero_fg = pct_color(_hero_pct)
        # Fold real shot-chart zone frequency (rim/mid/three) into the tag-generation
        # input so shot-selection tags (3PT Specialist, Rim Attacker, ...) are eligible
        # alongside the box-stat tags - p_data alone doesn't carry zone columns.
        _hero_tag_stats = dict(p_data)
        _hero_tag_stats.update(get_player_shot_zone_dict(current_player, p_data.get("TEAM")))
        _hero_tags = build_auto_skill_tags(_hero_tag_stats, _active_bm, top_n=4, threshold=80.0)
        for _vt in build_volume_tags(_hdr):
            if _vt not in _hero_tags:
                _hero_tags.append(_vt)
        _hero_recent_form = load_recent_form(current_player)
        for _ct in build_combo_tags(
            _hero_tag_stats, _active_bm, _player_pos_group,
            box_row=_hdr, top50_row=_top50_row, recent_form=_hero_recent_form,
            pos_benchmarks=_pos_benchmarks,
        ):
            if _ct not in _hero_tags:
                _hero_tags.append(_ct)
        for _st in build_synergy_archetype_tags(current_player):
            if _st not in _hero_tags:
                _hero_tags.append(_st)
        try:
            _hero_ppg_disp = f"{float(_hero_ppg):.1f}"
        except (TypeError, ValueError):
            _hero_ppg_disp = "-"
        _hero_pct_str = (
            f"{ordinal(_hero_pct)} percentile scorer vs. P5 {_player_pos_label}s"
            if _hero_pct is not None else "Points per game"
        )
        if _hero_tags:
            _hero_tags_html = "".join(
                f"<span style='background:rgba(255,255,255,0.22);border:1px solid rgba(255,255,255,0.4);"
                f"color:{_hero_fg};padding:5px 12px;border-radius:20px;font-size:0.78rem;font-weight:800;"
                f"margin:2px 6px 2px 0;display:inline-block;'>{t}</span>"
                for t in _hero_tags
            )
        else:
            _hero_tags_html = (
                f"<span style='color:{_hero_fg};opacity:0.8;font-size:0.85rem;'>"
                f"No standout percentile stats yet this season.</span>"
            )
        st.markdown(
            f"<div style='background:{_hero_bg};border-radius:14px;padding:18px 24px;"
            f"margin:14px 0 18px;display:flex;align-items:center;gap:26px;flex-wrap:wrap;'>"
            f"<div style='flex-shrink:0;'>"
            f"<div style='font-size:2.6rem;font-weight:900;color:{_hero_fg};line-height:1;'>"
            f"{_hero_ppg_disp}<span style='font-size:1.1rem;font-weight:700;opacity:0.8;'> PPG</span></div>"
            f"<div style='font-size:0.78rem;font-weight:700;color:{_hero_fg};opacity:0.9;margin-top:4px;'>"
            f"{_hero_pct_str}</div>"
            f"</div>"
            f"<div style='flex:1;min-width:200px;'>{_hero_tags_html}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # ── Recruit Alignment Survey tags (Max Feldman's pre-recruiting evaluation) ──
        conn = sqlite3.connect('scouting_hub.db')
        conn.row_factory = sqlite3.Row
        _survey_row = conn.execute(
            "SELECT * FROM recruit_surveys WHERE player_name = ?", (current_player,)
        ).fetchone()
        conn.close()
        if _survey_row:
            _survey = dict(_survey_row)
            _survey_score = sum(int(_survey.get(k) or 0) for k, *_ in SURVEY_CATEGORIES)
            _survey_priority = _survey.get("recruiting_priority") or "-"
            _survey_bucket = _survey.get("recruit_bucket") or "-"
            _priority_color = SURVEY_PRIORITY_COLORS.get(_survey_priority, "#64748B")

            # Just the three headline calls a coach needs at a glance - bucket, overall
            # score, recruiting priority - not the full 8-category breakdown (that lives
            # in the Notes section's "Full survey responses" for whoever wants to dig in).
            st.markdown(
                "<div style=\"margin:12px 0;padding:12px 14px;border:1px solid #dde2ee;"
                "border-left:4px solid #2D68C4;border-radius:8px;background:#fafbfc;\">"
                "<div style=\"font-size:12px;font-weight:800;color:#111827;text-transform:uppercase;"
                "letter-spacing:.04em;margin-bottom:8px;\">&#127919; Recruit Alignment Survey</div>"
                "<div style=\"display:flex;gap:10px;flex-wrap:wrap;\">"
                f"<span style=\"background:{_priority_color}1A;color:{_priority_color};border:1px solid {_priority_color}55;"
                f"padding:4px 10px;border-radius:5px;font-size:11px;font-weight:700;\">{_survey_score}/40 Alignment Score</span>"
                f"<span style=\"background:{_priority_color}1A;color:{_priority_color};border:1px solid {_priority_color}55;"
                f"padding:4px 10px;border-radius:5px;font-size:11px;font-weight:700;\">{_survey_priority}</span>"
                f"<span style=\"background:#eef3fb;color:#2D68C4;border:1px solid #cfe0f5;"
                f"padding:4px 10px;border-radius:5px;font-size:11px;font-weight:700;\">{_survey_bucket}</span>"
                "</div>"
                "</div>",
                unsafe_allow_html=True,
            )

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

            # Load PBP zone data early so shot-type values are available for the stat cards
            _pbp_all_early = load_cbb_pbp_zones()
            _pbp_bm = build_pbp_benchmarks()
            _pbp_pe = _pbp_all_early[
                (_pbp_all_early["player_name"] == current_player) &
                (_pbp_all_early["scope"] == "season")
            ] if not _pbp_all_early.empty else pd.DataFrame()
            if not _pbp_pe.empty:
                if len(_pbp_pe) > 1 and "fga" in _pbp_pe.columns:
                    _pbp_pe = _pbp_pe.sort_values("fga", ascending=False)
                _pbp_re = _pbp_pe.iloc[0]
                def _pval(col):
                    try:
                        v = _pbp_re.get(col)
                        return float(v) if v is not None and str(v) not in ("", "nan", "None") else None
                    except (TypeError, ValueError):
                        return None
                def _pbp_pct(col):
                    v = _pval(col)
                    vals = _pbp_bm.get(col)
                    if v is None or not vals:
                        return None
                    return get_pct(v, vals)
                _sc_rim_pct  = (_pval("atr2_fg_pct")   or 0) * 100
                _sc_rim_freq = (_pval("atr2_fga_freq")  or 0) * 100
                _sc_mid_pct  = (_pval("mid2_fg_pct")    or 0) * 100
                _sc_mid_freq = (_pval("mid2_fga_freq")  or 0) * 100
                _sc_3p_freq  = (_pval("fga3_rate")      or 0) * 100
                _sc_ft_pct   = (_pval("ft_pct")         or 0) * 100
            else:
                _pval = lambda col: None
                _pbp_pct = lambda col: None
                _sc_rim_pct = _sc_rim_freq = _sc_mid_pct = _sc_mid_freq = _sc_3p_freq = _sc_ft_pct = None

            eff_html = _cat_table("Efficiency", [
                _stat_row_colored("ORTG",  _bt.get("ORTG"),  _bt_pct("ORTG",  _bt.get("ORTG"))),
                _stat_row_colored("USG%",  _hdr.get("USG"),  _box_pct("USG",  _hdr.get("USG")),  "%"),
                _stat_row_colored("TS%",   _hdr.get("TS"),   _box_pct("TS",   _hdr.get("TS")),   "%"),
                _stat_row_colored("OBPM",  p_data.get("OBPM"), _bt_pct("OBPM", p_data.get("OBPM")), "", 1),
            ])

            # RAPM/WARP from cbb_player_agg (UCLA players only; dashes otherwise)
            _cbb_ir = _cbb_agg_all[
                (_cbb_agg_all["player_name"] == current_player) &
                (_cbb_agg_all["scope"] == "season")
            ]
            _cbb_impact = _cbb_ir.iloc[0].to_dict() if not _cbb_ir.empty else {}

            def _rapm_pct(val, lo=-5, hi=5):
                try:
                    return max(0.0, min(100.0, (float(val) - lo) / (hi - lo) * 100))
                except (TypeError, ValueError):
                    return None

            imp_html = _cat_table("Impact", [
                _stat_row_colored("RAPM",  _cbb_impact.get("rapm"),  _rapm_pct(_cbb_impact.get("rapm")), accent="#1B3E76"),
                _stat_row_colored("oRAPM", _cbb_impact.get("orapm"), _rapm_pct(_cbb_impact.get("orapm")), accent="#1B3E76"),
                _stat_row_colored("dRAPM", _cbb_impact.get("drapm"), _rapm_pct(_cbb_impact.get("drapm")), accent="#1B3E76"),
                _stat_row_colored("BPM",   p_data.get("BPM"),        _box_pct("BPM",  p_data.get("BPM")),  "", 1, accent="#1B3E76"),
            ])

            play_html = _cat_table("Playmaking", [
                _stat_row_colored("AST%",   _hdr.get("AST_PCT"), _box_pct("AST_PCT", _hdr.get("AST_PCT")), "%", accent="#F2A900"),
                _stat_row_colored("TOV%",   _hdr.get("TOV_PCT"), _box_pct("TOV_PCT", _hdr.get("TOV_PCT")), "%", accent="#F2A900"),
                _stat_row_colored("AST/TO", _hdr.get("AST_TO"),  _box_pct("AST_TO",  _hdr.get("AST_TO")),  "", 2, accent="#F2A900"),
                _stat_row_colored("USG%",   _hdr.get("USG"),     _box_pct("USG",     _hdr.get("USG")),     "%", accent="#F2A900"),
            ])

            _ft_pct_val = _sc_ft_pct if _sc_ft_pct is not None else _hdr.get("FT_PCT")
            _ft_pct_col = _pbp_pct("ft_pct") or _box_pct("FT_PCT", _hdr.get("FT_PCT"))
            shoot_html = _cat_table("Shot Types", [
                _shot_group("Rim", [
                    ("FG%",  _sc_rim_pct,         _pbp_pct("atr2_fg_pct"),                   "%"),
                    ("Freq", _sc_rim_freq,         _pbp_pct("atr2_fga_freq"),                 "%"),
                ]),
                _divider_row(),
                _shot_group("Mid", [
                    ("FG%",  _sc_mid_pct,          _pbp_pct("mid2_fg_pct"),                   "%"),
                    ("Freq", _sc_mid_freq,          _pbp_pct("mid2_fga_freq"),                 "%"),
                ]),
                _divider_row(),
                _shot_group("3PT", [
                    ("FG%",  _hdr.get("THREE_P"),  _box_pct("THREE_P", _hdr.get("THREE_P")), "%"),
                    ("Freq", _sc_3p_freq,           _pbp_pct("fga3_rate"),                    "%"),
                ]),
                _divider_row(),
                _shot_group("FT", [
                    ("FT%",  _ft_pct_val,           _ft_pct_col,                              "%"),
                    ("Freq", _hdr.get("FTR"),       _box_pct("FTR", _hdr.get("FTR")),        "%"),
                ]),
            ])

            reb_html = _cat_table("Rebounding", [
                _stat_row_colored("OREB%", _hdr.get("OR_PCT"), _box_pct("OR_PCT", _hdr.get("OR_PCT")), "%", accent="#B8860B"),
                _stat_row_colored("DREB%", _hdr.get("DR_PCT"), _box_pct("DR_PCT", _hdr.get("DR_PCT")), "%", accent="#B8860B"),
                _stat_row_colored("RPG",   _hdr.get("RPG"),    _box_pct("RPG",    _hdr.get("RPG")), accent="#B8860B"),
            ])

            def_html = _cat_table("Defense", [
                _stat_row_colored("STL%",  _hdr.get("STL_PCT"), _box_pct("STL_PCT", _hdr.get("STL_PCT")), "%", accent="#334155"),
                _stat_row_colored("BLK%",  _hdr.get("BLK_PCT"), _box_pct("BLK_PCT", _hdr.get("BLK_PCT")), "%", accent="#334155"),
                _stat_row_colored("DBPM",  _bt.get("DBPM"),     _bt_pct("DBPM",     _bt.get("DBPM")), accent="#334155"),
                _stat_row_colored("SPG",   _hdr.get("SPG"),     _box_pct("SPG",     _hdr.get("SPG")), accent="#334155"),
                _stat_row_colored("BPG",   _hdr.get("BPG"),     _box_pct("BPG",     _hdr.get("BPG")), accent="#334155"),
            ])

            with st.expander("Advanced Stats (efficiency, impact, playmaking, shooting, rebounding, defense)"):
                st.caption(f"Percentiles vs. P5 {_player_pos_label}s")
                col_left, col_right = st.columns(2)
                with col_left:
                    st.markdown(eff_html + def_html + play_html, unsafe_allow_html=True)
                with col_right:
                    st.markdown(reb_html + shoot_html + imp_html, unsafe_allow_html=True)

        curated_player = next((p for p in PORTAL_PLAYERS if p["name"] == current_player), None)

        if not _gl_ready:
            st.info("Run `python3 build_game_logs.py` to enable the shot chart.")
        else:
            _pbox = load_consistent_boxscore_stats()
            _pbox = _pbox[_pbox["PLAYER"] == current_player]
            if len(_pbox) > 1:
                _bt_team = p_data["TEAM"]
                _team_match = _pbox[_pbox["TEAM"].str.contains(_bt_team, case=False, na=False)]
                if not _team_match.empty:
                    _pbox = _team_match

            # Shot chart section - use matched team_espn_id to avoid name collisions
            _team_id = _pbox.iloc[0]["team_espn_id"] if not _pbox.empty and "team_espn_id" in _pbox.columns else None
            _shots = load_player_shots(current_player, _team_id)
            if not _shots.empty:
                st.write("**Shot Chart**")
                _fig = draw_shot_chart(_shots, title=current_player)
                col_chart, col_gap = st.columns([3, 2])
                with col_chart:
                    st.pyplot(_fig, use_container_width=True)
                plt.close(_fig)

            # ── Shot Zone Court Diagram ──────────────────────────────────────
            st.markdown("**Shot Zone Profile**")
            _pbp_all = load_cbb_pbp_zones()
            _pbp_player = _pbp_all[
                (_pbp_all["player_name"] == current_player) &
                (_pbp_all["scope"] == "season")
            ] if not _pbp_all.empty else pd.DataFrame()
            if not _pbp_player.empty:
                # If multiple rows, take highest fga
                if len(_pbp_player) > 1 and "fga" in _pbp_player.columns:
                    _pbp_player = _pbp_player.sort_values("fga", ascending=False)
                _pbp_r = _pbp_player.iloc[0]
                def _zone_val(col, default=0.0):
                    try:
                        return float(_pbp_r.get(col) or default)
                    except (TypeError, ValueError):
                        return default

                _atr_pct    = _zone_val("atr2_fg_pct")
                _atr_m      = int(_zone_val("atr2_fgm"))
                _atr_a      = int(_zone_val("atr2_fga"))
                _paint_pct  = _zone_val("paint2_fg_pct")
                _paint_m    = int(_zone_val("paint2_fgm"))
                _paint_a    = int(_zone_val("paint2_fga"))
                _mid_pct    = _zone_val("mid2_fg_pct")
                _mid_m      = int(_zone_val("mid2_fgm"))
                _mid_a      = int(_zone_val("mid2_fga"))
                _c3l_pct    = _zone_val("c3_fg_pct")
                _c3l_m      = int(_zone_val("c3_fgm"))
                _c3l_a      = int(_zone_val("c3_fga"))
                _atb_pct    = _zone_val("atb3_fg_pct")
                _atb_m      = int(_zone_val("atb3_fgm"))
                _atb_a      = int(_zone_val("atb3_fga"))

                # Back to the wedge-court matplotlib style (draw_shot_zone_profile) instead
                # of the rectangular SVG diagram - direct feedback that the rectangle
                # version looked worse than what this used to be, plus bigger/bolder text.
                _zone_agg = {
                    "rim":     {"pct": _atr_pct * 100,   "made": _atr_m,   "total": _atr_a},
                    "paint":   {"pct": _paint_pct * 100, "made": _paint_m, "total": _paint_a},
                    "mid":     {"pct": _mid_pct * 100,   "made": _mid_m,   "total": _mid_a},
                    "corner3": {"pct": _c3l_pct * 100,   "made": _c3l_m,   "total": _c3l_a},
                    "atb3":    {"pct": _atb_pct * 100,   "made": _atb_m,   "total": _atb_a},
                }
                _zfig = draw_shot_zone_profile(_zone_agg, title=current_player)
                _zcol, _zgap = st.columns([2, 3])
                with _zcol:
                    st.pyplot(_zfig, use_container_width=True)
                plt.close(_zfig)
            else:
                st.caption("No zone data available for this player.")

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
                                           horizontal=True, key="comp_bucket_radio",
                                           format_func=lambda v: "Forward" if v == "Wing" else v)

                top_matches, dominant_cat = find_stat_comps(
                    current_player, df_all, card_benchmarks, n=comp_n, bucket_override=comp_bucket
                )

                _comp_bucket_label = "Forward" if comp_bucket == "Wing" else comp_bucket
                boost_note = f" boosted toward this player's real-stat strength: **{dominant_cat}**" if dominant_cat else ""
                st.write(f"**Top {len(top_matches)} comps from {len(df_all):,} current-season players** "
                         f"- height ±5in, weighted by **{_comp_bucket_label}** profile{boost_note}, "
                         f"real KenPom team strength nudges the ranking, shot-selection profile and "
                         f"zone FG% (rim/mid/three) also weighted in where shot-chart data exists, and real "
                         f"Synergy play-type mix (spot-up, isolation, post-up, PnR, etc.) weighted in where "
                         f"both players have one loaded.")

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

                _synergy_profiles_ui = build_synergy_playtype_profiles()
                _target_playtype_mix = _synergy_profiles_ui.get(current_player)
                if _target_playtype_mix:
                    _top_pt_mix = sorted(_target_playtype_mix.items(), key=lambda kv: kv[1], reverse=True)[:3]
                    _pt_mix_str = " · ".join(
                        f"{_PLAYTYPE_LABELS.get(pt, pt)} {pct * 100:.0f}%" for pt, pct in _top_pt_mix
                    )
                    st.caption(f"**{current_player}'s play-type mix (Synergy):** {_pt_mix_str} of possessions")

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
                    pct_txt = f"({ordinal(pct)})" if pct is not None else ""
                    val_txt = fmt(value, decimals, suffix) if value is not None else "-"
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

                        # Basic box score - plain, no percentile, easy to scan at a glance.
                        basic_row_html = (
                            "<div style=\"display:flex;border:1px solid #e5e7eb;border-radius:5px;overflow:hidden;margin-bottom:6px;\">"
                            + _plain_tile("PPG", fmt(_stat_val(match_data, "PPG"), 1))
                            + _plain_tile("RPG", fmt(_stat_val(match_data, "RPG"), 1))
                            + _plain_tile("APG", fmt(_stat_val(match_data, "APG"), 1)).replace("border-right:1px solid #e5e7eb;", "")
                            + "</div>"
                        )

                        # Advanced stats - percentile-colored, same visual language as the Player Card.
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

                        # "Why matched" callout - the specific stats behind this player's dominant-category
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

                        # Candidate's real Synergy play-type mix, when loaded - so a coach can
                        # see *why* the mix similarity term (if any) pushed this player up,
                        # not just trust a black-box score.
                        playtype_row_html = ""
                        _cand_playtype_mix = _synergy_profiles_ui.get(c_name)
                        if _cand_playtype_mix:
                            _top_cand_actions = sorted(
                                _cand_playtype_mix.items(), key=lambda kv: kv[1], reverse=True
                            )[:3]
                            action_tiles = "".join(
                                _plain_tile(_PLAYTYPE_LABELS.get(pt, pt), f"{share * 100:.0f}%")
                                for pt, share in _top_cand_actions
                            )
                            idx = action_tiles.rfind("border-right:1px solid #e5e7eb;")
                            if idx != -1:
                                action_tiles = action_tiles[:idx] + action_tiles[idx + len("border-right:1px solid #e5e7eb;"):]
                            playtype_row_html = (
                                "<div style=\"margin-bottom:6px;\">"
                                "<div style=\"font-size:8px;font-weight:700;color:#6b7280;text-transform:uppercase;"
                                "letter-spacing:.04em;margin-bottom:4px;\">Play-type mix (Synergy)</div>"
                                "<div style=\"display:flex;border:1px solid #e5e7eb;border-radius:5px;overflow:hidden;\">"
                                + action_tiles + "</div></div>"
                            )

                        html = (
                            "<div style=\"background:#ffffff;border:1px solid #dde2ee;border-left:4px solid #2D68C4;border-radius:8px;padding:12px 14px;margin-bottom:8px;\">"
                            "<div style=\"display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px;\">"
                            "<div>"
                            "<div style=\"font-size:14px;font-weight:700;color:#111827;\">" + c_name + "</div>"
                            "<div style=\"font-size:9px;color:#6b7280;margin-top:2px;\">" + c_ht
                            + (" &middot; " + c_class if c_class else "") + " &middot; " + c_team + " (" + c_conf + ")</div>"
                            "</div>"
                            "<span style=\"font-size:8px;font-weight:600;padding:4px 8px;border-radius:3px;background:#e8f1f9;color:#2D68C4;border:1px solid #b8d3ec;\">" + str(pct) + "% match</span>"
                            "</div>"
                            + basic_row_html
                            + adv_row_html
                            + why_html
                            + zone_row_html
                            + playtype_row_html +
                            "<div style=\"height:3px;background:#e5e7eb;border-radius:2px;\">"
                            "<div style=\"height:100%;width:" + str(pct) + "%;background:#2D68C4;border-radius:2px;\"></div>"
                            "</div>"
                            "</div>"
                        )
                        st.markdown(html, unsafe_allow_html=True)
                        if st.button(f"↗ Open {c_name}'s Player Card", key=f"comp_open_{current_player}_{_comp_idx}_{c_name}"):
                            st.session_state.active_player = c_name
                            st.session_state.active_player_team = c_team
                            st.session_state.go_to_profile = True
                            st.rerun()

        st.divider()

        render_player_notes_workspace(current_player)


    # ==========================================
    # TAB: ONE PAGER (PRINTABLE PLAYER SHEET)
# ==========================================
with tab_onepager:
    st.subheader("Print Out")

    _op_opts = [None] + all_player_names
    # Same fix as the Player Card select, and follows the same shared active_player
    # (not a separate "op_player" that only this box ever wrote - that meant once you
    # touched this search once, it permanently ignored every other nav in the app,
    # including a fresh search on the Player Card tab). Sync only when active_player
    # changed via some OTHER means since we last synced, not from picking a value in
    # this selectbox itself.
    _op_external_nav = st.session_state.active_player != st.session_state.get("_op_last_synced")
    if _op_external_nav:
        if st.session_state.active_player in _op_opts:
            st.session_state["onepager_player_select"] = st.session_state.active_player
        st.session_state["_op_last_synced"] = st.session_state.active_player
    _op_pick = st.selectbox(
        "Search player:",
        _op_opts,
        format_func=lambda x: "" if x is None else x,
        key="onepager_player_select",
        label_visibility="collapsed",
        placeholder="Type a name...",
    )
    if _op_pick:
        st.session_state.active_player = _op_pick
        if not _op_external_nav:
            st.session_state.active_player_team = None
        st.session_state["_op_last_synced"] = _op_pick

    op_player = st.session_state.active_player
    if op_player is None:
        st.info("Search for a player above to generate a one pager.")
    if op_player is not None:
        op_match = df_all[df_all["PLAYER"] == op_player]
        op_stats = op_match.iloc[0] if not op_match.empty else None

        conn = sqlite3.connect('scouting_hub.db')
        cursor = conn.cursor()
        cursor.execute(
            "SELECT team_name, position, agent, photo_url, notes, scout_name, "
            "priority_tier, role, value_tag, onepager_notes "
            "FROM player_notes WHERE player_name = ?", (op_player,)
        )
        op_note_row = cursor.fetchone()
        op_roster_row = cursor.execute(
            "SELECT position, height, class_yr FROM roster WHERE bt_name = ? OR player_name = ?",
            (op_player, op_player)
        ).fetchone()
        # Most recent entry in the evaluation log (append-only - see Player Card),
        # not the old single-note field that used to get silently overwritten.
        op_latest_eval = cursor.execute(
            "SELECT scout_name, note FROM player_evaluations WHERE player_name = ? "
            "ORDER BY id DESC LIMIT 1", (op_player,)
        ).fetchone()
        conn.close()

        op_team = (
            (op_note_row[0] if op_note_row and op_note_row[0] else None)
            or (op_stats["TEAM"] if op_stats is not None else None)
            or "-"
        )
        op_pos = (
            (op_roster_row[0] if op_roster_row and op_roster_row[0] else None)
            or (op_note_row[1] if op_note_row and op_note_row[1] else None)
            or "-"
        )
        op_height = (
            (op_roster_row[1] if op_roster_row and op_roster_row[1] else None)
            or (op_stats["HEIGHT"] if op_stats is not None else None)
            or "-"
        )
        op_class = (
            (op_roster_row[2] if op_roster_row and op_roster_row[2] else None)
            or (op_stats["CLASS"] if op_stats is not None else None)
            or "-"
        )
        op_agent = (op_note_row[2] if op_note_row and op_note_row[2] else None) or "-"
        op_scout = (op_latest_eval[0] if op_latest_eval and op_latest_eval[0] else "")
        op_notes_raw = (op_latest_eval[1] if op_latest_eval and op_latest_eval[1] else "").strip()
        op_priority = (op_note_row[6] if op_note_row and op_note_row[6] else None) or "-"
        op_role_text = (op_note_row[7] if op_note_row and op_note_row[7] else None) or "-"
        op_value_tag = (op_note_row[8] if op_note_row and op_note_row[8] else None) or "-"
        op_onepager_notes_saved = (op_note_row[9] if op_note_row and len(op_note_row) > 9 and op_note_row[9] else "")
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
                v = float(v)
                if math.isnan(v):
                    return "-"
                return f"{v:.{d}f}"
            except (TypeError, ValueError):
                return "-"

        def _op_pct(v):
            try:
                v = float(v)
                if math.isnan(v):
                    return "-"
            except (TypeError, ValueError):
                return "-"
            return f"{v:.1f}%" if v else "-"

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
                return f"<tr><td>{label}</td>" + "<td>-</td>" * 13 + "</tr>"
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
                f"<td>{_op_pct(r.get('TS'))}</td>"
                f"<td>{_op_pct(r.get('TWO_P'))}</td>"
                f"<td>{_op_pct(r.get('THREE_P'))}</td>"
                f"<td>{_op_pct(r.get('USG'))}</td>"
                f"<td>{_op_pct(r.get('AST_PCT'))}</td>"
                "</tr>"
            )

        if op_hdr is not None:
            _op_top100_box = load_consistent_boxscore_stats(max_opp_rank=100)
            _op_t100r = _op_top100_box[_op_top100_box["PLAYER"] == op_player]
            op_top100_row = _op_t100r.iloc[0] if not _op_t100r.empty else None

            _op_top50_box = load_consistent_boxscore_stats(max_opp_rank=50)
            _op_t50r = _op_top50_box[_op_top50_box["PLAYER"] == op_player]
            op_top50_row = _op_t50r.iloc[0] if not _op_t50r.empty else None

            _op_rows_html = _op_stats_row("Season", op_hdr)
            if op_conf_row is not None or op_nonconf_row is not None:
                _op_rows_html += _op_stats_row("Conference", op_conf_row)
                _op_rows_html += _op_stats_row("Non-Conf", op_nonconf_row)
            _op_rows_html += _op_stats_row("vs Top 100", op_top100_row)
            _op_rows_html += _op_stats_row("vs Top 50", op_top50_row)

            stats_table_html = f"""
            <table class="stats">
              <thead><tr>
                <th></th><th>GP</th><th>MPG</th><th>PPG</th><th>RPG</th><th>APG</th><th>SPG</th><th>BPG</th>
                <th>FG%</th><th>TS%</th><th>2P%</th><th>3P%</th><th>USG%</th><th>AST%</th>
              </tr></thead>
              <tbody>{_op_rows_html}</tbody>
            </table>
            """
        else:
            stats_table_html = (
                '<div style="font-family:Arimo,sans-serif;font-size:12px;color:#8494a5;">'
                'No BartTorvik stat line available for this player yet.</div>'
            )

        # Staff Notes - a real Streamlit widget that auto-saves on every change (no Save
        # button), instead of the old contenteditable <li> bullets baked into the printed
        # HTML below, which looked editable but never persisted anything past a refresh.
        def _save_onepager_notes(_player=op_player):
            conn = sqlite3.connect('scouting_hub.db')
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO player_notes (player_name, onepager_notes) VALUES (?, ?) "
                "ON CONFLICT(player_name) DO UPDATE SET onepager_notes=excluded.onepager_notes",
                (_player, st.session_state.get(f"op_staffnotes_{_player}", ""))
            )
            conn.commit()
            conn.close()

        st.text_area(
            "Staff Notes (auto-saves as you type)",
            value=op_onepager_notes_saved,
            key=f"op_staffnotes_{op_player}",
            on_change=_save_onepager_notes,
            height=110,
        )
        _staff_notes_current = st.session_state.get(f"op_staffnotes_{op_player}", op_onepager_notes_saved)
        _staff_notes_lines = [ln.strip() for ln in _staff_notes_current.split("\n") if ln.strip()][:5]
        staff_notes_html = "".join(f'<li>{ln}</li>' for ln in _staff_notes_lines)
        staff_notes_html += "".join('<li></li>' for _ in range(5 - len(_staff_notes_lines)))
        photo_style = f"background-image:url('{op_photo}');" if op_photo else ""

        # Front Office status - priority tier, value tag, and projected role from the
        # scouting report - always gets a spot between Stats and Staff Notes, filled in
        # with "-" when a field hasn't been set yet, so staff always see where to look.
        fo_status_html = f"""
      <div class="sec"><h2>FRONT OFFICE STATUS</h2><div class="rule"></div></div>
      <div class="fo-grid">
        <div class="fo-tile"><div class="fo-tile-label">Priority</div><div class="fo-tile-val">{op_priority}</div></div>
        <div class="fo-tile"><div class="fo-tile-label">Value</div><div class="fo-tile-val">{op_value_tag}</div></div>
        <div class="fo-tile"><div class="fo-tile-label">Role</div><div class="fo-tile-val">{op_role_text}</div></div>
      </div>
    """

        # Recruit Alignment Survey, printed between Stats and Staff Notes when one has
        # been saved for this player - staff walking into a meeting with this sheet
        # should see the alignment read without needing a second tab open.
        _op_survey_conn = sqlite3.connect('scouting_hub.db')
        _op_survey_conn.row_factory = sqlite3.Row
        _op_survey_row = _op_survey_conn.execute(
            "SELECT * FROM recruit_surveys WHERE player_name = ?", (op_player,)
        ).fetchone()
        _op_survey_conn.close()

        survey_section_html = ""
        if _op_survey_row:
            _op_survey = dict(_op_survey_row)
            _op_survey_score = sum(int(_op_survey.get(k) or 0) for k, *_ in SURVEY_CATEGORIES)
            _op_bucket = _op_survey.get("recruit_bucket") or "-"
            _op_priority = _op_survey.get("recruiting_priority") or "-"
            _survey_tiles = "".join(
                f"<div class='survey-tile'><div class='survey-tile-label'>{title}</div>"
                f"<div class='survey-tile-val'>{labels[int(_op_survey.get(key) or 3) - 1]}</div></div>"
                for key, title, _q, labels in SURVEY_CATEGORIES
            )
            survey_section_html = f"""
      <div class="sec"><h2>ALIGNMENT SURVEY</h2><div class="rule"></div></div>
      <div class="statline">{_op_survey_score}/40 &bull; {_op_bucket} &bull; {_op_priority}</div>
      <div class="survey-grid">{_survey_tiles}</div>
    """

        one_pager_html = f"""
    <!doctype html><html><head><meta charset="UTF-8">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Spectral:wght@400;500;600;700;800&family=Arimo:wght@400;700&display=swap" rel="stylesheet">
    <style>
      :root {{ --navy: #1B3E76; --banner-blue: #2D68C4; --ink: #1B3E76; --rule: #1B3E76; --gold: #F2A900; --paper: #ffffff; }}
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      body {{ background: #e8e8e8; font-family: 'Spectral', Georgia, serif; color: var(--ink); padding: 24px 0; }}
      .toolbar {{ max-width: 8.5in; margin: 0 auto 14px; display: flex; justify-content: flex-end; gap: 8px; padding: 0 8px; }}
      .toolbar button {{ font-family: 'Arimo', Arial, sans-serif; font-size: 13px; font-weight: 700; padding: 8px 16px;
        border: none; border-radius: 4px; cursor: pointer; background: var(--navy); color: #fff; }}
      .toolbar button.secondary {{ background: #6b7c8f; }}
      .page {{ width: 8.5in; min-height: 11in; margin: 0 auto; background: var(--paper); padding: 0.45in 0.5in 0.5in;
        box-shadow: 0 2px 14px rgba(0,0,0,0.18); }}
      .banner {{ background: var(--banner-blue); color: #fff; padding: 22px 26px 20px; display: flex;
        justify-content: space-between; align-items: flex-start; border-bottom: 3px solid var(--gold); }}
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
      .survey-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 4px; }}
      .survey-tile {{ font-family: 'Arimo', Arial, sans-serif; border: 1px solid #d7dfe7; border-radius: 6px;
        padding: 7px 9px; background: #f8fafc; }}
      .survey-tile-label {{ font-size: 9px; text-transform: uppercase; letter-spacing: 0.04em; color: #6b7c8f; margin-bottom: 2px; }}
      .survey-tile-val {{ font-size: 12.5px; font-weight: 700; color: var(--banner-blue); }}
      .fo-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 4px; }}
      .fo-tile {{ font-family: 'Arimo', Arial, sans-serif; border: 1px solid #d7dfe7; border-radius: 6px;
        padding: 9px 11px; background: #f8fafc; }}
      .fo-tile-label {{ font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; color: #6b7c8f; margin-bottom: 3px; }}
      .fo-tile-val {{ font-size: 14px; font-weight: 700; color: var(--banner-blue); }}
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
      {fo_status_html}
      {survey_section_html}
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
    st.subheader("Portal Discovery Engine")
    st.caption("Quick filters below cover most searches. Open Advanced Filters only for a specific stat threshold.")

    st.write("**Competition:**")
    _disc_split = st.segmented_control(
        "Competition:", ["All Games", "Top 100", "Top 50"],
        default="All Games", key="discovery_split", label_visibility="collapsed",
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

    with st.expander("Advanced Filters (position, team, tags, recruit ratings, stat minimums)", expanded=False):
        col_pos, col_class, col_conf, col_team = st.columns(4)
        with col_pos:
            selected_positions = st.multiselect("Position:", ["Guard", "Wing", "Big"])
        with col_class:
            class_options = sorted(list(df_all["CLASS"].dropna().unique()))
            selected_classes = st.multiselect("Class:", class_options)
        with col_conf:
            conf_options = sorted(list(df_all["CONF"].unique()))
            selected_confs = st.multiselect("Conference:", conf_options)
        with col_team:
            team_options = sorted(list(df_all["TEAM"].unique()))
            selected_teams = st.multiselect("Program / Team:", team_options)

        col_bucket, col_tags = st.columns(2)
        with col_bucket:
            # Recruit Bucket comes from the Recruit Alignment Survey - only players with a
            # saved survey have one, so this filter only ever narrows to tagged players.
            selected_buckets = st.multiselect("Recruit Bucket:", RECRUIT_BUCKETS)
        with col_tags:
            # Same auto-generated skill tags shown on a Player Card's hero bar, computed
            # for the whole pool once - the system already knows who qualifies for each
            # one, so this is a straight lookup rather than a coach guessing thresholds.
            _all_player_tags = build_all_player_tags(df_all)
            _tag_options = sorted({t for tags in _all_player_tags.values() for t in tags})
            selected_tags = st.multiselect(
                "Tags:", _tag_options,
                help="Filters to players who qualify for ANY of the selected tags.",
            )

        selected_survey_labels = {}
        use_survey_filters = st.checkbox("Filter by Recruit Alignment Survey ratings")
        if use_survey_filters:
            _survey_filter_cols = st.columns(4)
            for i, (cat_key, title, _q, labels) in enumerate(SURVEY_CATEGORIES):
                with _survey_filter_cols[i % 4]:
                    selected_survey_labels[cat_key] = st.multiselect(
                        f"{title}:", labels, key=f"disc_survey_{cat_key}")

        st.write("**Statistical range filters** — drag either end of a slider; leave it at full width to include everyone.")
        f1, f2, f3, f4 = st.columns(4)

        with f1:
            st.markdown("**Volume & Impact**")
            min_pct_rng = st.slider("Min%",      0.0, 100.0, (0.0, 100.0),   step=1.0, format="%.1f",
                                     help="Share of available team minutes this player is on the floor.")
            usg_rng     = st.slider("Usage%",     0.0,  50.0, (0.0, 50.0),   step=1.0, format="%.1f",
                                     help="Share of team plays this player uses (shots, assists, turnovers) while on the floor.")
            bpm_rng     = st.slider("Box BPM",  -20.0,  30.0, (-20.0, 30.0), step=0.5, format="%.1f",
                                     help="Box Plus-Minus: estimated point contribution per 100 possessions vs. an average player.")
            obpm_rng    = st.slider("Off. BPM", -20.0,  30.0, (-20.0, 30.0), step=0.5, format="%.1f",
                                     help="The offensive half of Box Plus-Minus.")
            dbpm_rng    = st.slider("Def. BPM", -20.0,  20.0, (-20.0, 20.0), step=0.5, format="%.1f",
                                     help="The defensive half of Box Plus-Minus.")

        with f2:
            st.markdown("**Efficiency & Scoring**")
            ortg_rng  = st.slider("O-Rating", 0.0, 150.0, (0.0, 150.0), step=1.0, format="%.1f",
                                   help="Points produced per 100 individual possessions used.")
            efg_rng   = st.slider("eFG%",     0.0, 100.0, (0.0, 100.0), step=1.0, format="%.1f",
                                   help="Effective field goal % - adjusts for 3-pointers being worth more than 2s.")
            ts_rng    = st.slider("TS%",      0.0, 100.0, (0.0, 100.0), step=1.0, format="%.1f",
                                   help="True Shooting % - overall scoring efficiency, including free throws.")
            two_p_rng = st.slider("2P%",      0.0, 100.0, (0.0, 100.0), step=1.0, format="%.1f",
                                   help="Two-point field goal percentage.")

        with f3:
            st.markdown("**Shooting & Frequency**")
            three_p_rng     = st.slider("3P%",     0.0, 100.0, (0.0, 100.0), step=1.0, format="%.1f",
                                         help="Three-point field goal percentage.")
            three_p_100_rng = st.slider("3PA/100",  0.0,  30.0, (0.0, 30.0), step=0.5, format="%.1f",
                                         help="Three-point attempts per 100 possessions - how often they shoot from three.")
            ftr_rng         = st.slider("FTR",      0.0, 150.0, (0.0, 150.0), step=1.0, format="%.1f",
                                         help="Free throw rate - how often this player draws fouls and gets to the line.")

        with f4:
            st.markdown("**Playmaking & Rebounding**")
            ast_rng = st.slider("Ast%",   0.0, 60.0,  (0.0, 60.0), step=1.0, format="%.1f",
                                 help="Share of teammate baskets this player assisted while on the floor.")
            tov_rng = st.slider("TO%",    0.0, 100.0, (0.0, 100.0), step=1.0, format="%.1f",
                                 help="Turnovers per 100 possessions used.")
            orb_rng = st.slider("O-Reb%", 0.0, 50.0,  (0.0, 50.0), step=1.0, format="%.1f",
                                 help="Share of available offensive rebounds grabbed while on the floor.")
            drb_rng = st.slider("D-Reb%", 0.0, 50.0,  (0.0, 50.0), step=1.0, format="%.1f",
                                 help="Share of available defensive rebounds grabbed while on the floor.")
            blk_rng = st.slider("Blk%",   0.0, 30.0,  (0.0, 30.0), step=0.5, format="%.1f",
                                 help="Share of opponent 2-point attempts blocked while on the floor.")
            stl_rng = st.slider("Stl%",   0.0, 15.0,  (0.0, 15.0), step=0.5, format="%.1f",
                                 help="Share of opponent possessions ended by a steal while on the floor.")

    filtered_df = disc_base_df.copy()

    _survey_filters_active = selected_buckets or any(selected_survey_labels.values())
    if _survey_filters_active:
        conn = sqlite3.connect('scouting_hub.db')
        _survey_df = pd.read_sql_query("SELECT * FROM recruit_surveys", conn).set_index("player_name")
        conn.close()

        if selected_buckets:
            _bucket_map = _survey_df["recruit_bucket"].to_dict()
            filtered_df = filtered_df[filtered_df["PLAYER"].map(_bucket_map).isin(selected_buckets)]

        for cat_key, _title, _q, labels in SURVEY_CATEGORIES:
            chosen_labels = selected_survey_labels.get(cat_key)
            if chosen_labels and cat_key in _survey_df.columns:
                valid_ratings = {labels.index(lbl) + 1 for lbl in chosen_labels}
                _rating_map = _survey_df[cat_key].to_dict()
                filtered_df = filtered_df[filtered_df["PLAYER"].map(_rating_map).isin(valid_ratings)]

    if selected_confs:
        filtered_df = filtered_df[filtered_df["CONF"].isin(selected_confs)]
    if selected_teams:
        filtered_df = filtered_df[filtered_df["TEAM"].isin(selected_teams)]
    if selected_classes:
        filtered_df = filtered_df[filtered_df["CLASS"].isin(selected_classes)]
    if selected_positions and "POS_TAG" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["POS_TAG"].map(
            lambda t: POS_TAG_BUCKET.get(t, "Wing")).isin(selected_positions)]
    if selected_tags:
        _wanted_tags = set(selected_tags)
        filtered_df = filtered_df[filtered_df["PLAYER"].map(
            lambda p: bool(_wanted_tags & set(_all_player_tags.get(p, []))))]

    def _col_filter_range(df, col, rng, floor, ceiling):
        # A slider left at its full width means "no filter" - matches the old
        # number-inputs' "leave at the floor = include everyone" behavior.
        lo, hi = rng
        if col not in df.columns or (lo <= floor and hi >= ceiling):
            return df
        return df[(df[col] >= lo) & (df[col] <= hi)]

    filtered_df = _col_filter_range(filtered_df, "MIN_PCT",     min_pct_rng,       0.0, 100.0)
    filtered_df = _col_filter_range(filtered_df, "BPM",         bpm_rng,         -20.0,  30.0)
    filtered_df = _col_filter_range(filtered_df, "OBPM",        obpm_rng,        -20.0,  30.0)
    filtered_df = _col_filter_range(filtered_df, "DBPM",        dbpm_rng,        -20.0,  20.0)
    filtered_df = _col_filter_range(filtered_df, "ORTG",        ortg_rng,          0.0, 150.0)
    filtered_df = _col_filter_range(filtered_df, "USG",         usg_rng,           0.0,  50.0)
    filtered_df = _col_filter_range(filtered_df, "EFG",         efg_rng,           0.0, 100.0)
    filtered_df = _col_filter_range(filtered_df, "TS",          ts_rng,            0.0, 100.0)
    filtered_df = _col_filter_range(filtered_df, "OR",          orb_rng,           0.0,  50.0)
    filtered_df = _col_filter_range(filtered_df, "DR",          drb_rng,           0.0,  50.0)
    filtered_df = _col_filter_range(filtered_df, "AST",         ast_rng,           0.0,  60.0)
    filtered_df = _col_filter_range(filtered_df, "TO",          tov_rng,           0.0, 100.0)
    filtered_df = _col_filter_range(filtered_df, "BLK",         blk_rng,           0.0,  30.0)
    filtered_df = _col_filter_range(filtered_df, "STL",         stl_rng,           0.0,  15.0)
    filtered_df = _col_filter_range(filtered_df, "FTR",         ftr_rng,           0.0, 150.0)
    filtered_df = _col_filter_range(filtered_df, "TWO_P",       two_p_rng,         0.0, 100.0)
    filtered_df = _col_filter_range(filtered_df, "THREE_P",     three_p_rng,       0.0, 100.0)
    filtered_df = _col_filter_range(filtered_df, "THREE_P_100", three_p_100_rng,   0.0,  30.0)

    sort_col = "PRPG" if "PRPG" in filtered_df.columns else "PPG" if "PPG" in filtered_df.columns else filtered_df.columns[0]
    filtered_df = filtered_df.sort_values(by=sort_col, ascending=False)

    _hidden = {"team_espn_id"}
    # Plain columns (identity + raw counting stats, no percentile color) up front, then
    # every percentile-colored stat grouped together right after - instead of interleaved,
    # so it's obvious at a glance which block of columns is which.
    _basic_cols = ["PLAYER", "TEAM", "CONF", "CLASS", "HEIGHT", "GP", "MPG", "PPG", "RPG", "APG"]
    _style_cols = ["PRPG", "BPM", "OBPM", "DBPM", "ORTG", "MIN_PCT", "USG", "EFG", "TS",
                   "TWO_P", "THREE_P", "FTR", "FT_PCT", "AST", "TO", "OR", "DR", "BLK", "STL"]
    _basic_cols = [c for c in _basic_cols if c in filtered_df.columns]
    _style_cols = [c for c in _style_cols if c in filtered_df.columns]
    ordered_cols = _basic_cols + _style_cols
    remaining_cols = [c for c in filtered_df.columns if c not in ordered_cols and c not in _hidden]
    filtered_df = filtered_df[ordered_cols + remaining_cols]

    st.write(f"**Filter Results ({st.session_state.discovery_split}):** Found {len(filtered_df)} profiles matching criteria.")
    show_all_stats = st.checkbox(
        "Show all advanced stat columns", value=False,
        help="Off shows a compact view (name, team, class, height, and the basics). "
             "On adds the full percentile-colored stat breakdown.",
    )
    _essential_cols = [c for c in
                        ["PLAYER", "TEAM", "CONF", "CLASS", "HEIGHT", "GP", "MPG", "PPG", "RPG", "APG",
                         "TS", "BPM", "USG"]
                        if c in filtered_df.columns]
    display_df = filtered_df if show_all_stats else filtered_df[_essential_cols]
    display_style_cols = _style_cols if show_all_stats else [
        c for c in ["TS", "BPM", "USG"] if c in display_df.columns
    ]

    # A widget callback only fires when *this* widget's own selection genuinely
    # changes from a user click on it - unlike checking event_discovery.selection.rows
    # in the main body, which re-reads the same still-selected row on every rerun
    # (including ones triggered by unrelated widgets, like picking a new player in the
    # Player Card dropdown) and would keep forcing active_player back to this row.
    def _on_portal_row_click():
        sel = st.session_state.get("discovery_df_select", {})
        rows = sel.get("selection", {}).get("rows", [])
        if rows:
            st.session_state.active_player = filtered_df.iloc[rows[0]]["PLAYER"]
            st.session_state.active_player_team = filtered_df.iloc[rows[0]]["TEAM"]
            st.session_state.go_to_profile = True

    # BartTorvik's raw feed comes back at full float precision (e.g. 14.6471), which is what
    # made this read like an unformatted spreadsheet export - round it for display via
    # column_config instead of mutating the underlying data used for filtering/sorting above.
    _pct_cols = {"USG", "EFG", "TS", "AST", "OR", "DR", "BLK", "STL", "FTR", "FT_PCT",
                 "TWO_P", "THREE_P", "THREE_P_100", "MIN_PCT", "TO"}
    _decimal_cols = {"PPG", "PRPG", "BPM", "OBPM", "DBPM", "SOS", "RPG", "APG", "MPG", "ORTG"}
    # Hover help text so a coach doesn't need to know the abbreviations to read the table.
    _stat_help = {
        "MPG": "Minutes per game.", "PPG": "Points per game.", "RPG": "Rebounds per game.",
        "APG": "Assists per game.",
        "TS": "True Shooting % - overall scoring efficiency, including free throws.",
        "BPM": "Box Plus-Minus - estimated point contribution per 100 possessions vs. an average player.",
        "USG": "Usage % - share of team plays this player uses while on the floor.",
        "PRPG": "Points Responsible Per Game - overall value including scoring and playmaking.",
        "OBPM": "The offensive half of Box Plus-Minus.",
        "DBPM": "The defensive half of Box Plus-Minus.",
        "ORTG": "Points produced per 100 individual possessions used.",
        "EFG": "Effective FG% - adjusts for 3-pointers being worth more than 2s.",
        "TWO_P": "Two-point field goal percentage.", "THREE_P": "Three-point field goal percentage.",
        "THREE_P_100": "Three-point attempts per 100 possessions.",
        "FTR": "Free throw rate - how often this player draws fouls and gets to the line.",
        "FT_PCT": "Free throw percentage.",
        "AST": "Assist % - share of teammate baskets this player assisted.",
        "TO": "Turnover % - turnovers per 100 possessions used.",
        "OR": "Offensive rebound % of available boards grabbed.",
        "DR": "Defensive rebound % of available boards grabbed.",
        "BLK": "Block % of opponent 2-point attempts.", "STL": "Steal % of opponent possessions.",
        "MIN_PCT": "Share of available team minutes played.", "SOS": "Strength of schedule.",
    }
    _discovery_col_config = {
        "PLAYER": st.column_config.TextColumn("Player", pinned=True),
        "TEAM": st.column_config.TextColumn("Team"),
        "CONF": st.column_config.TextColumn("Conf"),
        "CLASS": st.column_config.TextColumn("Class"),
        "HEIGHT": st.column_config.TextColumn("Height"),
        "GP": st.column_config.NumberColumn("GP", format="%d", help="Games played."),
    }
    for _c in display_df.columns:
        if _c in _discovery_col_config:
            continue
        if _c in _pct_cols:
            _discovery_col_config[_c] = st.column_config.NumberColumn(_c, format="%.1f%%", help=_stat_help.get(_c))
        elif _c in _decimal_cols:
            _discovery_col_config[_c] = st.column_config.NumberColumn(_c, format="%.1f", help=_stat_help.get(_c))

    st.markdown(
        "<style>"
        "div[data-testid='stDataFrame'] { border: 1px solid #d7dfe7; border-radius: 8px; "
        "overflow: hidden; box-shadow: 0 1px 3px rgba(15,23,42,0.06); }"
        "div[data-testid='stExpander'] { border-left: 3px solid #2D68C4; border-radius: 6px; }"
        "</style>",
        unsafe_allow_html=True,
    )

    # Color the same stat columns the same blue-grey-gold way the Player Card and comp
    # cards do (via national percentile), so this reads as part of the same tool instead
    # of a raw spreadsheet export. _style_cols (built above, alongside _basic_cols) is the
    # single source of truth for both column order and which columns get colored.
    _discovery_benchmarks = build_national_benchmarks(df_all)

    def _discovery_cell_style(col):
        styles = []
        # Bold + a left divider on the first colored column, so the "plain" block
        # (identity/counting stats) reads as visually distinct from the "percentile"
        # block instead of every column looking the same weight.
        is_first_style_col = display_style_cols and col.name == display_style_cols[0]
        for val in col:
            pct = national_pct(col.name, val, _discovery_benchmarks)
            if pct is None:
                styles.append("border-left:2px solid #2D68C4;" if is_first_style_col else "")
                continue
            bg, fg = pct_color(pct)
            border = "border-left:2px solid #2D68C4;" if is_first_style_col else ""
            styles.append(f"background-color:{bg};color:{fg};font-weight:700;{border}")
        return styles

    _styled_discovery_df = display_df.style.apply(_discovery_cell_style, subset=display_style_cols)

    event_discovery = st.dataframe(
        _styled_discovery_df,
        hide_index=True,
        on_select=_on_portal_row_click,
        selection_mode="single-row",
        height=650,
        use_container_width=True,
        column_config=_discovery_col_config,
        key="discovery_df_select",
    )

    if event_discovery.selection.rows:
        clicked_idx = event_discovery.selection.rows[0]
        clicked_player = filtered_df.iloc[clicked_idx]["PLAYER"]
        st.caption(f"🎯 **{clicked_player}** selected - their full profile is loaded on the "
                   f"**Individual Player Stats** and **Print Out** tabs.")


# ==========================================
# TAB 3: FRONT OFFICE TARGET BOARD
# ==========================================
def _build_board_print_html(board_groups):
    """Printable Big Board: every position row, ranked, one clean page."""
    TIER_ABBR = {"High Priority": "HIGH", "Mid Priority": "MID", "Low Priority": "LOW"}
    sections = []
    for pos, group_df in board_groups.items():
        if group_df.empty:
            continue
        rows_html = ""
        for i, row in group_df.reset_index(drop=True).iterrows():
            rows_html += (
                f"<tr><td class='rank'>{i + 1}</td><td class='name'>{row['PLAYER']}</td>"
                f"<td class='stats'>{row.get('STATS_TEXT', '-')}</td>"
                f"<td>{row['TEAM'] or '-'}</td><td>{TIER_ABBR.get(row['TIER'], row['TIER'] or '-')}</td>"
                f"<td>{row['VALUE TAG'] or '-'}</td><td class='role'>{row['ROLE'] or ''}</td></tr>"
            )
        sections.append(
            f"<div class='pos-block'><h2>{pos}</h2>"
            f"<table><thead><tr><th></th><th>Name</th><th>Stats</th><th>Team</th><th>Priority</th>"
            f"<th>Value</th><th>Role</th></tr></thead><tbody>{rows_html}</tbody></table></div>"
        )
    body = "".join(sections) if sections else "<p>No targets logged yet.</p>"
    return f"""
<!doctype html><html><head><meta charset="UTF-8">
<link href="https://fonts.googleapis.com/css2?family=Spectral:wght@400;600;700;800&family=Arimo:wght@400;700&display=swap" rel="stylesheet">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Spectral',Georgia,serif; color:#1B3E76; padding:20px; background:#fff; }}
  .toolbar {{ text-align:right; margin-bottom:14px; }}
  .toolbar button {{ font-family:'Arimo',Arial,sans-serif; font-size:13px; font-weight:700; padding:8px 16px;
    border:none; border-radius:4px; cursor:pointer; background:#2D68C4; color:#fff; }}
  h1 {{ font-size:26px; border-bottom:3px solid #F2A900; padding-bottom:8px; margin-bottom:16px; }}
  .pos-block {{ margin-bottom:22px; page-break-inside:avoid; }}
  .pos-block h2 {{ font-size:17px; text-transform:uppercase; letter-spacing:0.06em; color:#fff;
    background:#2D68C4; padding:6px 10px; border-radius:4px 4px 0 0; }}
  table {{ width:100%; border-collapse:collapse; font-family:'Arimo',Arial,sans-serif; font-size:12.5px; }}
  th {{ text-align:left; padding:6px 8px; background:#eef3fb; color:#1B3E76; font-size:10.5px; text-transform:uppercase; }}
  td {{ padding:6px 8px; border-bottom:1px solid #eef1f5; }}
  td.rank {{ color:#94A3B8; font-weight:700; width:24px; }}
  td.name {{ font-weight:700; }}
  td.role {{ color:#475569; font-size:11.5px; }}
  td.stats {{ color:#1B3E76; font-size:10.5px; font-weight:600; white-space:nowrap; }}
  @media print {{ .toolbar {{ display:none; }} body {{ padding:0; }} }}
</style>
</head><body>
<div class="toolbar"><button onclick="window.print()">Print Big Board</button></div>
<h1>UCLA Basketball &middot; Front Office Target Board</h1>
{body}
</body></html>
"""


with tab3:
    st.subheader("Front Office Target Board")
    st.caption("The Big Board, ranked by position. Click a name to open their full Individual "
               "Player Stats page. Use the arrows to reorder within a position.")

    conn = sqlite3.connect('scouting_hub.db')
    db_df = pd.read_sql_query('''
        SELECT player_name AS PLAYER, team_name AS TEAM, position AS POS, role AS ROLE,
               notes AS NOTES, priority_tier AS TIER, value_tag AS [VALUE TAG],
               board_rank AS [BOARD RANK]
        FROM player_notes
        WHERE priority_tier IS NOT NULL AND priority_tier != ''
    ''', conn)

    if db_df.empty:
        conn.close()
        st.info("No targets currently logged onto the system database. Add a target from the "
                 "**Big Board Status** section on any player's Individual Player Stats page.")
    else:
        _class_lookup = dict(zip(df_all["PLAYER"], df_all["CLASS"]))
        db_df["CLASS"] = db_df["PLAYER"].map(_class_lookup)

        col_search, col_class_f = st.columns([2, 1])
        with col_search:
            _board_q = st.text_input("Search by player or school:", key="board_search_q").strip().lower()
        with col_class_f:
            _class_opts = [c for c in ["Fr", "So", "Jr", "Sr"] if c in set(db_df["CLASS"].dropna())]
            _board_class_f = st.multiselect("Year of Eligibility", _class_opts, key="board_class_f")

        if _board_q:
            db_df = db_df[
                db_df["PLAYER"].str.lower().str.contains(_board_q, na=False)
                | db_df["TEAM"].fillna("").str.lower().str.contains(_board_q, na=False)
            ]
        if _board_class_f:
            db_df = db_df[db_df["CLASS"].isin(_board_class_f)]

        db_df["BOARD_POS"] = db_df["POS"].map(lambda v: LEGACY_BOARD_POS_MAP.get(v, v) if v else None)
        _board_benchmarks = build_national_benchmarks(df_all)

        _conn_s = sqlite3.connect('scouting_hub.db')
        _conn_s.row_factory = sqlite3.Row
        _survey_rows = {r["player_name"]: dict(r) for r in _conn_s.execute("SELECT * FROM recruit_surveys").fetchall()}
        _conn_s.close()

        def _board_stat_row(p_name):
            match = df_all[df_all["PLAYER"] == p_name]
            if match.empty:
                return "<span style='color:#94A3B8;font-size:11px;'>No stat line found</span>", []
            srow = match.iloc[0]

            def _v(col):
                try:
                    return f"{float(srow.get(col)):.1f}"
                except (TypeError, ValueError):
                    return "-"

            stats_html = (
                "<div style='display:flex;gap:14px;'>"
                + "".join(
                    f"<div><span style='font-weight:800;color:#0F172A;'>{_v(col)}</span>"
                    f"<span style='color:#94A3B8;font-size:10px;'> {label}</span></div>"
                    for col, label in [("PPG", "PPG"), ("RPG", "RPG"), ("APG", "APG")]
                )
                + "</div>"
            )
            tag_stats = dict(srow)
            tag_stats.update(get_player_shot_zone_dict(p_name, srow.get("TEAM")))
            tags = build_auto_skill_tags(tag_stats, _board_benchmarks, top_n=3, threshold=80.0)
            _box_match = load_consistent_boxscore_stats()
            _box_match = _box_match[_box_match["PLAYER"] == p_name]
            for _vt in build_volume_tags(_box_match.iloc[0] if not _box_match.empty else None):
                if _vt not in tags:
                    tags.append(_vt)
            return stats_html, tags

        def _swap_board_rank(names, i, j):
            cur = conn.cursor()
            a, b = names[i], names[j]
            ra = cur.execute("SELECT board_rank FROM player_notes WHERE player_name=?", (a,)).fetchone()[0]
            rb = cur.execute("SELECT board_rank FROM player_notes WHERE player_name=?", (b,)).fetchone()[0]
            cur.execute("UPDATE player_notes SET board_rank=? WHERE player_name=?", (rb, a))
            cur.execute("UPDATE player_notes SET board_rank=? WHERE player_name=?", (ra, b))
            conn.commit()

        def _rank_group(group_df):
            # Any target without a rank yet gets one assigned once, so manual
            # reordering has real integers to swap instead of colliding on NULL.
            if not group_df.empty and group_df["BOARD RANK"].isna().any():
                next_rank = int(group_df["BOARD RANK"].max()) + 1 if group_df["BOARD RANK"].notna().any() else 0
                cur = conn.cursor()
                for _, mrow in group_df[group_df["BOARD RANK"].isna()].sort_values("PLAYER").iterrows():
                    cur.execute("UPDATE player_notes SET board_rank = ? WHERE player_name = ?", (next_rank, mrow["PLAYER"]))
                    group_df.loc[group_df["PLAYER"] == mrow["PLAYER"], "BOARD RANK"] = next_rank
                    next_rank += 1
                conn.commit()
            return group_df.sort_values("BOARD RANK").reset_index(drop=True)

        board_groups = {pos: _rank_group(db_df[db_df["BOARD_POS"] == pos].copy()) for pos in BOARD_POSITIONS}

        display_positions = list(BOARD_POSITIONS)
        leftover_df = db_df[~db_df["BOARD_POS"].isin(BOARD_POSITIONS)].copy()
        if not leftover_df.empty:
            board_groups["Unclassified"] = _rank_group(leftover_df)
            display_positions.append("Unclassified")

        def _print_stat_text(p_name):
            match = df_all[df_all["PLAYER"] == p_name]
            if match.empty:
                return "-"
            s = match.iloc[0]

            def _v(col):
                try:
                    return f"{float(s.get(col)):.1f}"
                except (TypeError, ValueError):
                    return "-"

            return f"{_v('PPG')} PPG &middot; {_v('RPG')} RPG &middot; {_v('APG')} APG"

        for _pos_key, _gdf in board_groups.items():
            if not _gdf.empty:
                _gdf["STATS_TEXT"] = _gdf["PLAYER"].map(_print_stat_text)

        with st.expander("Print Big Board"):
            components.html(_build_board_print_html(board_groups), height=600, scrolling=True)

        _board_filters_active = bool(_board_q or _board_class_f)
        for pos in display_positions:
            group_df = board_groups[pos]
            st.markdown(f"### {pos} ({len(group_df)})")
            if group_df.empty:
                st.caption("No targets match these filters." if _board_filters_active
                           else "No targets logged at this position yet.")
                st.divider()
                continue

            ordered_names = group_df["PLAYER"].tolist()
            for i, row in group_df.iterrows():
                p_name = row["PLAYER"]
                # Once a Recruit Alignment Survey exists for this player, the badges switch
                # from the manually-set Priority/Value Tag to the survey's own verdict - the
                # survey is a more informed, staff-aligned read, so it should replace the
                # placeholder rather than just sit in a caption line underneath.
                _survey = _survey_rows.get(p_name)
                if _survey:
                    _survey_score = sum(int(_survey.get(k) or 0) for k, *_ in SURVEY_CATEGORIES)
                    _survey_priority = _survey.get("recruiting_priority") or "-"
                    _survey_bucket = _survey.get("recruit_bucket") or "-"
                    _priority_color = SURVEY_PRIORITY_COLORS.get(_survey_priority, "#64748B")
                    _badges_html = (
                        f"<span style='background:{_priority_color}1A;color:{_priority_color};border:1px solid {_priority_color}55;"
                        f"padding:3px 8px;border-radius:4px;font-size:10.5px;font-weight:700;margin-right:4px;'>{_survey_score}/40</span>"
                        f"<span style='background:{_priority_color}1A;color:{_priority_color};border:1px solid {_priority_color}55;"
                        f"padding:3px 8px;border-radius:4px;font-size:10.5px;font-weight:700;margin-right:4px;'>{_survey_priority}</span>"
                        f"<span style='background:#eef3fb;color:#2D68C4;border:1px solid #cfe0f5;"
                        f"padding:3px 8px;border-radius:4px;font-size:10.5px;font-weight:700;'>{_survey_bucket}</span>"
                    )
                else:
                    v_tag = row["VALUE TAG"] if row["VALUE TAG"] else "Properly Valued"
                    v_color = VALUE_TAG_COLORS.get(v_tag, "#64748B")
                    t_color = TIER_BADGE_COLORS.get(row["TIER"], "#94A3B8")
                    _badges_html = (
                        f"<span style='background:{t_color}1A;color:{t_color};border:1px solid {t_color}55;"
                        f"padding:3px 8px;border-radius:4px;font-size:10.5px;font-weight:700;margin-right:4px;'>{row['TIER'] or '-'}</span>"
                        f"<span style='background:{v_color}1A;color:{v_color};border:1px solid {v_color}55;"
                        f"padding:3px 8px;border-radius:4px;font-size:10.5px;font-weight:700;'>{v_tag}</span>"
                    )

                stats_html, tags = _board_stat_row(p_name)
                tags_html = "".join(
                    f"<span style='background:#eef3fb;color:#2D68C4;border:1px solid #cfe0f5;"
                    f"padding:2px 7px;border-radius:10px;font-size:9.5px;font-weight:700;margin:2px 4px 0 0;"
                    f"display:inline-block;'>{t}</span>"
                    for t in tags
                )
                photo_url = fetch_espn_headshot(p_name)

                row_box = st.container(border=True)
                with row_box:
                    c_rank, c_up, c_dn, c_photo, c_name, c_stats, c_meta, c_badge = st.columns(
                        [0.3, 0.3, 0.3, 0.6, 1.8, 1.5, 1.0, 1.9]
                    )
                    c_rank.markdown(
                        f"<div style='padding-top:14px;font-weight:800;color:#94A3B8;'>{i + 1}</div>",
                        unsafe_allow_html=True,
                    )
                    if c_up.button("↑", key=f"up_{pos}_{p_name}", disabled=(i == 0)):
                        _swap_board_rank(ordered_names, i, i - 1)
                        st.rerun()
                    if c_dn.button("↓", key=f"dn_{pos}_{p_name}", disabled=(i == len(ordered_names) - 1)):
                        _swap_board_rank(ordered_names, i, i + 1)
                        st.rerun()
                    with c_photo:
                        if photo_url:
                            st.image(photo_url, width=42)
                        else:
                            st.markdown(
                                "<div style='width:42px;height:42px;border-radius:50%;background:#e2e8f0;"
                                "display:flex;align-items:center;justify-content:center;color:#94A3B8;"
                                "font-size:9px;margin-top:6px;'>N/A</div>",
                                unsafe_allow_html=True,
                            )
                    with c_name:
                        if st.button(p_name, key=f"open_{pos}_{p_name}"):
                            st.session_state.active_player = p_name
                            st.session_state.active_player_team = row["TEAM"]
                            st.session_state.go_to_profile = True
                            st.rerun()
                        if row["ROLE"]:
                            st.caption(row["ROLE"])
                        if tags_html:
                            st.markdown(tags_html, unsafe_allow_html=True)
                    c_stats.markdown(f"<div style='padding-top:14px;'>{stats_html}</div>", unsafe_allow_html=True)
                    c_meta.markdown(f"<div style='padding-top:14px;font-weight:600;color:#1B3E76;'>{row['TEAM'] or '-'}</div>", unsafe_allow_html=True)
                    c_badge.markdown(
                        f"<div style='padding-top:12px;'>{_badges_html}</div>",
                        unsafe_allow_html=True,
                    )
            st.divider()
        conn.close()


# ==========================================
# TAB 4: RECRUIT ALIGNMENT SURVEY (Max Feldman's pre-recruiting evaluation)
# ==========================================
with tab4:
    st.subheader("UCLA Recruit Alignment Survey")
    st.caption("Pre-Recruiting Evaluation - staff alignment on transfer portal and high school targets. "
               "Once saved, a player's results show as tags on their Player Card, right above the advanced stats.")

    conn = sqlite3.connect('scouting_hub.db')
    _survey_names = [r[0] for r in conn.execute(
        "SELECT player_name FROM recruit_surveys ORDER BY player_name").fetchall()]
    conn.close()

    col_pick, col_link = st.columns(2)
    with col_pick:
        survey_pick = st.selectbox("Load existing survey to edit:", ["+ New Survey"] + _survey_names,
                                   key="recruit_survey_pick")

    saved_survey = None
    if survey_pick != "+ New Survey":
        conn = sqlite3.connect('scouting_hub.db')
        conn.row_factory = sqlite3.Row
        _row = conn.execute("SELECT * FROM recruit_surveys WHERE player_name = ?", (survey_pick,)).fetchone()
        conn.close()
        if _row:
            saved_survey = dict(_row)

    def _sv(key, default=""):
        v = saved_survey.get(key) if saved_survey else None
        return v if v not in (None, "") else default

    # International prospects (from the International Players tab) are searchable here too,
    # tagged " (Intl)" since their names can collide with a tracked domestic player.
    _intl_link_conn = sqlite3.connect('scouting_hub.db')
    _intl_link_rows = {
        r[0]: {"TEAM": r[1], "POS_TAG": _intl_pos_to_board(r[2])}
        for r in _intl_link_conn.execute("SELECT player_name, country, position FROM international_players").fetchall()
    }
    _intl_link_conn.close()

    with col_link:
        _intl_link_options = sorted(f"{n} (Intl)" for n in _intl_link_rows.keys())
        _link_options = ["- Not in database / High School Recruit -"] + all_player_names + _intl_link_options
        link_pick = st.selectbox("Auto-fill from a tracked player (optional):", _link_options,
                                 key="recruit_link_pick")
    _link_row = None
    _link_display_name = link_pick
    if link_pick != _link_options[0]:
        if link_pick.endswith(" (Intl)"):
            _link_display_name = link_pick[:-len(" (Intl)")]
            _link_row = _intl_link_rows.get(_link_display_name)
        else:
            _lm = df_all[df_all["PLAYER"] == link_pick]
            if not _lm.empty:
                _link_row = _lm.iloc[0]

    st.divider()

    # Every widget below keys off _fkey (survey_pick) or _nkey (survey_pick + link_pick) so
    # switching which saved survey is loaded - or which player it's linked to - actually
    # resets the field to that record's values, instead of Streamlit keeping whatever the
    # widget last held (the same stale-widget-state issue fixed earlier for player search).
    _fkey = survey_pick
    _nkey = f"{survey_pick}__{link_pick}"

    c1, c2, c3 = st.columns(3)
    with c1:
        _default_name = survey_pick if survey_pick != "+ New Survey" else (
            _link_display_name if _link_row is not None else _sv("player_name"))
        player_name_input = st.text_input("Player Name:", value=_default_name, key=f"survey_name_{_nkey}")
    with c2:
        _default_school = _sv("school") or (str(_link_row["TEAM"]) if _link_row is not None else "")
        school_input = st.text_input("School / Current Team:", value=_default_school, key=f"survey_school_{_nkey}")
    with c3:
        _default_pos = _sv("position") or (str(_link_row.get("POS_TAG", "")) if _link_row is not None else "")
        position_input = st.text_input("Position:", value=_default_pos, key=f"survey_pos_{_nkey}")

    recruit_bucket_input = st.radio(
        "Recruit Bucket", RECRUIT_BUCKETS,
        index=RECRUIT_BUCKETS.index(_sv("recruit_bucket")) if _sv("recruit_bucket") in RECRUIT_BUCKETS else 0,
        key=f"survey_bucket_{_fkey}",
    )

    c4, c5 = st.columns(2)
    with c4:
        evaluator_input = st.text_input("Primary Evaluator:", value=_sv("primary_evaluator"),
                                        key=f"survey_evaluator_{_fkey}")
    with c5:
        _default_date_str = _sv("eval_date") or datetime.now().strftime("%Y-%m-%d")
        try:
            _default_date_obj = datetime.strptime(_default_date_str, "%Y-%m-%d").date()
        except ValueError:
            _default_date_obj = datetime.now().date()
        date_input = st.date_input("Date:", value=_default_date_obj, key=f"survey_date_{_fkey}")

    st.divider()

    ratings = {}
    market_value_input = ""
    for i, (cat_key, title, question, labels) in enumerate(SURVEY_CATEGORIES, start=1):
        st.write(f"**{i}. {title}**")
        if question:
            st.markdown(f"<div style='font-size:1.05rem;font-weight:700;color:#111827;margin-bottom:6px;'>{question}</div>",
                       unsafe_allow_html=True)
        _default_rating = int(_sv(cat_key, 3) or 3)
        ratings[cat_key] = st.radio(
            f"rating_{cat_key}", [1, 2, 3, 4, 5],
            format_func=lambda v, labels=labels: f"{v} - {labels[v - 1]}",
            index=_default_rating - 1,
            horizontal=True,
            key=f"survey_rating_{cat_key}_{_fkey}",
            label_visibility="collapsed",
        )
        if cat_key == "financial_alignment":
            market_value_input = st.text_input("Estimated Market Value:", value=_sv("market_value"),
                                                placeholder="e.g. $1.2M", key=f"survey_marketval_{_fkey}")

    st.divider()
    st.write("**Notes**")
    best_info_source_input = st.text_input("Best information source:", value=_sv("best_info_source"),
                                           key=f"survey_infosrc_{_fkey}")
    best_influencer_input = st.text_input("Best influencer:", value=_sv("best_influencer"),
                                          key=f"survey_influencer_{_fkey}")
    relationship_owner_input = st.text_input("Who should own this relationship?", value=_sv("relationship_owner"),
                                             key=f"survey_owner_{_fkey}")
    hidden_connections_input = st.text_area("Any hidden connections?", value=_sv("hidden_connections"),
                                            key=f"survey_hidden_{_fkey}")

    overall_score = sum(ratings.values())
    st.metric("Overall Alignment Score", f"{overall_score} / 40")

    priority_input = st.radio(
        "Recruiting Priority", RECRUIT_PRIORITY_OPTIONS,
        index=RECRUIT_PRIORITY_OPTIONS.index(_sv("recruiting_priority"))
        if _sv("recruiting_priority") in RECRUIT_PRIORITY_OPTIONS else 2,
        key=f"survey_priority_{_fkey}",
    )

    if st.button("Save Survey", type="primary"):
        if not player_name_input.strip():
            st.error("Player Name is required.")
        else:
            conn = sqlite3.connect('scouting_hub.db')
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO recruit_surveys (
                    player_name, school, position, recruit_bucket, primary_evaluator, eval_date,
                    self_awareness, circle_alignment, positional_fit, financial_alignment,
                    coachability, physical_toughness, representation, info_influence,
                    market_value, best_info_source, best_influencer, relationship_owner,
                    hidden_connections, recruiting_priority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(player_name) DO UPDATE SET
                    school=excluded.school, position=excluded.position, recruit_bucket=excluded.recruit_bucket,
                    primary_evaluator=excluded.primary_evaluator, eval_date=excluded.eval_date,
                    self_awareness=excluded.self_awareness, circle_alignment=excluded.circle_alignment,
                    positional_fit=excluded.positional_fit, financial_alignment=excluded.financial_alignment,
                    coachability=excluded.coachability, physical_toughness=excluded.physical_toughness,
                    representation=excluded.representation, info_influence=excluded.info_influence,
                    market_value=excluded.market_value, best_info_source=excluded.best_info_source,
                    best_influencer=excluded.best_influencer, relationship_owner=excluded.relationship_owner,
                    hidden_connections=excluded.hidden_connections, recruiting_priority=excluded.recruiting_priority
            ''', (
                player_name_input.strip(), school_input, position_input, recruit_bucket_input,
                evaluator_input, date_input.strftime("%Y-%m-%d"),
                ratings["self_awareness"], ratings["circle_alignment"], ratings["positional_fit"],
                ratings["financial_alignment"], ratings["coachability"], ratings["physical_toughness"],
                ratings["representation"], ratings["info_influence"],
                market_value_input, best_info_source_input, best_influencer_input,
                relationship_owner_input, hidden_connections_input, priority_input,
            ))
            conn.commit()
            conn.close()
            st.success(f"Survey saved for {player_name_input.strip()}.")
            st.rerun()

    st.divider()
    st.write("**All Saved Surveys**")
    conn = sqlite3.connect('scouting_hub.db')
    _all_surveys = pd.read_sql_query("SELECT * FROM recruit_surveys", conn)
    conn.close()

    if _all_surveys.empty:
        st.caption("No surveys saved yet.")
    else:
        _rating_cols = [c for c, *_ in SURVEY_CATEGORIES]
        _all_surveys["Overall Score"] = _all_surveys[_rating_cols].sum(axis=1)
        _all_surveys = _all_surveys.sort_values("Overall Score", ascending=False)
        _board_display = _all_surveys[["player_name", "school", "recruit_bucket", "Overall Score",
                                       "recruiting_priority", "primary_evaluator", "eval_date"]].rename(columns={
            "player_name": "Player", "school": "School/Team", "recruit_bucket": "Bucket",
            "recruiting_priority": "Priority", "primary_evaluator": "Evaluator", "eval_date": "Date",
        })
        st.dataframe(_board_display, hide_index=True, use_container_width=True)

# ==========================================
# TAB: SYNERGY PLAY TYPES
# ==========================================
with tab_synergy:
    st.subheader("Synergy Play Types · 2021-22")

    @st.cache_data(ttl=3600)
    def _synergy_player_list():
        try:
            c = sqlite3.connect("scouting_hub.db")
            rows = c.execute(
                "SELECT DISTINCT player_name FROM synergy_playtypes ORDER BY player_name"
            ).fetchall()
            c.close()
            return [r[0] for r in rows]
        except Exception:
            return []

    @st.cache_data(ttl=3600)
    def _load_synergy_events(player_name):
        try:
            c = sqlite3.connect("scouting_hub.db")
            rows = c.execute(
                "SELECT shot_x, shot_y, play_tags, game_quarter, d_player_name, "
                "zone, short_clock, pick_and_roll, is_home "
                "FROM synergy_events WHERE player_name=?", (player_name,)
            ).fetchall()
            c.close()
            import json as _json
            result = []
            for x, y, tags_str, qtr, defender, zone, sc, pnr, home in rows:
                tags = _json.loads(tags_str) if tags_str else []
                made = "Make2Pts" in tags or "Make3Pts" in tags or "Make2PtsFoul" in tags or "Make3PtsFoul" in tags
                is3 = "Make3Pts" in tags or "Miss3Pts" in tags or "Make3PtsFoul" in tags
                is_shot = any(t in tags for t in ["Make2Pts","Miss2Pts","Make3Pts","Miss3Pts","Make2PtsFoul","Make3PtsFoul"])
                result.append({
                    "x": x, "y": y, "tags": tags, "made": made, "is3": is3,
                    "is_shot": is_shot, "qtr": qtr, "defender": defender,
                    "zone": zone, "short_clock": sc, "pnr": pnr, "home": home,
                })
            return result
        except Exception:
            return []

    _syn_players = _synergy_player_list()

    if not _syn_players:
        st.info("Synergy play type data coming soon.")
    else:
        _syn_default = "Paolo Banchero" if "Paolo Banchero" in _syn_players else _syn_players[0]
        _syn_idx = _syn_players.index(_syn_default)

        _syn_col1, _syn_col2 = st.columns([2, 1])
        with _syn_col1:
            _syn_selected = st.selectbox(
                "Player:", _syn_players, index=_syn_idx, key="synergy_player_select"
            )
        with _syn_col2:
            _pos_options = ["Guard", "Wing", "Big"]
            try:
                _sc = sqlite3.connect("scouting_hub.db")
                _syn_pos_row = _sc.execute(
                    "SELECT position_group FROM player_positions WHERE player_name = ?",
                    (_syn_selected,)
                ).fetchone()
                _sc.close()
                _auto_pos = _syn_pos_row[0] if _syn_pos_row else "Wing"
            except Exception:
                _auto_pos = "Wing"
            _syn_pos = st.radio(
                "Position group:",
                _pos_options,
                index=_pos_options.index(_auto_pos),
                horizontal=True,
                key="synergy_pos_select"
            )

        _syn_events = _load_synergy_events(_syn_selected)
        _synergy_rows = get_synergy_playtype_rows(_syn_selected, _syn_pos)

        # ── HERO: what kind of player he is (how he scores) and his best shot types ──
        if _synergy_rows:
            _by_usage = sorted(_synergy_rows, key=lambda r: r[1] or 0, reverse=True)
            _lead, _second = _by_usage[0], (_by_usage[1] if len(_by_usage) > 1 else None)
            _lead_pct = _lead[1] or 0
            _second_pct = (_second[1] or 0) if _second else 0
            # Within 3 points of possession share counts as "dead even" - call out both
            # play types instead of picking a single "most-used" that overstates the gap.
            if _second is not None and abs(_lead_pct - _second_pct) <= 0.03:
                _style_desc = f"{_lead[0]} / {_second[0]} Scorer"
            else:
                _style_desc = f"{_lead[0]} Scorer"

            # Best shot types = highest FG% percentile among play types with real volume
            # (so a 2-for-3 flash of efficiency doesn't outrank his actual bread and butter).
            _efficiency_candidates = []
            for label, time_pct, stat_rows in _synergy_rows:
                _fg = next((s for s in stat_rows if s[0] == "FG%"), None)
                _poss = next((s for s in stat_rows if s[0] == "Poss"), None)
                if _fg and _fg[2] is not None and _poss and (_poss[1] or 0) >= 15:
                    _efficiency_candidates.append((label, _fg[1], _fg[2]))
            _efficiency_candidates.sort(key=lambda x: x[2], reverse=True)
            _best_shot_types = _efficiency_candidates[:3]

            _lead_fg = next((s for s in _lead[2] if s[0] == "FG%"), None)
            _hero2_bg, _hero2_fg = pct_color(_lead_fg[2] if _lead_fg else None)

            if _best_shot_types:
                _tags_html = "".join(
                    f"<span style='background:rgba(255,255,255,0.22);border:1px solid rgba(255,255,255,0.4);"
                    f"color:{_hero2_fg};padding:5px 12px;border-radius:20px;font-size:0.78rem;font-weight:800;"
                    f"margin:2px 6px 2px 0;display:inline-block;'>Best: {t_label} ({t_fg:.0f}% FG, "
                    f"{ordinal(t_pct)} pct)</span>"
                    for t_label, t_fg, t_pct in _best_shot_types
                )
            else:
                _tags_html = (
                    f"<span style='color:{_hero2_fg};opacity:0.8;font-size:0.85rem;'>"
                    f"No play type has enough volume yet to call out a best shot type.</span>"
                )

            st.markdown(
                f"<div style='background:{_hero2_bg};border-radius:14px;padding:18px 24px;margin:14px 0 18px;"
                f"display:flex;align-items:center;gap:26px;flex-wrap:wrap;'>"
                f"<div style='flex-shrink:0;'>"
                f"<div style='font-size:2.0rem;font-weight:900;color:{_hero2_fg};line-height:1;'>{_style_desc}</div>"
                f"<div style='font-size:0.78rem;font-weight:700;color:{_hero2_fg};opacity:0.9;margin-top:4px;'>"
                f"How he scores, by usage share of his own possessions</div>"
                f"</div>"
                f"<div style='flex:1;min-width:220px;'>{_tags_html}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        # ── SECTION: Play Types ────────────────────────────────────────────
        st.markdown("---")
        st.markdown("#### Play Type Breakdown")
        if True:

            if _synergy_rows:
                st.caption(f"Percentiles vs. all {_syn_pos}s · 2021-22 NCAAMB")

                def _playtype_block_tab(pt_label, time_pct, stat_rows):
                    time_str = f"{time_pct * 100:.1f}%" if time_pct is not None else "-"
                    # "Poss" percentile doubles as "how often, relative to peers" - surface it
                    # right under the big possession number instead of only in the row below.
                    _poss_stat = next((s for s in stat_rows if s[0] == "Poss"), None)
                    _usage_pct = _poss_stat[2] if _poss_stat else None
                    usage_pct_str = f"{ordinal(_usage_pct)} percentile usage" if _usage_pct is not None else ""
                    header = (
                        f"<div style='margin-bottom:10px'>"
                        f"<div style='font-size:0.95rem;font-weight:900;text-transform:uppercase;"
                        f"letter-spacing:0.06em;color:#111;'>{pt_label}</div>"
                        f"<div style='display:flex;align-items:baseline;gap:8px;border-bottom:2px solid #ddd;"
                        f"padding-bottom:4px;'>"
                        f"<span style='font-size:1.7rem;font-weight:900;color:#111;line-height:1.1;'>{time_str}</span>"
                        f"<span style='font-size:0.72rem;font-weight:600;color:#666;'>of possessions"
                        f"{' &middot; ' + usage_pct_str if usage_pct_str else ''}</span>"
                        f"</div></div>"
                    )
                    rows_html = []
                    for sl, v, p, sfx, d in stat_rows:
                        bg, bubble_fg = pct_color(p)
                        disp = f"{v:.{d}f}" if v is not None else "-"
                        val_str = f"{disp}{sfx}" if disp != "-" else "-"
                        pct_str = f"<span style='font-size:0.68rem;font-weight:700;color:#666;margin-left:6px'>" \
                                  f"({ordinal(p)} pct)</span>" if p is not None else ""
                        if p is not None:
                            fill_w = f"{p:.1f}%"
                            bubble = (
                                f"<div style='position:absolute;top:50%;left:{fill_w};transform:translate(-50%,-50%);"
                                f"background:{bg};color:{bubble_fg};font-size:0.62rem;font-weight:900;border-radius:50%;"
                                f"width:20px;height:20px;display:flex;align-items:center;justify-content:center;"
                                f"z-index:2;border:1.5px solid rgba(0,0,0,0.25)'>{p:.0f}</div>"
                            )
                            fill = f"<div style='position:absolute;top:0;left:0;height:100%;width:{fill_w};background:{bg};border-radius:4px'></div>"
                        else:
                            fill = bubble = ""
                        rows_html.append(
                            f"<div style='display:flex;align-items:center;margin-bottom:6px;gap:10px'>"
                            f"<span style='font-size:0.82rem;font-weight:800;color:#111;min-width:72px;text-align:right;flex-shrink:0'>{sl}</span>"
                            f"<div style='flex:1;position:relative;height:20px;border-radius:4px;overflow:visible;background:#e0e0e0'>"
                            f"{fill}{bubble}</div>"
                            f"<span style='font-size:0.95rem;font-weight:900;color:#111;min-width:42px;text-align:right;flex-shrink:0'>{val_str}</span>"
                            f"{pct_str}"
                            f"</div>"
                        )
                    return f"<div style='margin-bottom:20px'>{header}{''.join(rows_html)}</div>"

                _synergy_rows_sorted = sorted(_synergy_rows, key=lambda r: r[1] or 0, reverse=True)
                half = math.ceil(len(_synergy_rows_sorted) / 2)

                _pt_left, _pt_right = st.columns(2)
                with _pt_left:
                    st.markdown(
                        "".join(_playtype_block_tab(*r) for r in _synergy_rows_sorted[:half]),
                        unsafe_allow_html=True
                    )
                with _pt_right:
                    st.markdown(
                        "".join(_playtype_block_tab(*r) for r in _synergy_rows_sorted[half:]),
                        unsafe_allow_html=True
                    )
            else:
                st.info(f"No Synergy play type data found for {_syn_selected}.")

        # ── VIEW: Shot Chart ───────────────────────────────────────────────
        # ── SECTION: Shot Chart ────────────────────────────────────────────
        st.markdown("---")
        st.markdown("#### Shot Chart")
        if True:
            _shot_evts = [e for e in _syn_events if e["is_shot"]]
            if not _shot_evts:
                st.info("No shot data found.")
            else:
                _sc_col1, _sc_col2 = st.columns([3, 1])
                with _sc_col2:
                    _pt_filter_opts = ["All"] + list({
                        t for e in _shot_evts for t in e["tags"]
                        if t in ["PandRBallHandler","Iso","PostUp","SpotUp","Cut","OffScreen","HandOff","Transition","PandRRollMan","Post_Up","Spot_Up"]
                    })
                    _pt_filter_map = {
                        "PandRBallHandler": "P&R Ball Handler", "Iso": "Isolation", "ISO": "Isolation",
                        "PostUp": "Post Up", "Post_Up": "Post Up", "SpotUp": "Spot Up", "Spot_Up": "Spot Up",
                        "Cut": "Cut", "OffScreen": "Off Screen", "HandOff": "Hand Off",
                        "Transition": "Transition", "PandRRollMan": "P&R Roll Man",
                    }
                    _pt_filter = st.selectbox("Play type:", ["All"] + sorted({
                        _pt_filter_map.get(t, t) for t in _pt_filter_opts if t != "All"
                    }), key="syn_shot_pt_filter")
                    _coverage_filter = st.radio("Coverage:", ["All", "Open", "Guarded", "Defense Commits"], key="syn_cov_filter")
                    _show_made = st.checkbox("Made", value=True, key="syn_show_made")
                    _show_miss = st.checkbox("Missed", value=True, key="syn_show_miss")

                _reverse_pt_map = {v: k for k, v in _pt_filter_map.items()}
                _pt_keys = [_reverse_pt_map.get(_pt_filter, _pt_filter)] if _pt_filter != "All" else None
                _cov_map = {"Open": "Open", "Guarded": "Guarded", "Defense Commits": "DefenseCommits"}

                _filtered = []
                for e in _shot_evts:
                    if _pt_keys and not any(k in e["tags"] for k in _pt_keys + [_pt_filter]):
                        continue
                    if _coverage_filter != "All" and _cov_map[_coverage_filter] not in e["tags"]:
                        continue
                    if e["made"] and not _show_made:
                        continue
                    if not e["made"] and not _show_miss:
                        continue
                    _filtered.append(e)

                with _sc_col1:
                    _fig_sc, _ax_sc = plt.subplots(figsize=(6, 5))
                    _ax_sc.set_facecolor("#f8f8f8")
                    _fig_sc.patch.set_facecolor("#f8f8f8")
                    _draw_half_court(_ax_sc)

                    for e in _filtered:
                        if e["x"] is None or e["y"] is None:
                            continue
                        # Synergy coords: origin at center, y positive toward basket
                        # Convert: x in [-250,250] (tenths of feet from center), y in [-36,458]
                        px = e["x"] / 10.0 + 25.0   # shift to 0-50 ft
                        py = e["y"] / 10.0 + 5.25   # shift so basket = 5.25
                        if py < 0 or py > 47:
                            continue
                        color = "#F2A900" if e["made"] else "#2D68C4"
                        marker = "o" if not e["is3"] else "^"
                        _ax_sc.scatter(px, py, c=color, s=18, alpha=0.7,
                                       marker=marker, linewidths=0.3, edgecolors="white", zorder=3)

                    total = len(_filtered)
                    made_count = sum(1 for e in _filtered if e["made"])
                    fg_pct = made_count / total * 100 if total else 0
                    _ax_sc.set_xlim(0, 50)
                    _ax_sc.set_ylim(0, 47)
                    _ax_sc.axis("off")
                    _ax_sc.set_title(
                        f"{_syn_selected} · {_pt_filter} · {total} shots · {fg_pct:.1f}% FG",
                        fontsize=13, fontweight="bold", pad=10
                    )
                    from matplotlib.lines import Line2D
                    legend_els = [
                        Line2D([0],[0], marker='o', color='w', markerfacecolor='#F2A900', markersize=10, label='Made 2pt'),
                        Line2D([0],[0], marker='^', color='w', markerfacecolor='#F2A900', markersize=10, label='Made 3pt'),
                        Line2D([0],[0], marker='o', color='w', markerfacecolor='#2D68C4', markersize=10, label='Miss 2pt'),
                        Line2D([0],[0], marker='^', color='w', markerfacecolor='#2D68C4', markersize=10, label='Miss 3pt'),
                    ]
                    _ax_sc.legend(handles=legend_els, loc="upper right", fontsize=10, framealpha=0.9)
                    st.pyplot(_fig_sc, use_container_width=True)
                    plt.close(_fig_sc)

                    # Shot zone frequency table
                    _zone_map = [
                        ("At Basket", "AtBasket"),
                        ("Short (<4ft)", "Short"),
                        ("Mid (4-17ft)", "Shortto17"),
                        ("Mid-Long (17ft-3pt)", "Medium17to3pt"),
                        ("Long 3pt", "Long3pt"),
                        ("Deep 3pt", "Long"),
                    ]
                    _zone_rows = []
                    for zlabel, ztag in _zone_map:
                        ze = [e for e in _filtered if ztag in e["tags"]]
                        if not ze:
                            continue
                        zm = sum(1 for e in ze if e["made"])
                        _zone_rows.append({
                            "Zone": zlabel,
                            "Att": len(ze),
                            "Freq%": f"{len(ze)/total*100:.1f}%" if total else "-",
                            "FG%": f"{zm/len(ze)*100:.1f}%",
                        })
                    if _zone_rows:
                        st.caption("Shot zone breakdown")
                        st.dataframe(pd.DataFrame(_zone_rows), hide_index=True, use_container_width=True)

        # ── VIEW: Tendencies ───────────────────────────────────────────────
        # ── SECTION: Tendencies ────────────────────────────────────────────
        st.markdown("---")
        st.markdown("#### Tendencies")

        def _tend_bar_block(title, rows, count_label):
            """Same bar-and-bubble visual language as the Play Type Breakdown above,
            instead of a plain bordered table - bar width is share of use (Freq%),
            color is shooting efficiency (FG%) on the site's blue-grey-gold scale."""
            if not rows:
                return ""
            header = (
                f"<div style='font-size:0.85rem;font-weight:900;text-transform:uppercase;"
                f"letter-spacing:0.06em;color:#111;border-bottom:2px solid #ddd;"
                f"padding-bottom:3px;margin-bottom:8px'>{title}</div>"
            )
            bars = []
            for r in rows:
                fg = r.get("fg")
                freq = r.get("freq")
                bg, fg_color = pct_color(fg) if fg is not None else ("#EAECF0", "#64748B")
                fill_w = f"{freq:.1f}%" if freq is not None else "0%"
                fg_str = f"{fg:.1f}% FG" if fg is not None else "-"
                bars.append(
                    f"<div style='display:flex;align-items:center;margin-bottom:8px;gap:10px'>"
                    f"<span style='font-size:0.78rem;font-weight:800;color:#111;min-width:118px;"
                    f"text-align:right;flex-shrink:0'>{r['label']}</span>"
                    f"<div style='flex:1;position:relative;height:22px;border-radius:5px;"
                    f"overflow:hidden;background:#e9edf3'>"
                    f"<div style='position:absolute;top:0;left:0;height:100%;width:{fill_w};"
                    f"background:{bg};'></div>"
                    f"<div style='position:relative;height:100%;display:flex;align-items:center;"
                    f"padding-left:8px;font-size:0.68rem;font-weight:700;color:#0F172A;'>"
                    f"{r['count']} {count_label}</div></div>"
                    f"<span style='font-size:0.76rem;font-weight:800;color:{fg_color};background:{bg};"
                    f"padding:2px 8px;border-radius:4px;min-width:70px;text-align:center;"
                    f"flex-shrink:0'>{fg_str}</span>"
                    f"</div>"
                )
            return f"<div style='margin-bottom:20px'>{header}{''.join(bars)}</div>"

        if not _syn_events:
            st.info("No event data found.")
        else:
            _tend_col1, _tend_col2 = st.columns(2)

            with _tend_col1:
                # Drive directions
                _drive_tags = [("Left", "DrivesLeft"), ("Right", "DrivesRight"),
                               ("Straight", "DrivesStraight"), ("Baseline", "DriveBaseline"),
                               ("Middle", "DriveMiddle")]
                _drive_data = []
                for label, tag in _drive_tags:
                    count = sum(1 for e in _syn_events if tag in e["tags"])
                    if count:
                        _shot_w_tag = [e for e in _syn_events if tag in e["tags"] and e["is_shot"]]
                        _made_w_tag = sum(1 for e in _shot_w_tag if e["made"])
                        _drive_data.append({
                            "label": label, "count": count,
                            "fg": (_made_w_tag / len(_shot_w_tag) * 100) if _shot_w_tag else None,
                        })
                if _drive_data:
                    _total_drives = sum(d["count"] for d in _drive_data)
                    for d in _drive_data:
                        d["freq"] = d["count"] / _total_drives * 100
                st.markdown(_tend_bar_block("Drive Direction", _drive_data, "poss"), unsafe_allow_html=True)

                # P&R tendencies
                _pnr_tags = [("High P&R", "HighPandR"), ("Left P&R", "LeftPandR"),
                             ("Right P&R", "RightPandR"), ("Slips Pick", "SlipsthePick"),
                             ("Pick & Pop", "PickandPops"), ("Rolls to Basket", "RollstoBasket"),
                             ("Goes Away", "GoAwayfromPick"), ("Dribble Off Pick", "DribbleOffPick")]
                _pnr_data = []
                for label, tag in _pnr_tags:
                    count = sum(1 for e in _syn_events if tag in e["tags"])
                    if count:
                        _s = [e for e in _syn_events if tag in e["tags"] and e["is_shot"]]
                        _m = sum(1 for e in _s if e["made"])
                        _pnr_data.append({
                            "label": label, "count": count,
                            "fg": (_m / len(_s) * 100) if _s else None,
                        })
                if _pnr_data:
                    _total_pnr = sum(d["count"] for d in _pnr_data)
                    for d in _pnr_data:
                        d["freq"] = d["count"] / _total_pnr * 100
                st.markdown(_tend_bar_block("P&R Tendencies", _pnr_data, "poss"), unsafe_allow_html=True)

            with _tend_col2:
                # Coverage breakdown
                _cov_tags = [("Open", "Open"), ("Guarded", "Guarded"), ("Defense Commits", "DefenseCommits")]
                _cov_data = []
                for label, tag in _cov_tags:
                    evts = [e for e in _syn_events if tag in e["tags"] and e["is_shot"]]
                    if evts:
                        made = sum(1 for e in evts if e["made"])
                        _cov_data.append({"label": label, "count": len(evts), "fg": made / len(evts) * 100})
                if _cov_data:
                    total_cov = sum(d["count"] for d in _cov_data)
                    for d in _cov_data:
                        d["freq"] = d["count"] / total_cov * 100
                st.markdown(_tend_bar_block("Coverage", _cov_data, "shots"), unsafe_allow_html=True)

                # Post-up sub-tendencies
                _post_tags = [("Left Block", "LeftBlock"), ("Right Block", "RightBlock"),
                              ("Left Shoulder", "LeftShoulder"), ("Right Shoulder", "RightShoulder"),
                              ("Left Wing", "LeftWing"), ("Right Wing", "RightWing")]
                _post_data = []
                for label, tag in _post_tags:
                    evts = [e for e in _syn_events if tag in e["tags"] and e["is_shot"]]
                    if evts:
                        made = sum(1 for e in evts if e["made"])
                        _post_data.append({"label": label, "count": len(evts), "fg": made / len(evts) * 100})
                if _post_data:
                    total_post = sum(d["count"] for d in _post_data)
                    for d in _post_data:
                        d["freq"] = d["count"] / total_post * 100
                st.markdown(_tend_bar_block("Post Location", _post_data, "shots"), unsafe_allow_html=True)

                # Shot creation
                _create_tags = [("Off Dribble", "DribbleJumper"), ("Catch & Shoot", "NoDribbleJumper"),
                                ("Dribble Move", "DribbleMove"), ("From Stationary", "FromStationary"),
                                ("Early Jumper", "EarlyJumper"), ("Transition Leak", "LeakOuts"),
                                ("Trailer", "Trailer")]
                _create_data = []
                for label, tag in _create_tags:
                    evts = [e for e in _syn_events if tag in e["tags"] and e["is_shot"]]
                    if evts:
                        made = sum(1 for e in evts if e["made"])
                        _create_data.append({"label": label, "count": len(evts), "fg": made / len(evts) * 100})
                if _create_data:
                    total_create = sum(d["count"] for d in _create_data)
                    for d in _create_data:
                        d["freq"] = d["count"] / total_create * 100
                st.markdown(_tend_bar_block("Shot Creation", _create_data, "shots"), unsafe_allow_html=True)

            # Situational
            st.markdown("**Situational**")
            _sit_col1, _sit_col2, _sit_col3, _sit_col4 = st.columns(4)
            _sit_checks = [
                ("vs Zone", "zone"), ("Short Clock", "short_clock"),
            ]
            for (label, key), col in zip(_sit_checks, [_sit_col1, _sit_col2]):
                evts = [e for e in _syn_events if e[key] and e["is_shot"]]
                total = len(evts)
                made = sum(1 for e in evts if e["made"])
                with col:
                    st.metric(label, f"{made/total*100:.1f}% FG" if total else "-",
                              delta=f"{total} shots", delta_color="off")

            # Transition breakdown
            _trans_tags = [("Leak Out", "LeakOuts"), ("Trailer", "Trailer"),
                           ("Early Jumper", "EarlyJumper"), ("Takes Early Jumper", "TakesEarlyJumpShot")]
            _trans_data = []
            for label, tag in _trans_tags:
                evts = [e for e in _syn_events if tag in e["tags"] and e["is_shot"]]
                if evts:
                    made = sum(1 for e in evts if e["made"])
                    _trans_data.append({"label": label, "count": len(evts), "fg": made / len(evts) * 100})
            if _trans_data:
                _total_trans = sum(d["count"] for d in _trans_data)
                for d in _trans_data:
                    d["freq"] = d["count"] / _total_trans * 100
                st.markdown(_tend_bar_block("Transition Sub-Types", _trans_data, "shots"), unsafe_allow_html=True)
            else:
                st.caption("No transition sub-type data.")

        # ── VIEW: Matchup Defense ──────────────────────────────────────────
        # ── SECTION: Matchup Defense ───────────────────────────────────────
        st.markdown("---")
        st.markdown("#### Matchup Defense")
        if True:
            st.caption("Players who defended this player - PPP allowed, shots faced")
            _def_evts = [e for e in _syn_events if e["defender"] and e["is_shot"]]
            if not _def_evts:
                st.info("No defensive matchup data found.")
            else:
                from collections import defaultdict
                _def_stats = defaultdict(lambda: {"shots": 0, "made": 0, "pts": 0})
                for e in _def_evts:
                    d = e["defender"]
                    _def_stats[d]["shots"] += 1
                    if e["made"]:
                        _def_stats[d]["made"] += 1
                        _def_stats[d]["pts"] += 3 if e["is3"] else 2
                _def_rows = []
                for defender, s in _def_stats.items():
                    if s["shots"] < 2:
                        continue
                    _def_rows.append({
                        "Defender": defender,
                        "Shots Faced": s["shots"],
                        "FG%": round(s["made"] / s["shots"] * 100, 1),
                        "PPP Allowed": round(s["pts"] / s["shots"], 3),
                    })
                _def_rows.sort(key=lambda x: x["Shots Faced"], reverse=True)
                st.dataframe(
                    pd.DataFrame(_def_rows),
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "FG%": st.column_config.NumberColumn("FG%", format="%.1f%%"),
                        "PPP Allowed": st.column_config.NumberColumn("PPP Allowed", format="%.3f"),
                    }
                )


# ==========================================
# TAB: INTERNATIONAL PLAYERS
# ==========================================
_INTL_TEMPS = ["Yes", "See More", "Doubtful"]
_INTL_TEMP_COLORS = {"Yes": ("#15803D", "#FFFFFF"), "See More": ("#92600A", "#FFFFFF"), "Doubtful": ("#DC2626", "#FFFFFF")}


with tab_intl:
    st.subheader("International Players")

    _intl_conn = sqlite3.connect('scouting_hub.db')
    _intl_df = pd.read_sql_query("SELECT * FROM international_players ORDER BY player_name", _intl_conn)
    _intl_conn.close()

    if _intl_df.empty:
        st.info("No international players logged yet - add one below.")
    else:
        _intl_col_f1, _intl_col_f2, _intl_col_f3, _intl_col_f4, _intl_col_f5 = st.columns([1, 1, 1, 1, 1.3])
        with _intl_col_f1:
            _intl_countries = sorted(_intl_df["country"].dropna().unique().tolist())
            _intl_country_filter = st.multiselect("Filter by country:", _intl_countries, default=[])
        with _intl_col_f2:
            # Position is a mix of two conventions depending on which board a player came
            # from: older entries use the classic 1-5 numeric codes, newer ones (26.08.18
            # board) use section labels (ON BALL GUARD, COMBO GUARD, WING, FOURS, BIGS,
            # SHOOTING BIGS) - offer whichever values actually appear in the data, in a
            # sensible position order rather than alphabetical.
            _intl_pos_order = ["1", "ON BALL GUARD", "2", "COMBO GUARD", "3", "WING",
                                "4", "FOURS", "5", "BIGS", "SHOOTING BIGS"]
            _intl_pos_present = {p for v in _intl_df["position"].dropna() for p in str(v).split("/")}
            _intl_pos_options = [p for p in _intl_pos_order if p in _intl_pos_present] + \
                sorted(_intl_pos_present - set(_intl_pos_order))
            _intl_position_filter = st.multiselect("Filter by position:", _intl_pos_options, default=[])
        with _intl_col_f3:
            # Split combo values ("2027/2028") into individual years so the dropdown
            # offers clean single-year options instead of the raw combo strings.
            _intl_classes = sorted({y for c in _intl_df["class_yr"].dropna() for y in str(c).split("/") if y})
            _intl_class_filter = st.multiselect("Filter by class:", _intl_classes, default=[])
        with _intl_col_f4:
            _intl_temp_filter = st.multiselect("Filter by temperature:", _INTL_TEMPS, default=[])
        with _intl_col_f5:
            _intl_action_names = sorted(_intl_df["player_name"].tolist())
            _intl_action_pick = st.selectbox(
                "Search a player (Big Board / Alignment Survey):",
                _intl_action_names, key="intl_action_pick",
            )

        _intl_action_row = _intl_df[_intl_df["player_name"] == _intl_action_pick].iloc[0]
        _intl_c1, _intl_c2 = st.columns(2)
        with _intl_c1:
            if st.button("+ Add to Big Board", key="intl_add_board"):
                conn = sqlite3.connect('scouting_hub.db')
                cursor = conn.cursor()
                cursor.execute('''
                               INSERT INTO player_notes (player_name, team_name, position, agent, notes,
                                                         priority_tier, value_tag, eval_date)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(player_name) DO
                               UPDATE SET
                                   team_name=excluded.team_name, position=excluded.position,
                                   agent=excluded.agent, notes=excluded.notes
                               ''',
                               (_intl_action_row["player_name"], _intl_action_row["country"],
                                _intl_pos_to_board(_intl_action_row["position"]), _intl_action_row["agent"],
                                _intl_action_row["notes"], "Mid Priority", "Properly Valued",
                                datetime.now().strftime("%Y-%m-%d")))
                conn.commit()
                conn.close()
                st.success(f"{_intl_action_row['player_name']} added to the Front Office Target Board.")
        with _intl_c2:
            if st.button("+ Start Alignment Survey", key="intl_start_survey"):
                # No prefill - jumps to the survey tab, where this player is searchable
                # under "Auto-fill from a tracked player" (tagged " (Intl)") since
                # international players are now included in that list.
                st.session_state.go_to_tab = _TAB_INDEX["Recruit Alignment Survey"]
                st.rerun()

        st.divider()

        _intl_shown = _intl_df.copy()
        if _intl_country_filter:
            _intl_shown = _intl_shown[_intl_shown["country"].isin(_intl_country_filter)]
        if _intl_position_filter:
            _intl_wanted_pos = set(_intl_position_filter)
            _intl_shown = _intl_shown[_intl_shown["position"].fillna("").map(
                lambda p: bool(_intl_wanted_pos & set(str(p).split("/")))
            )]
        if _intl_class_filter:
            # Same combo handling as position - a class of "2027/2028" should match a
            # filter for either 2027 or 2028, not just an exact string match.
            _intl_wanted_class = set(_intl_class_filter)
            _intl_shown = _intl_shown[_intl_shown["class_yr"].fillna("").map(
                lambda c: bool(_intl_wanted_class & set(str(c).split("/")))
            )]
        if _intl_temp_filter:
            _intl_shown = _intl_shown[_intl_shown["temperature"].isin(_intl_temp_filter)]

        _intl_temp_order = {"Yes": 0, "See More": 1, "Doubtful": 2}
        _intl_shown = _intl_shown.assign(
            _sort=_intl_shown["temperature"].map(_intl_temp_order).fillna(3),
            # Whoever's picked in "Search a player" above floats to row 1, ahead of the
            # normal temperature sort, so searching actually surfaces them instead of
            # leaving them wherever they'd normally fall in the table.
            _pinned=(_intl_shown["player_name"] != _intl_action_pick).astype(int),
        ).sort_values(["_pinned", "_sort", "player_name"]).drop(columns=["_sort", "_pinned"])

        def _intl_temp_style(col):
            styles = []
            for val in col:
                bg, fg = _INTL_TEMP_COLORS.get(val, ("#EAECF0", "#1A1A1A"))
                styles.append(f"background-color:{bg};color:{fg};font-weight:700;")
            return styles

        _intl_display = _intl_shown[[
            "player_name", "country", "height", "position", "age", "class_yr",
            "temperature", "agent", "notes", "profile_url",
        ]].rename(columns={
            "player_name": "Player", "country": "Country", "height": "Height", "position": "POS",
            "age": "Age", "class_yr": "Class", "temperature": "Temperature", "agent": "Agent",
            "notes": "Notes", "profile_url": "Profile",
        })
        # Format Age as a plain string ourselves (blank for unknown ages) instead of
        # leaving it numeric - passed through a Styler below, a raw NaN/None renders as
        # the literal text "None" rather than blanking out automatically.
        _intl_display["Age"] = pd.to_numeric(_intl_display["Age"], errors="coerce").map(
            lambda v: f"{v:.1f}" if pd.notna(v) else ""
        )
        _intl_text_cols = ["Player", "Country", "Height", "POS", "Class", "Temperature",
                            "Agent", "Notes", "Profile"]
        _intl_display[_intl_text_cols] = _intl_display[_intl_text_cols].fillna("")
        _intl_styled = _intl_display.style.apply(_intl_temp_style, subset=["Temperature"])
        st.dataframe(
            _intl_styled,
            hide_index=True,
            use_container_width=True,
            height=460,
            column_config={
                "Notes": st.column_config.TextColumn("Notes", width="large"),
                "Profile": st.column_config.LinkColumn("Profile", display_text="Open"),
            },
        )

    st.divider()

    with st.expander("+ Add / Edit International Player", expanded=False):
        _intl_existing = sorted(_intl_df["player_name"].tolist()) if not _intl_df.empty else []
        _intl_pick = st.selectbox("Load existing player to edit:", ["+ New Player"] + _intl_existing,
                                   key="intl_edit_pick")

        _intl_saved = None
        if _intl_pick != "+ New Player":
            _intl_saved = _intl_df[_intl_df["player_name"] == _intl_pick].iloc[0].to_dict()

        def _iv(key, default=""):
            v = _intl_saved.get(key) if _intl_saved else None
            return v if v not in (None, "", "nan") else default

        _ikey = _intl_pick

        _ic1, _ic2, _ic3 = st.columns(3)
        with _ic1:
            _i_name = st.text_input("Player Name:", value=_iv("player_name"), key=f"intl_name_{_ikey}")
        with _ic2:
            _i_country = st.text_input("Country / Team:", value=_iv("country"), key=f"intl_country_{_ikey}")
        with _ic3:
            _i_height = st.text_input("Height:", value=_iv("height"), key=f"intl_height_{_ikey}")

        _ic4, _ic5, _ic6 = st.columns(3)
        with _ic4:
            _i_pos = st.text_input("Position:", value=_iv("position"), key=f"intl_pos_{_ikey}")
        with _ic5:
            try:
                _i_age_default = float(_iv("age", 17.5))
            except (TypeError, ValueError):
                _i_age_default = 17.5
            _i_age = st.number_input("Age:", value=_i_age_default, min_value=14.0, max_value=25.0,
                                      step=0.1, format="%.1f", key=f"intl_age_{_ikey}")
        with _ic6:
            _i_class = st.text_input("Class Year:", value=_iv("class_yr"), key=f"intl_class_{_ikey}")

        _ic7, _ic8 = st.columns(2)
        with _ic7:
            _i_temp_default = _iv("temperature") or "See More"
            _i_temp = st.radio("Temperature:", _INTL_TEMPS,
                               index=_INTL_TEMPS.index(_i_temp_default) if _i_temp_default in _INTL_TEMPS else 1,
                               horizontal=True, key=f"intl_temp_{_ikey}")
        with _ic8:
            _i_agent = st.text_input("Agent:", value=_iv("agent"), key=f"intl_agent_{_ikey}")

        _ic9, _ic10 = st.columns(2)
        with _ic9:
            _i_profile = st.text_input("Profile URL (optional):", value=_iv("profile_url"), key=f"intl_url_{_ikey}")
        with _ic10:
            _i_source = st.text_input("Source / Event:", value=_iv("source"), key=f"intl_source_{_ikey}")

        _i_scout = st.text_input("Scout Name:", value=_iv("scout_name"), key=f"intl_scout_{_ikey}")
        _i_notes = st.text_area("Notes:", value=_iv("notes"), height=140, key=f"intl_notes_{_ikey}")

        _isave_col, _idel_col = st.columns(2)
        with _isave_col:
            if st.button("Save Player", type="primary", key=f"intl_save_{_ikey}"):
                if not _i_name.strip():
                    st.error("Player Name is required.")
                else:
                    conn = sqlite3.connect('scouting_hub.db')
                    cursor = conn.cursor()
                    if _intl_pick != "+ New Player":
                        cursor.execute('''
                                       UPDATE international_players
                                       SET player_name=?, country=?, height=?, position=?, age=?, class_yr=?,
                                           temperature=?, agent=?, notes=?, profile_url=?, source=?,
                                           scout_name=?, eval_date=?
                                       WHERE player_name = ?
                                       ''',
                                       (_i_name, _i_country, _i_height, _i_pos, _i_age, _i_class, _i_temp,
                                        _i_agent, _i_notes, _i_profile, _i_source, _i_scout,
                                        datetime.now().strftime("%Y-%m-%d"), _intl_pick))
                    else:
                        cursor.execute('''
                                       INSERT INTO international_players
                                       (player_name, country, height, position, age, class_yr, temperature,
                                        agent, notes, profile_url, source, scout_name, eval_date)
                                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                       ''',
                                       (_i_name, _i_country, _i_height, _i_pos, _i_age, _i_class, _i_temp,
                                        _i_agent, _i_notes, _i_profile, _i_source, _i_scout,
                                        datetime.now().strftime("%Y-%m-%d")))
                    conn.commit()
                    conn.close()
                    st.success(f"Saved {_i_name}.")
                    st.rerun()
        with _idel_col:
            if _intl_pick != "+ New Player":
                if st.button("Delete Player", key=f"intl_delete_{_ikey}"):
                    conn = sqlite3.connect('scouting_hub.db')
                    conn.execute("DELETE FROM international_players WHERE player_name = ?", (_intl_pick,))
                    conn.commit()
                    conn.close()
                    st.success(f"Deleted {_intl_pick}.")
                    st.rerun()


# ==========================================
# TAB: PLAYER EVALUATIONS - search any player and pull up everything every coach has
# logged on them (Big Board status, representation notes, alignment survey, evaluation
# log) without paging through the full stats card. Same shared section as the bottom
# of Individual Player Stats.
# ==========================================
with tab_evals:
    st.subheader("Player Evaluations")
    st.caption("Search any player to see their Big Board status and every coach's evaluation on file.")

    _pe_opts = [None] + all_player_names
    _pe_external_nav = st.session_state.active_player != st.session_state.get("_pe_last_synced")
    if _pe_external_nav:
        if st.session_state.active_player in _pe_opts:
            st.session_state["pe_player_select"] = st.session_state.active_player
        st.session_state["_pe_last_synced"] = st.session_state.active_player
    _pe_pick = st.selectbox(
        "Search player:",
        _pe_opts,
        format_func=lambda x: "" if x is None else x,
        key="pe_player_select",
        label_visibility="collapsed",
        placeholder="Type a name...",
    )
    if _pe_pick:
        st.session_state.active_player = _pe_pick
        st.session_state["_pe_last_synced"] = _pe_pick

    if not _pe_pick:
        st.info("Search for a player above to see their evaluations.")
    else:
        st.markdown(f"### {_pe_pick}")
        render_player_notes_workspace(_pe_pick, key_prefix="pe")
