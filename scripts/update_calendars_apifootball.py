import os
import time
import requests
from datetime import timedelta
from dateutil import parser
from ics import Calendar, Event


# ---------------------------
# CONFIG AUTH (API-SPORTS diretto O RapidAPI)
# ---------------------------
BASE_URL = "https://v3.football.api-sports.io"

APISPORTS_KEY = os.getenv("APIFOOTBALL_KEY")  # tua key
RAPIDAPI_HOST = os.getenv("RAPIDAPI_HOST")    # es: "api-football-v1.p.rapidapi.com" (solo se usi RapidAPI)

if not APISPORTS_KEY:
    raise SystemExit("Missing APIFOOTBALL_KEY secret")

HEADERS = {}
if RAPIDAPI_HOST:
    # Modalità RapidAPI
    BASE_URL = f"https://{RAPIDAPI_HOST}/v3"
    HEADERS["X-RapidAPI-Key"] = APISPORTS_KEY
    HEADERS["X-RapidAPI-Host"] = RAPIDAPI_HOST
else:
    # Modalità API-SPORTS diretta
    HEADERS["x-apisports-key"] = APISPORTS_KEY


COUNTRY = "Italy"

TEAMS = [
    {"team_search": "Napoli", "league_name": "Serie A", "output": "calendario-napoli.ics", "summary": "NAPOLI"},
    {"team_search": "Juve Stabia", "league_name": "Serie B", "output": "calendario-juvestabia.ics", "summary": "JUVE STABIA"},
    {"team_search": "Casertana", "league_name": "Serie C", "output": "calendario-casertana.ics", "summary": "CASERTANA"},
]


def season_start_year() -> int:
    # 2025/26 -> 2025
    import datetime
    now = datetime.datetime.utcnow()
    return now.year if now.month >= 7 else now.year - 1


def api_get(path: str, params: dict):
    url = f"{BASE_URL}{path}"
    r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    # rate-limit basic
    if r.status_code == 429:
        time.sleep(2)
        r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    # Debug error reporting (importantissimo)
    errs = data.get("errors")
    if errs:
        print(f"[API errors] path={path} params={params} errors={errs}")

    return data


def find_team_id(team_name: str) -> int:
    data = api_get("/teams", {"search": team_name})
    resp = data.get("response", [])
    if not resp:
        raise SystemExit(f"Team not found: {team_name}")
    return int(resp[0]["team"]["id"])


def find_league_id(league_name: str, season: int) -> int:
    """
    Cerca la lega in Italia per quella season.
    Per Serie C spesso il name è "Serie C" e i gironi sono nella field 'league'/'country'/'seasons' ecc.
    """
    data = api_get("/leagues", {"search": league_name, "country": COUNTRY, "season": season})
    resp = data.get("response", [])
    if not resp:
        raise SystemExit(f"League not found: {league_name} {COUNTRY} season={season}")

    # Prendi il primo risultato che matcha bene
    # (di solito è quello giusto: Serie A/B/C Italy)
    return int(resp[0]["league"]["id"])


def fetch_fixtures(team_id: int, league_id: int, season: int):
    """
    Fixtures filtrate per league+season+team (molto più affidabile).
    Gestisce pagination.
    """
    all_items = []
    page = 1
    total_pages = 1

    while page <= total_pages:
        data = api_get("/fixtures", {"team": team_id, "league": league_id, "season": season, "page": page})
        paging = data.get("paging") or {}
        total_pages = int(paging.get("total", 1))
        items = data.get("response", [])
        all_items.extend(items)
        page += 1
        time.sleep(0.2)

    return all_items


def build_home_calendar(team_id: int, summary_prefix: str, fixtures: list) -> Calendar:
    cal = Calendar()
    kept = 0

    for it in fixtures:
        fixture = it.get("fixture", {}) or {}
        teams = it.get("teams", {}) or {}
        league = it.get("league", {}) or {}

        home = teams.get("home", {}) or {}
        away = teams.get("away", {}) or {}

        # SOLO IN CASA (robusto via ID)
        if int(home.get("id") or -1) != int(team_id):
            continue

        dt_str = fixture.get("date")
        fx_id = fixture.get("id")
        if not dt_str or not fx_id:
            continue

        start = parser.isoparse(dt_str)
        end = start + timedelta(hours=2)

        venue = fixture.get("venue", {}) or {}
        loc = None
        if venue.get("name") and venue.get("city"):
            loc = f"{venue['name']}, {venue['city']}"
        elif venue.get("name"):
            loc = str(venue["name"])

        status_short = (fixture.get("status") or {}).get("short", "")
        round_name = league.get("round", "")
        league_name = league.get("name", "")

        e = Event()
        e.uid = f"{summary_prefix.lower().replace(' ','')}-home-{fx_id}@firemonster16"
        e.name = f"{summary_prefix} vs {away.get('name','Unknown')}"
        e.begin = start
        e.end = end
        if loc:
            e.location = loc
        e.description = f"{league_name} - {round_name} - Status: {status_short}"

        cal.events.add(e)
        kept += 1

    print(f"[{summary_prefix}] events_written={kept}")
    return cal


def main():
    season = season_start_year()
    print(f"Using season={season}")
    print(f"Using BASE_URL={BASE_URL}")
    print(f"Using auth={'RapidAPI' if RAPIDAPI_HOST else 'API-SPORTS direct'}")

    for cfg in TEAMS:
        team_id = find_team_id(cfg["team_search"])
        league_id = find_league_id(cfg["league_name"], season)

        fixtures = fetch_fixtures(team_id, league_id, season)
        print(f"[{cfg['team_search']}] team_id={team_id} league_id={league_id} fixtures={len(fixtures)}")

        cal = build_home_calendar(team_id, cfg["summary"], fixtures)

        with open(cfg["output"], "w", encoding="utf-8") as f:
            f.write(cal.serialize())

        print(f"OK wrote {cfg['output']}")


if __name__ == "__main__":
    main()
