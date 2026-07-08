"""
Scrape KenPom SOS (Strength of Schedule) rankings and save to scouting_hub.db.
Run: python3 build_kenpom_sos.py
"""
import re
import sqlite3
import requests
import urllib3

urllib3.disable_warnings()

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
KP_EMAIL = "Ngeorgeton@gmail.com"
KP_PASS  = "Bearcats1"


def scrape_kenpom_sos() -> list[dict]:
    CHROME = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    s = requests.Session()
    s.get("https://kenpom.com/", headers={**HEADERS, "User-Agent": CHROME}, verify=False, timeout=10)
    s.post(
        "https://kenpom.com/handlers/login_handler.php",
        data={"email": KP_EMAIL, "password": KP_PASS, "remember": "1", "submit": "Login!"},
        headers={**HEADERS, "User-Agent": CHROME, "Referer": "https://kenpom.com/",
                 "Content-Type": "application/x-www-form-urlencoded", "Origin": "https://kenpom.com"},
        verify=False, timeout=10,
    )
    # Session cookies are set regardless of the response text — verify by checking data access
    r = s.get("https://kenpom.com/", headers={**HEADERS, "User-Agent": CHROME}, verify=False, timeout=15)
    rows = re.findall(r"<tr[^>]*>.*?</tr>", r.text, re.DOTALL)

    results = []
    for row in rows:
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.DOTALL)
        clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        if len(clean) < 11:
            continue
        # Col 0=Rk, 1=Team, 2=Conf, 9=SOS NetRtg value, 14=SOS NetRtg national rank
        try:
            nat_rank = int(clean[0])
        except ValueError:
            continue
        team_raw = re.sub(r"\s*\d+$", "", clean[1]).strip()  # strip seed number
        try:
            sos_rank = int(clean[14])
            sos_value = float(clean[9])
        except (ValueError, IndexError):
            continue
        results.append({
            "kp_team": team_raw,
            "conf": clean[2],
            "sos_rank": sos_rank,
            "sos_value": sos_value,
        })

    return results


def save_to_db(rows: list[dict]):
    conn = sqlite3.connect("scouting_hub.db")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kenpom_sos (
            kp_team   TEXT PRIMARY KEY,
            conf      TEXT,
            sos_rank  INTEGER,
            sos_value REAL
        )
    """)
    conn.execute("DELETE FROM kenpom_sos")
    conn.executemany(
        "INSERT INTO kenpom_sos (kp_team, conf, sos_rank, sos_value) VALUES (:kp_team, :conf, :sos_rank, :sos_value)",
        rows,
    )
    conn.commit()
    conn.close()
    print(f"Saved {len(rows)} teams to kenpom_sos table.")


if __name__ == "__main__":
    print("Logging in to KenPom...")
    data = scrape_kenpom_sos()
    print(f"Scraped {len(data)} teams.")
    # Spot-check
    for row in data:
        if row["kp_team"] in ("UCLA", "Duke", "Michigan"):
            print(f"  {row['kp_team']}: SOS rank #{row['sos_rank']} ({row['sos_value']:+.2f})")
    save_to_db(data)
    print("Done.")
