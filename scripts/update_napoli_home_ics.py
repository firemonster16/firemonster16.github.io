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

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())

def is_napoli(name: str) -> bool:
    return "napoli" in norm(name)

def get_competition_matches():
    url = f"https://api.football-data.org/v4/competitions/{COMPETITION_CODE}/matches"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json().get("matches", [])

def get_napoli_team_id():
    # trova un match dove Napoli è home/away e prendi l'id
    matches = get_competition_matches()
    for m in matches:
        h = m["homeTeam"]["name"]
        a = m["awayTeam"]["name"]
        if is_napoli(h):
            return m["homeTeam"]["id"]
        if is_napoli(a):
            return m["awayTeam"]["id"]
    raise SystemExit("Could not determine Napoli teamId from competition matches.")

def get_team_matches(team_id: int):
    # prendi tutte le partite del team in Serie A, con stati utili
    url = f"https://api.football-data.org/v4/teams/{team_id}/matches"
    params = {
        "competitions": COMPETITION_CODE,
        "status": "SCHEDULED,TIMED,FINISHED,POSTPONED"
    }
    r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("matches", [])

def is_time_tbd(dt_utc):
    return dt_utc.hour == 0 and dt_utc.minute == 0 and dt_utc.second == 0

def main():
    team_id = get_napoli_team_id()
    matches = get_team_matches(team_id)

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

        start_utc = parser.isoparse(utc_date)
        end_utc = start_utc + timedelta(hours=2)

        status = m.get("status", "")
        matchday = m.get("matchday")

        tbd = (status in ("SCHEDULED", "TIMED") and is_time_tbd(start_utc))

        match_id = m.get("id")
        uid = f"napoli-home-{match_id}@firemonster16"

        e = Event()
        e.uid = uid
        e.begin = start_utc
        e.end = end_utc
        e.location = "Stadio Diego Armando Maradona, Napoli"

        if tbd:
            e.name = f"NAPOLI vs {away} (ORARIO DA DEFINIRE)"
            e.description = f"Serie A - Giornata {matchday} - Status: {status} - ORARIO DA DEFINIRE"
        else:
            e.name = f"NAPOLI vs {away}"
            e.description = f"Serie A - Giornata {matchday} - Status: {status}"

        cal.events.add(e)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(cal.serialize())

if __name__ == "__main__":
    main()
