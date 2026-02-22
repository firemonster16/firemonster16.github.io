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
COMPETITION_CODE = "SA"

OUTPUT_FILE = "calendario-napoli.ics"

def is_napoli(name: str) -> bool:
    t = re.sub(r"\s+", " ", name.strip().lower())
    return "napoli" in t

def get_matches():
    url = f"https://api.football-data.org/v4/competitions/{COMPETITION_CODE}/matches"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json().get("matches", [])

def is_time_tbd(dt_utc):
    # spesso 00:00Z = orario non ancora definito
    return dt_utc.hour == 0 and dt_utc.minute == 0 and dt_utc.second == 0

def main():
    matches = get_matches()

    cal = Calendar()
    cal.extra.append("CALSCALE:GREGORIAN")
    cal.extra.append("X-WR-CALNAME:Napoli (Casa) - Serie A")
    cal.extra.append("X-WR-TIMEZONE:Europe/Rome")

    for m in matches:
        home = m["homeTeam"]["name"]
        away = m["awayTeam"]["name"]

        # SOLO Napoli in casa
        if not is_napoli(home):
            continue

        utc_date = m.get("utcDate")
        if not utc_date:
            continue

        start_utc = parser.isoparse(utc_date)  # di solito timezone-aware (Z)

        # se SCHEDULED e orario TBD (00:00Z), salta finché non lo aggiornano
        if m.get("status") == "SCHEDULED" and is_time_tbd(start_utc):
            continue

        end_utc = start_utc + timedelta(hours=2)

        match_id = m.get("id")
        uid = f"napoli-home-{match_id}@firemonster16"

        e = Event()
        e.uid = uid
        e.name = f"NAPOLI vs {away}"
        e.begin = start_utc
        e.end = end_utc
        e.location = "Stadio Diego Armando Maradona, Napoli"

        matchday = m.get("matchday")
        status = m.get("status", "")
        e.description = f"Serie A - Giornata {matchday} - Status: {status}"

        cal.events.add(e)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(cal.serialize())

if __name__ == "__main__":
    main()
