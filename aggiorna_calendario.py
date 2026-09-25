#!/usr/bin/env python3

import re
import sys
import urllib.request
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from html.parser import HTMLParser

ICS_FILE = "calendario-eventi.ics"
ROME = ZoneInfo("Europe/Rome")

# ============================================================
# SQUADRE MONITORATE
# ============================================================

TEAMS = {
    "NAPOLI": {
        "url": "https://www.corrieredellosport.it/squadra/calcio/napoli/calendario/t459",
        "competition": "Serie A",
        "location": "STADIO DIEGO ARMANDO MARADONA, NAPOLI, ITALIA",
        "aliases": ["Napoli"],
    },

    "CASERTANA": {
        "url": "https://www.corrieredellosport.it/squadra/calcio/casertana/calendario/t2478",
        "competition": "Serie C Girone C",
        "location": "STADIO ALBERTO PINTO, CASERTA, ITALY",
        "aliases": ["Casertana"],
    },

    "SAVOIA": {
        "url": "https://www.corrieredellosport.it/squadra/calcio/savoia/calendario/t3629",
        "competition": "Serie C Girone C",
        "location": "STADIO ALFREDO GIRAUD, TORRE ANNUNZIATA, ITALIA",
        "aliases": ["Savoia"],
    },

    "JUVE STABIA": {
        "url": "https://www.corrieredellosport.it/squadra/calcio/juve-stabia/calendario/t2184",
        "competition": "Serie B",
        "location": "STADIO ROMEO MENTI, CASTELLAMMARE DI STABIA, ITALY",
        "aliases": ["Juve Stabia"],
    },
}


# ============================================================
# LETTURA PAGINE WEB
# ============================================================

class TextExtractor(HTMLParser):

    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):

        text = " ".join(data.split())

        if text:
            self.parts.append(text)


def fetch_page(url):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
            "Mozilla/5.0 (compatible; CalendarUpdater/1.0)"
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=30
    ) as response:

        html = response.read().decode(
            "utf-8",
            errors="replace"
        )

    parser = TextExtractor()

    parser.feed(html)

    print(f"Pagina scaricata: {len(html)} caratteri")
    print(f"Elementi di testo estratti: {len(parser.parts)}")

    print("=== PRIMI ELEMENTI DELLA PAGINA ===")
    for item in parser.parts[:80]:
        print(repr(item))
    print("=== FINE DEBUG ===")

    return parser.parts


# ============================================================
# NORMALIZZAZIONE NOMI
# ============================================================

def normalize(text):

    text = unicodedata.normalize(
        "NFKD",
        text
    )

    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )

    text = text.lower()

    text = text.replace("–", "-")
    text = text.replace("—", "-")

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text
    )

    return " ".join(text.split())


ALIASES = {

    "internazionale ii": [
        "inter u23",
        "inter ii",
        "internazionale u23",
    ],

    "cerignola": [
        "audace cerignola",
        "audace cerig",
    ],

    "fc sudtirol": [
        "sudtirol",
        "südtirol",
    ],

    "verona": [
        "hellas verona",
    ],
}


def equivalent(a, b):

    a = normalize(a)
    b = normalize(b)

    if a == b:
        return True

    for canonical, variants in ALIASES.items():

        group = {
            normalize(canonical),
            *(normalize(x) for x in variants),
        }

        if a in group and b in group:
            return True

    return False


# ============================================================
# ESTRAZIONE PARTITE
# ============================================================

DATE_RE = re.compile(
    r"^(?:lunedi|martedi|mercoledi|giovedi|"
    r"venerdi|sabato|domenica)?\s*"
    r"(\d{2}\.\d{2}\.\d{4})$",
    re.I,
)

FUTURE_RE = re.compile(
    r"^(.+?)\s+(\d{2}:\d{2})\s+(.+?)$"
)

RESULT_RE = re.compile(
    r"^(.+?)\s+\d+\s*-\s*\d+\s+(.+?)$"
)


def parse_matches(lines, team):

    matches = []

    # La pagina del Corriere presenta i dati così:
    #
    # Serie A
    # domenica 30.08.2026
    # Napoli 18:30 Como
    #
    # Per questo analizziamo direttamente:
    # competizione -> data -> partita

    for index, line in enumerate(lines):

        # Cerchiamo soltanto la competizione
        # che ci interessa.
        if line.strip() != team["competition"]:
            continue

        date = None
        match_line = None

        # Nei pochi elementi successivi devono esserci
        # data e partita.
        for candidate in lines[index + 1:index + 8]:

            # Cerca una data nel formato 30.08.2026
            date_match = re.search(
                r"(\d{2}\.\d{2}\.\d{4})",
                candidate
            )

            if date_match and date is None:

                try:

                    date = datetime.strptime(
                        date_match.group(1),
                        "%d.%m.%Y"
                    ).date()

                except ValueError:
                    pass

                continue

            # Dopo aver trovato la data,
            # cerchiamo "Squadra 18:30 Squadra"
            if date:

                game_match = re.match(
                    r"^(.+?)\s+(\d{2}:\d{2})\s+(.+?)$",
                    candidate.strip()
                )

                if game_match:

                    match_line = game_match
                    break

        if not date or not match_line:
            continue

        home = match_line.group(1).strip()
        time = match_line.group(2).strip()
        away = match_line.group(3).strip()

        # Evita eventuali orari placeholder.
        if time in {
            "00:00",
            "01:00",
            "02:00",
        }:
            continue

        matches.append(
            (
                date,
                time,
                home,
                away,
            )
        )

    # Elimina eventuali duplicati
    unique = []

    seen = set()

    for match in matches:

        key = (
            match[0],
            match[1],
            normalize(match[2]),
            normalize(match[3]),
        )

        if key not in seen:

            seen.add(key)
            unique.append(match)

    return unique


# ============================================================
# GESTIONE FILE ICS
# ============================================================

def get_events(text):

    return re.findall(
        r"BEGIN:VEVENT\r?\n.*?\r?\nEND:VEVENT",
        text,
        flags=re.S,
    )


def get_field(event, name):

    match = re.search(
        rf"^{re.escape(name)}:(.*)$",
        event,
        flags=re.M,
    )

    if match:
        return match.group(1).strip()

    return ""


def get_teams_from_summary(summary):

    summary = re.sub(
        r"^(PARTITA\s+)?",
        "",
        summary.strip(),
        flags=re.I,
    )

    parts = re.split(
        r"\s+(?:VS|-|–)\s+",
        summary,
        maxsplit=1,
        flags=re.I,
    )

    if len(parts) == 2:
        return parts

    return None


def find_event(events, home, away):

    for index, event in enumerate(events):

        teams = get_teams_from_summary(
            get_field(
                event,
                "SUMMARY"
            )
        )

        if not teams:
            continue

        if (
            equivalent(teams[0], home)
            and
            equivalent(teams[1], away)
        ):
            return index

    return None


# ============================================================
# GESTIONE ORARI
# ============================================================

def to_utc(date, time):

    hour, minute = map(
        int,
        time.split(":")
    )

    local_time = datetime(
        date.year,
        date.month,
        date.day,
        hour,
        minute,
        tzinfo=ROME,
    )

    utc_time = local_time.astimezone(
        timezone.utc
    )

    return utc_time.strftime(
        "%Y%m%dT%H%M%SZ"
    )


def replace_field(event, name, value):

    pattern = rf"^{re.escape(name)}:.*$"

    if re.search(
        pattern,
        event,
        flags=re.M
    ):

        return re.sub(
            pattern,
            f"{name}:{value}",
            event,
            flags=re.M,
        )

    return event.replace(
        "END:VEVENT",
        f"{name}:{value}\nEND:VEVENT"
    )


# ============================================================
# AGGIORNAMENTO EVENTO ESISTENTE
# ============================================================

def update_event(
    event,
    date,
    time,
    location
):

    start = to_utc(
        date,
        time
    )

    hour, minute = map(
        int,
        time.split(":")
    )

    end_local = datetime(
        date.year,
        date.month,
        date.day,
        hour,
        minute,
        tzinfo=ROME,
    ) + timedelta(hours=2)

    end = end_local.astimezone(
        timezone.utc
    ).strftime(
        "%Y%m%dT%H%M%SZ"
    )

    event = replace_field(
        event,
        "DTSTART",
        start
    )

    event = replace_field(
        event,
        "DTEND",
        end
    )

    if location:

        event = replace_field(
            event,
            "LOCATION",
            location
        )

    return event


# ============================================================
# CREAZIONE NUOVA PARTITA
# ============================================================

def create_event(
    team_name,
    home,
    away,
    date,
    time,
    location
):

    start = to_utc(
        date,
        time
    )

    hour, minute = map(
        int,
        time.split(":")
    )

    end_local = datetime(
        date.year,
        date.month,
        date.day,
        hour,
        minute,
        tzinfo=ROME,
    ) + timedelta(hours=2)

    end = end_local.astimezone(
        timezone.utc
    ).strftime(
        "%Y%m%dT%H%M%SZ"
    )

    uid = (
        normalize(home).replace(" ", "-")
        + "-"
        + normalize(away).replace(" ", "-")
        + "-"
        + date.isoformat()
        + "@firemonster16"
    )

    return "\n".join([

        "BEGIN:VEVENT",

        f"UID:{uid}",

        f"SUMMARY:{home.upper()} VS {away.upper()}",

        f"DTSTART:{start}",

        f"DTEND:{end}",

        f"LOCATION:{location}",

        (
            f"DESCRIPTION:PARTITA IN CASA DEL "
            f"{team_name} CONTRO {away.upper()}"
        ),

        f"X-AUTO-TEAM:{team_name}",

        "BEGIN:VALARM",

        "ACTION:DISPLAY",

        (
            f"DESCRIPTION:"
            f"{home.upper()} VS {away.upper()}"
        ),

        "TRIGGER:-P1W",

        "END:VALARM",

        "END:VEVENT",
    ])


# ============================================================
# PROGRAMMA PRINCIPALE
# ============================================================

def main():

    with open(
        ICS_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        original = file.read()

    events = get_events(original)

    original_event_count = len(events)

    modified = []
    added = []

    for team_name, team in TEAMS.items():

        print(
            f"\nControllo {team_name}..."
        )

        try:

            page = fetch_page(
                team["url"]
            )

            matches = parse_matches(
                page,
                team
            )

        except Exception as error:

            print(
                f"ERRORE {team_name}: {error}",
                file=sys.stderr
            )

            continue

        home_matches = [

            match

            for match in matches

            if any(
                equivalent(
                    match[2],
                    alias
                )
                for alias in team["aliases"]
            )
        ]

        print(
            f"{len(home_matches)} "
            "partite casalinghe trovate"
        )

        for (
            date,
            time,
            home,
            away
        ) in home_matches:

            event_index = find_event(
                events,
                home,
                away
            )

            if event_index is not None:

                old_event = events[
                    event_index
                ]

                new_event = update_event(
                    old_event,
                    date,
                    time,
                    team["location"],
                )

                if new_event != old_event:

                    events[
                        event_index
                    ] = new_event

                    modified.append(
                        f"{home} - {away}: "
                        f"{date.strftime('%d/%m/%Y')} "
                        f"{time}"
                    )

            else:

                events.append(
                    create_event(
                        team_name,
                        home,
                        away,
                        date,
                        time,
                        team["location"],
                    )
                )

                added.append(
                    f"{home} - {away}: "
                    f"{date.strftime('%d/%m/%Y')} "
                    f"{time}"
                )

    # ========================================================
    # RICOSTRUZIONE CALENDARIO
    # ========================================================

    existing_events = events[
        :original_event_count
    ]

    iterator = iter(
        existing_events
    )

    output = re.sub(
        r"BEGIN:VEVENT\r?\n.*?\r?\nEND:VEVENT",
        lambda _: next(iterator),
        original,
        flags=re.S,
    )

    # Aggiunge eventuali nuove partite
    # immediatamente prima di END:VCALENDAR

    if len(events) > original_event_count:

        new_events = "\n\n".join(
            events[
                original_event_count:
            ]
        )

        output = re.sub(
            r"\r?\nEND:VCALENDAR\s*$",
            (
                f"\n\n{new_events}"
                "\nEND:VCALENDAR\n"
            ),
            output,
        )

    # ========================================================
    # SALVATAGGIO
    # ========================================================

    if output != original:

        with open(
            ICS_FILE,
            "w",
            encoding="utf-8",
            newline="\n"
        ) as file:

            file.write(output)

        print(
            "\n=============================="
        )

        print(
            "CALENDARIO AGGIORNATO"
        )

        print(
            "=============================="
        )

        for item in modified:

            print(
                "MODIFICATA:",
                item
            )

        for item in added:

            print(
                "AGGIUNTA:",
                item
            )

    else:

        print(
            "\nNessuna modifica necessaria."
        )


if __name__ == "__main__":
    main()
