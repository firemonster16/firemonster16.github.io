import os
import re
import time
import requests
from datetime import timedelta
from dateutil import parser
from ics import Calendar, Event
from typing import Dict, Any, List, Optional, Tuple


BASE_URL = "https://v3.football.api-sports.io"
API_KEY = os.getenv("APIFOOTBALL_KEY")
if not API_KEY:
    raise SystemExit("Missing APIFOOTBALL_KEY secret")

HEADERS = {"x-apisports-key": API_KEY}

# --- Config squadre/calendari ---
# league_prefix: usato per filtrare i fixtures solo nella competizione voluta
TEAMS = [
    {
        "team_search": "Napoli",
        "league_prefix": "Serie A",
        "output": "calendario-napoli.ics",
        "summary_prefix": "NAPOLI",
        "home_only": True,
    },
    {
        "team_search": "Juve Stabia",
        "league_prefix": "Serie B",
        "output": "calendario-juvestabia.ics",
        "summary_prefix": "JUVE STABIA",
        "home_only": True,
    },
    {
        "team_search": "Casertana",
        # Serie C spesso appare come "Serie C - Girone C" ecc. => startswith "Serie C"
        "league_prefix": "Serie C",
        "output": "calendario-casertana.ics",
        "summary_prefix": "CASERTANA",
        "home_only": True,
    },
]

# Status utili per includere future + passate
# API-FOOTBALL usa status tipo: NS (not started), FT (finished), PST, CANC, etc.
ALLOWED_STATUSES = None  # None = prendi tutto e filtra per league; se vuoi, puoi limitare


def current_season_start_year() -> int:
    """
    API-FOOTBALL usa season = anno di inizio stagione (es. 2025 per 2025/26).
    Regola pratica: se mese >= 7 => season = anno corrente, altrimenti anno corrente - 1
    """
    import datetime
    now = datetime.datetime.utcnow()
    return now.year if now.month >= 7 else now.year - 1


def api_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{BASE_URL}{path}"
    r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    # Gestione rate limit soft
    if r.status_code == 429:
        # aspetta e riprova una volta
        time.sleep(2)
        r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def find_team_id(team_search: str) -> Tuple[int, str]:
    """
    Cerca team_id tramite endpoint /teams?search=...
    """
    data = api_get("/teams", {"search": team_search})
    resp = data.get("response", [])
    if not resp:
        raise SystemExit(f"Team not found via /teams search: {team_search}")

    # Pick migliore: match esatto se possibile
    wanted = normalize(team_search)
    best = resp[0]
    for item in resp:
        name = item.get("team", {}).get("name", "")
        if normalize(name) == wanted:
            best = item
            break

    team = best["team"]
    return int(team["id"]), team["name"]


def fetch_all_fixtures(team_id: int, season: int) -> List[Dict[str, Any]]:
    """
    Scarica tutte le fixtures del team per season.
    Gestisce pagination: response.paging.total
    """
    all_items: List[Dict[str, Any]] = []
    page = 1
    total_pages = 1

    while page <= total_pages:
        params = {"team": team_id, "season": season, "page": page}
        data = api_get("/fixtures", params)

        paging = data.get("paging") or {}
        total_pages = int(paging.get("total", 1))

        items = data.get("response", [])
        all_items.extend(items)
        page += 1

        # piccolo delay per stare tranquilli col free tier (10/min)
        time.sleep(0.2)

    return all_items


def league_matches_target(league_name: str, league_prefix: str) -> bool:
    # Match "prefix" per coprire casi tipo "Serie C - Girone C"
    return normalize(league_name).startswith(normalize(league_prefix))


def build_calendar_for_team(cfg: Dict[str, Any], fixtures: List[Dict[str, Any]]) -> Calendar:
    cal = Calendar()

    league_prefix = cfg["league_prefix"]
    home_only = cfg["home_only"]
    summary_prefix = cfg["summary_prefix"]
    team_search = cfg["team_search"]

    for item in fixtures:
        league = item.get("league", {})
        league_name = league.get("name", "")
        if not league_matches_target(league_name, league_prefix):
            continue

        fixture = item.get("fixture", {})
        teams = item.get("teams", {})
        home = teams.get("home", {})
        away = teams.get("away", {})

        home_name = home.get("name", "")
        away_name = away.get("name", "")

        # home_only: includi solo se il team cercato è la squadra di casa
        if home_only:
            if normalize(home_name).find(normalize(team_search)) == -1 and normalize(team_search) not in normalize(home_name):
                # fallback: usa flag winner? no; meglio match substring
                # Se non matcha, scarta
                continue

        # date ISO
        dt_str = fixture.get("date")
        if not dt_str:
            continue
        start = parser.isoparse(dt_str)  # timezone-aware
        end = start + timedelta(hours=2)

        fixture_id = fixture.get("id")
        if not fixture_id:
            continue

        # Venue
        venue = fixture.get("venue", {}) or {}
        venue_name = venue.get("name")
        venue_city = venue.get("city")
        location = None
        if venue_name and venue_city:
            location = f"{venue_name}, {venue_city}"
        elif venue_name:
            location = str(venue_name)

        # Status
        status = (fixture.get("status") or {}).get("short", "")
        # Title
        # Se home-only, titolo coerente "SQUADRA vs OSPITE"
        title = f"{summary_prefix} vs {away_name}"

        e = Event()
        e.uid = f"{normalize(summary_prefix).replace(' ','')}-home-{fixture_id}@firemonster16"
        e.name = title
        e.begin = start
        e.end = end
        if location:
            e.location = location

        round_name = league.get("round", "")
        e.description = f"{league_name} - {round_name} - Status: {status}"

        cal.events.add(e)

    return cal


def main():
    season = current_season_start_year()

    for cfg in TEAMS:
        team_id, team_real_name = find_team_id(cfg["team_search"])
        fixtures = fetch_all_fixtures(team_id, season)
        cal = build_calendar_for_team(cfg, fixtures)

        out = cfg["output"]
        with open(out, "w", encoding="utf-8") as f:
            f.write(cal.serialize())

        print(f"OK: wrote {out} for team='{team_real_name}' season={season} events={len(cal.events)}")


if __name__ == "__main__":
    main()
