import os
import re
import requests
from datetime import timedelta
from dateutil import parser
from ics import Calendar, Event
import pytz

TZ = pytz.timezone("Europe/Rome")

TOKEN = os.getenv("FOOTBALL_DATA_TOKEN")
if not TOKEN:
    raise SystemExit("Missing FOOTBALL_DATA_TOKEN secret")

HEADERS = {"X-Auth-Token": TOKEN}

# Serie A su football-data.org è tipicamente "SA"
COMPETITION_CODE = "SA"

# Match robusto sul nome (per evitare mismatch tipo "Napoli" vs "SSC Napoli")
def is_napoli(team_name: str) -> bool:
    t = re.sub(r"\s+", " ", team_name.strip().lower())
    return "napoli" in t  # prende "SSC Napoli", "Napoli", ecc.

def get_matches():
    url = f"https://api.football-data.org/v4/competitions/{COMPETITION_CODE}/matches"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json().get("matches", [])

def to_rome_dt(utc_iso: str):
    dt = parser.isoparse(utc_iso)
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(TZ)

def main():
    matches = get_matches()

    cal = Calendar()

    for m in matches:
        home = m["homeTeam"]["name"]
        away = m["awayTeam"]["name"]

        # SOLO Napoli in casa
        if not is_napoli(home):
            continue

        utc_date = m.get("utcDate")
        if not utc_date:
            continue

        start = to_rome_dt(utc_date)
        end = start + timedelta(hours=2)

        match_id = m.get("id")
        uid = f"napoli-home-{match_id}@firemonster16"

        e = Event()
        e.uid = uid
        e.name = f"NAPOLI vs {away}"
        e.begin = start
        e.end = end

        matchday = m.get("matchday")
        status = m.get("status", "")
        e.description = f"Serie A - Giornata {matchday} - Status: {status}"

        # spesso "venue" non c'è su football-data; se c'è lo mettiamo
        venue = m.get("venue")
        if venue:
            e.location = venue
        else:
            e.location = "Stadio Diego Armando Maradona, Napoli"

        cal.events.add(e)

    # IMPORTANTISSIMO: sovrascrive esattamente il file che hai nel repo
    with open("calendario-napoli.ics", "w", encoding="utf-8") as f:
        f.write(cal.serialize())

if __name__ == "__main__":
    main()
