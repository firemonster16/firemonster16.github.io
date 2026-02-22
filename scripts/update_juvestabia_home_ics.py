import os
import re
import requests
from datetime import timedelta
from dateutil import parser
from ics import Calendar, Event

TOKEN = os.getenv("FOOTBALL_DATA_TOKEN")
if not TOKEN:
    raise SystemExit("Missing FOOTBALL_DATA_TOKEN secret")

HEADERS = {"X-Auth-Token": TOKEN}

# Juve Stabia: di norma Serie B -> "SB"
COMPETITION_CODE = "SB"
OUTPUT_FILE = "calendario-juvestabia.ics"

def is_juvestabia(name: str) -> bool:
    t = re.sub(r"\s+", " ", name.strip().lower())
    # robusto su varianti tipo "Juve Stabia", "S.S. Juve Stabia", ecc.
    return ("juve stabia" in t) or ("j." in t and "stabia" in t)

def is_time_tbd(dt_utc):
    return dt_utc.hour == 0 and dt_utc.minute == 0 and dt_utc.second == 0

def get_matches():
    url = f"https://api.football-data.org/v4/competitions/{COMPETITION_CODE}/matches"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json().get("matches", [])

def main():
    matches = get_matches()
    cal = Calendar()

    for m in matches:
        home = m["homeTeam"]["name"]
        away = m["awayTeam"]["name"]

        # SOLO Juve Stabia in casa
        if not is_juvestabia(home):
            continue

        utc_date = m.get("utcDate")
        if not utc_date:
            continue

        start_utc = parser.isoparse(utc_date)  # timezone-aware (Z)
        end_utc = start_utc + timedelta(hours=2)

        status = m.get("status", "")
        matchday = m.get("matchday")
        tbd = (status == "SCHEDULED" and is_time_tbd(start_utc))

        match_id = m.get("id")
        uid = f"juvestabia-home-{match_id}@firemonster16"

        e = Event()
        e.uid = uid
        e.begin = start_utc
        e.end = end_utc
        e.location = m.get("venue") or "Stadio Romeo Menti, Castellammare di Stabia"

        if tbd:
            e.name = f"JUVE STABIA vs {away} (ORARIO DA DEFINIRE)"
            e.description = f"Serie B - Giornata {matchday} - Status: {status} - ORARIO DA DEFINIRE"
        else:
            e.name = f"JUVE STABIA vs {away}"
            e.description = f"Serie B - Giornata {matchday} - Status: {status}"

        cal.events.add(e)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(cal.serialize())

if __name__ == "__main__":
    main()
