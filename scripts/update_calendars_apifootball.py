import os
import time
import requests
from datetime import timedelta
from dateutil import parser
from ics import Calendar, Event
from typing import Dict, Any, List, Tuple


BASE_URL = "https://v3.football.api-sports.io"
API_KEY = os.getenv("APIFOOTBALL_KEY")
if not API_KEY:
    raise SystemExit("Missing APIFOOTBALL_KEY secret")

HEADERS = {"x-apisports-key": API_KEY}

TEAMS = [
    {
        "team_search": "Napoli",
        "league_prefix": "Serie A",          # usato solo come filtro "soft"
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
        "league_prefix": "Serie C",
        "output": "calendario-casertana.ics",
        "summary_prefix": "CASERTANA",
        "home_only": True,
    },
]

def current_season_start_year() -> int:
    # stagione calcistica: 2025/26 -> season=2025
    import datetime
    now = datetime.datetime.utcnow()
    return now.year if now.month >= 7 else now.year - 1

def api_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{BASE_URL}{path}"
    r = requests.get(url, headers=HEADERS, params=params, timeout=30)

    # basic rate-limit handling
    if r.status_code == 429:
        time.sleep(2)
        r = requests.get(url, headers=HEADERS, params=params, timeout=30)

    r.raise_for_status()
    return r.json()

def find_team_id(team_search: str) -> Tuple[int, str]:
    data = api_get("/teams", {"search": team_search})
    resp = data.get("response", [])
    if not resp:
        raise SystemExit(f"Team not found via /teams search: {team_search}")

    # prende il primo (di solito è quello giusto)
    team = resp[0]["team"]
    return int(team["id"]), team["name"]

def fetch_all_fixtures(team_id: int, season: int) -> List[Dict[str, Any]]:
    all_items: List[Dict[str, Any]] = []
    page = 1
    total_pages = 1

    while page <= total_pages:
        data = api_get("/fixtures", {"team": team_id, "season": season, "page": page})
        paging = data.get("paging") or {}
        total_pages = int(paging.get("total", 1))
        items = data.get("response", [])
        all_items.extend(items)
        page += 1
        time.sleep(0.2)

    return all_items

def startswith_ci(hay: str, pref: str) -> bool:
    return hay.strip().lower().startswith(pref.strip().lower())

def build_calendar(cfg: Dict[str, Any], team_id: int, fixtures: List[Dict[str, Any]]) -> Calendar:
    cal = Calendar()

    kept_total = 0
    kept_home = 0
    kept_league = 0

    for item in fixtures:
        league = item.get("league", {}) or {}
        league_name = league.get("name", "") or ""

        # filtro "soft" sulla lega (Serie A/B/C)
        # se vuoi disattivarlo: commenta queste 2 righe
        if cfg.get("league_prefix") and not startswith_ci(league_name, cfg["league_prefix"]):
            continue
        kept_league += 1

        teams = item.get("teams", {}) or {}
        home = teams.get("home", {}) or {}
        away = teams.get("away", {}) or {}

        home_id = home.get("id")
        away_name = away.get("name", "Unknown")

        # SOLO IN CASA: filtro robusto per ID
        if cfg.get("home_only", False):
            if int(home_id or -1) != int(team_id):
                continue
            kept_home += 1

        fixture = item.get("fixture", {}) or {}
        fixture_id = fixture.get("id")
        dt_str = fixture.get("date")

        if not fixture_id or not dt_str:
            continue

        start = parser.isoparse(dt_str)
        end = start + timedelta(hours=2)

        venue = fixture.get("venue", {}) or {}
        location = None
        if venue.get("name") and venue.get("city"):
            location = f"{venue['name']}, {venue['city']}"
        elif venue.get("name"):
            location = str(venue["name"])

        status_short = (fixture.get("status") or {}).get("short", "")
        round_name = league.get("round", "")

        e = Event()
        e.uid = f"{cfg['summary_prefix'].lower().replace(' ','')}-home-{fixture_id}@firemonster16"
        e.name = f"{cfg['summary_prefix']} vs {away_name}"
        e.begin = start
        e.end = end
        if location:
            e.location = location

        e.description = f"{league_name} - {round_name} - Status: {status_short}"
        cal.events.add(e)
        kept_total += 1

    print(
        f"[{cfg['team_search']}] fixtures={len(fixtures)} "
        f"after_league={kept_league} after_home={kept_home} events_written={kept_total}"
    )

    return cal

def main():
    season = current_season_start_year()
    print(f"Using season={season}")

    for cfg in TEAMS:
        team_id, team_real_name = find_team_id(cfg["team_search"])
        fixtures = fetch_all_fixtures(team_id, season)

        # DEBUG extra: mostra 5 nomi lega trovati (capire se matcha il filtro)
        leagues = []
        for it in fixtures[:50]:
            ln = (it.get("league", {}) or {}).get("name", "")
            if ln and ln not in leagues:
                leagues.append(ln)
            if len(leagues) >= 5:
                break
        print(f"[{cfg['team_search']}] team_id={team_id} team_name='{team_real_name}' sample_leagues={leagues}")

        cal = build_calendar(cfg, team_id, fixtures)

        with open(cfg["output"], "w", encoding="utf-8") as f:
            f.write(cal.serialize())

        print(f"OK wrote {cfg['output']}")

if __name__ == "__main__":
    main()
