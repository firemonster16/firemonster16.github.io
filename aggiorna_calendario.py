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
            "Mozilla/5.0 (compatible; CalendarUpdater/3.0)"
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

    return parser.parts


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


def canonical_team(name):

    value = normalize(name)

    for canonical, variants in ALIASES.items():

        group = {
            normalize(canonical),
            *(normalize(x) for x in variants),
        }

        if value in group:
            return normalize(canonical)

    return value


def equivalent(a, b):

    return canonical_team(a) == canonical_team(b)


def parse_matches(lines, team):

    matches = []

    for index in range(len(lines) - 4):

        competition = lines[index].strip()

        if competition != team["competition"]:
            continue

        date_match = re.search(
            r"(\d{2}\.\d{2}\.\d{4})",
            lines[index + 1]
        )

        if not date_match:
            continue

        try:

            date = datetime.strptime(
                date_match.group(1),
                "%d.%m.%Y"
            ).date()

        except ValueError:
            continue

        home = lines[index + 2].strip()
        result_or_time = lines[index + 3].strip()
        away = lines[index + 4].strip()

        # Partita già disputata.
        if re.fullmatch(
            r"\d+\s*-\s*\d+",
            result_or_time
        ):
            continue

        # Deve esserci un vero orario.
        if not re.fullmatch(
            r"\d{2}:\d{2}",
            result_or_time
        ):
            continue

        time = result_or_time

        # Escludiamo valori palesemente placeholder.
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

    return matches


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

    summary = summary.strip()

    summary = re.sub(
        r"^(PARTITA\s+|CALCIO\s+)",
        "",
        summary,
        flags=re.I,
    )

    # Prima proviamo VS, che è il formato principale.
    parts = re.split(
        r"\s+\bVS\b\s+",
        summary,
        maxsplit=1,
        flags=re.I,
    )

    if len(parts) == 2:
        return (
            parts[0].strip(),
            parts[1].strip(),
        )

    # Poi i trattini con spazi ai lati.
    parts = re.split(
        r"\s+[-–—]\s+",
        summary,
        maxsplit=1,
    )

    if len(parts) == 2:
        return (
            parts[0].strip(),
            parts[1].strip(),
        )

    return None


def is_managed_home_team(home):

    for team in TEAMS.values():

        if any(
            equivalent(home, alias)
            for alias in team["aliases"]
        ):
            return True

    return False


def match_key(home, away):

    return (
        canonical_team(home),
        canonical_team(away),
    )


def find_event(events, home, away):

    wanted = match_key(
        home,
        away
    )

    for index, event in enumerate(events):

        teams = get_teams_from_summary(
            get_field(
                event,
                "SUMMARY"
            )
        )

        if not teams:
            continue

        if match_key(
            teams[0],
            teams[1]
        ) == wanted:

            return index

    return None


def remove_duplicate_matches(events):

    seen = set()
    cleaned = []
    removed = []

    for event in events:

        summary = get_field(
            event,
            "SUMMARY"
        )

        teams = get_teams_from_summary(
            summary
        )

        if not teams:

            cleaned.append(event)
            continue

        home, away = teams

        # Concerti, fiere e altre manifestazioni
        # non vengono mai considerate.
        if not is_managed_home_team(home):

            cleaned.append(event)
            continue

        key = match_key(
            home,
            away
        )

        if key in seen:

            removed.append(summary)
            continue

        seen.add(key)
        cleaned.append(event)

    return cleaned, removed


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

    return local_time.astimezone(
        timezone.utc
    ).strftime(
        "%Y%m%dT%H%M%SZ"
    )


def end_to_utc(date, time):

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
    ) + timedelta(hours=2)

    return local_time.astimezone(
        timezone.utc
    ).strftime(
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


def update_event(
    event,
    date,
    time,
    location
):

    event = replace_field(
        event,
        "DTSTART",
        to_utc(date, time)
    )

    event = replace_field(
        event,
        "DTEND",
        end_to_utc(date, time)
    )

    if location:

        event = replace_field(
            event,
            "LOCATION",
            location
        )

    return event


def create_event(
    team_name,
    home,
    away,
    date,
    time,
    location
):

    uid = (
        canonical_team(home).replace(" ", "-")
        + "-"
        + canonical_team(away).replace(" ", "-")
        + "-"
        + date.isoformat()
        + "@firemonster16"
    )

    return "\n".join([

        "BEGIN:VEVENT",

        f"UID:{uid}",

        f"SUMMARY:{home.upper()} VS {away.upper()}",

        f"DTSTART:{to_utc(date, time)}",

        f"DTEND:{end_to_utc(date, time)}",

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


def rebuild_calendar(original, original_events, final_events):

    # Ricostruiamo il VCALENDAR senza toccare
    # intestazione o proprietà generali.
    first_event = re.search(
        r"BEGIN:VEVENT\r?\n",
        original
    )

    if not first_event:

        raise RuntimeError(
            "Nessun VEVENT trovato nel calendario."
        )

    last_end = list(
        re.finditer(
            r"END:VEVENT",
            original
        )
    )

    if not last_end:

        raise RuntimeError(
            "Calendario ICS non valido."
        )

    prefix = original[
        :first_event.start()
    ]

    suffix = original[
        last_end[-1].end():
    ]

    body = "\n\n".join(
        final_events
    )

    return (
        prefix.rstrip()
        + "\n"
        + body
        + "\n"
        + suffix.lstrip()
    )


def main():

    with open(
        ICS_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        original = file.read()

    original_events = get_events(
        original
    )

    events, duplicates_removed = (
        remove_duplicate_matches(
            original_events
        )
    )

    modified = []
    added = []

    if duplicates_removed:

        print(
            "\nDuplicati già presenti "
            "nel calendario:"
        )

        for item in duplicates_removed:

            print(
                "RIMOSSO DUPLICATO:",
                item
            )

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

    output = rebuild_calendar(
        original,
        original_events,
        events
    )

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

        for item in duplicates_removed:

            print(
                "RIMOSSO DUPLICATO:",
                item
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
