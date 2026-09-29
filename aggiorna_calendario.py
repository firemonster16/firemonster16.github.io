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
# SQUADRE GESTITE
# ============================================================

TEAMS = {

    "NAPOLI": {
        "url": "https://www.corrieredellosport.it/squadra/calcio/napoli/calendario/t459",
        "source": "corriere",
        "competition": "Serie A",
        "location": "STADIO DIEGO ARMANDO MARADONA, NAPOLI, ITALIA",
        "aliases": ["Napoli"],
    },

    "CASERTANA": {
        "url": "https://www.corrieredellosport.it/squadra/calcio/casertana/calendario/t2478",
        "source": "corriere",
        "competition": "Serie C Girone C",
        "location": "STADIO ALBERTO PINTO, CASERTA, ITALY",
        "aliases": ["Casertana"],
    },

    "SAVOIA": {
        "url": "https://www.corrieredellosport.it/squadra/calcio/savoia/calendario/t3629",
        "source": "corriere",
        "competition": "Serie C Girone C",
        "location": "STADIO ALFREDO GIRAUD, TORRE ANNUNZIATA, ITALIA",
        "aliases": ["Savoia"],
    },

    "JUVE STABIA": {
        "url": "https://www.corrieredellosport.it/squadra/calcio/juve-stabia/calendario/t2184",
        "source": "corriere",
        "competition": "Serie B",
        "location": "STADIO ROMEO MENTI, CASTELLAMMARE DI STABIA, ITALY",
        "aliases": ["Juve Stabia"],
    },

    "PSA NAPOLI EST": {
        "url": "https://www.legapallacanestro.com/serie-b/psa-napoli-est",
        "source": "lnp",
        "location": "PALADENNERLEIN, NAPOLI, ITALIA",
        "aliases": [
            "PSA Napoli Est",
            "PSA Basket Napoli",
            "PSA Napoli",
        ],
    },
}


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

    return " ".join(
        text.split()
    )


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

    "psa napoli est": [
        "psa basket napoli",
        "psa napoli",
        "psa napoli est",
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

    return (
        canonical_team(a)
        ==
        canonical_team(b)
    )


def match_key(home, away):

    return (
        canonical_team(home),
        canonical_team(away),
    )


# ============================================================
# CORRIERE DELLO SPORT
# ============================================================

class TextExtractor(HTMLParser):

    def __init__(self):

        super().__init__()

        self.parts = []

    def handle_data(self, data):

        text = " ".join(
            data.split()
        )

        if text:
            self.parts.append(text)


def fetch_page(url):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
            "Mozilla/5.0 (compatible; CalendarUpdater/4.0)"
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


def parse_matches(lines, team):

    matches = []

    for index in range(
        len(lines) - 4
    ):

        competition = (
            lines[index].strip()
        )

        if (
            competition
            !=
            team["competition"]
        ):
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

        home = (
            lines[index + 2]
            .strip()
        )

        result_or_time = (
            lines[index + 3]
            .strip()
        )

        away = (
            lines[index + 4]
            .strip()
        )

        # Partita già disputata:
        # 2 - 1
        if re.fullmatch(
            r"\d+\s*-\s*\d+",
            result_or_time
        ):
            continue

        # Partita futura:
        # 20:45
        if not re.fullmatch(
            r"\d{2}:\d{2}",
            result_or_time
        ):
            continue

        time = result_or_time

        # Orari palesemente placeholder
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


# ============================================================
# LEGA NAZIONALE PALLACANESTRO
# ============================================================

class LNPTableParser(HTMLParser):

    def __init__(self):

        super().__init__()

        self.in_tr = False
        self.in_td = False

        self.current_cell = []
        self.current_row = []

        self.rows = []

    def handle_starttag(
        self,
        tag,
        attrs
    ):

        if tag == "tr":

            self.in_tr = True
            self.current_row = []

        elif (
            tag == "td"
            and
            self.in_tr
        ):

            self.in_td = True
            self.current_cell = []

    def handle_data(
        self,
        data
    ):

        if self.in_td:

            text = " ".join(
                data.split()
            )

            if text:

                self.current_cell.append(
                    text
                )

    def handle_endtag(
        self,
        tag
    ):

        if (
            tag == "td"
            and
            self.in_td
        ):

            value = " ".join(
                self.current_cell
            ).strip()

            self.current_row.append(
                value
            )

            self.current_cell = []
            self.in_td = False

        elif (
            tag == "tr"
            and
            self.in_tr
        ):

            if self.current_row:

                self.rows.append(
                    self.current_row
                )

            self.current_row = []
            self.in_tr = False


def fetch_lnp_matches(url):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
            "Mozilla/5.0 (compatible; CalendarUpdater/4.0)"
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

    parser = LNPTableParser()

    parser.feed(html)

    matches = []

    for row in parser.rows:

        if len(row) < 3:
            continue

        # Cerchiamo la cella contenente
        # data + ora.
        date_index = None
        date = None
        time = None

        for index, value in enumerate(
            row
        ):

            match = re.search(
                r"(\d{2}/\d{2}/\d{4})"
                r"\s+"
                r"(\d{2}:\d{2})",
                value
            )

            if match:

                try:

                    date = datetime.strptime(
                        match.group(1),
                        "%d/%m/%Y"
                    ).date()

                except ValueError:
                    continue

                time = match.group(2)

                date_index = index

                break

        if date_index is None:
            continue

        # Cerchiamo le due squadre nelle
        # celle successive.
        remaining = [

            value.strip()

            for value
            in row[
                date_index + 1:
            ]

            if value.strip()
        ]

        if len(remaining) < 2:
            continue

        home = remaining[0]
        away = remaining[1]

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


# ============================================================
# LETTURA ICS
# ============================================================

def get_events(text):

    return re.findall(
        r"BEGIN:VEVENT\r?\n"
        r".*?"
        r"\r?\nEND:VEVENT",
        text,
        flags=re.S,
    )


def get_field(
    event,
    name
):

    match = re.search(
        rf"^{re.escape(name)}:(.*)$",
        event,
        flags=re.M,
    )

    if match:

        return (
            match.group(1)
            .strip()
        )

    return ""


def get_teams_from_summary(
    summary
):

    summary = (
        summary.strip()
    )

    summary = re.sub(
        r"^(PARTITA\s+|CALCIO\s+)",
        "",
        summary,
        flags=re.I,
    )

    # Formato:
    # NAPOLI VS ROMA
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

    # Formato:
    # NAPOLI - ROMA
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
            equivalent(
                home,
                alias
            )
            for alias
            in team["aliases"]
        ):

            return True

    return False


def find_event(
    events,
    home,
    away
):

    wanted = match_key(
        home,
        away
    )

    for index, event in enumerate(
        events
    ):

        teams = get_teams_from_summary(
            get_field(
                event,
                "SUMMARY"
            )
        )

        if not teams:
            continue

        existing = match_key(
            teams[0],
            teams[1]
        )

        if existing == wanted:

            return index

    return None


# ============================================================
# RIMOZIONE DUPLICATI
# ============================================================

def remove_duplicate_matches(
    events
):

    seen = set()
    cleaned = []
    removed = []

    for event in events:

        summary = get_field(
            event,
            "SUMMARY"
        )

        teams = (
            get_teams_from_summary(
                summary
            )
        )

        # Non è una partita riconoscibile:
        # concerto, fiera, evento manuale...
        if not teams:

            cleaned.append(
                event
            )

            continue

        home, away = teams

        # Non appartiene alle squadre
        # gestite automaticamente.
        if not is_managed_home_team(
            home
        ):

            cleaned.append(
                event
            )

            continue

        key = match_key(
            home,
            away
        )

        if key in seen:

            removed.append(
                summary
            )

            continue

        seen.add(key)

        cleaned.append(
            event
        )

    return (
        cleaned,
        removed
    )


# ============================================================
# DATA / ORA
# ============================================================

def to_utc(
    date,
    time
):

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

    utc_time = (
        local_time.astimezone(
            timezone.utc
        )
    )

    return utc_time.strftime(
        "%Y%m%dT%H%M%SZ"
    )


def end_to_utc(
    date,
    time
):

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

    local_time += timedelta(
        hours=2
    )

    utc_time = (
        local_time.astimezone(
            timezone.utc
        )
    )

    return utc_time.strftime(
        "%Y%m%dT%H%M%SZ"
    )


# ============================================================
# MODIFICA VEVENT
# ============================================================

def replace_field(
    event,
    name,
    value
):

    pattern = (
        rf"^{re.escape(name)}:.*$"
    )

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
        f"{name}:{value}\n"
        "END:VEVENT"
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
        to_utc(
            date,
            time
        )
    )

    event = replace_field(
        event,
        "DTEND",
        end_to_utc(
            date,
            time
        )
    )

    if location:

        event = replace_field(
            event,
            "LOCATION",
            location
        )

    return event


# ============================================================
# CREAZIONE NUOVO EVENTO
# ============================================================

def create_event(
    team_name,
    home,
    away,
    date,
    time,
    location
):

    uid = (
        canonical_team(home)
        .replace(" ", "-")
        + "-"
        + canonical_team(away)
        .replace(" ", "-")
        + "-"
        + date.isoformat()
        + "@firemonster16"
    )

    return "\n".join([

        "BEGIN:VEVENT",

        f"UID:{uid}",

        (
            f"SUMMARY:"
            f"{home.upper()} VS "
            f"{away.upper()}"
        ),

        (
            f"DTSTART:"
            f"{to_utc(date, time)}"
        ),

        (
            f"DTEND:"
            f"{end_to_utc(date, time)}"
        ),

        f"LOCATION:{location}",

        (
            f"DESCRIPTION:"
            f"PARTITA IN CASA DEL "
            f"{team_name} CONTRO "
            f"{away.upper()}"
        ),

        f"X-AUTO-TEAM:{team_name}",

        "BEGIN:VALARM",

        "ACTION:DISPLAY",

        (
            f"DESCRIPTION:"
            f"{home.upper()} VS "
            f"{away.upper()}"
        ),

        "TRIGGER:-P1W",

        "END:VALARM",

        "END:VEVENT",
    ])


# ============================================================
# RICOSTRUZIONE CALENDARIO
# ============================================================

def rebuild_calendar(
    original,
    final_events
):

    first_event = re.search(
        r"BEGIN:VEVENT\r?\n",
        original
    )

    if not first_event:

        raise RuntimeError(
            "Nessun VEVENT trovato "
            "nel calendario."
        )

    last_events = list(
        re.finditer(
            r"END:VEVENT",
            original
        )
    )

    if not last_events:

        raise RuntimeError(
            "Calendario ICS non valido."
        )

    prefix = original[
        :first_event.start()
    ]

    suffix = original[
        last_events[-1].end():
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


# ============================================================
# MAIN
# ============================================================

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
            "\nDuplicati trovati "
            "nel calendario:"
        )

        for item in duplicates_removed:

            print(
                "RIMOSSO DUPLICATO:",
                item
            )

    # --------------------------------------------------------
    # CONTROLLO SQUADRE
    # --------------------------------------------------------

    for team_name, team in TEAMS.items():

        print(
            f"\nControllo {team_name}..."
        )

        try:

            # -----------------------------
            # LNP
            # -----------------------------

            if (
                team["source"]
                ==
                "lnp"
            ):

                matches = (
                    fetch_lnp_matches(
                        team["url"]
                    )
                )

            # -----------------------------
            # CORRIERE DELLO SPORT
            # -----------------------------

            else:

                page = fetch_page(
                    team["url"]
                )

                matches = parse_matches(
                    page,
                    team
                )

        except Exception as error:

            print(
                f"ERRORE {team_name}: "
                f"{error}",
                file=sys.stderr
            )

            continue

        # ----------------------------------------------------
        # SOLO PARTITE CASALINGHE
        # ----------------------------------------------------

        home_matches = [

            match

            for match in matches

            if any(
                equivalent(
                    match[2],
                    alias
                )

                for alias
                in team["aliases"]
            )
        ]

        print(
            f"{len(home_matches)} "
            "partite casalinghe trovate"
        )

        # ----------------------------------------------------
        # AGGIORNA / CREA
        # ----------------------------------------------------

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

            # Evento già presente
            if event_index is not None:

                old_event = (
                    events[
                        event_index
                    ]
                )

                new_event = update_event(
                    old_event,
                    date,
                    time,
                    team["location"],
                )

                if (
                    new_event
                    !=
                    old_event
                ):

                    events[
                        event_index
                    ] = new_event

                    modified.append(
                        f"{home} - "
                        f"{away}: "
                        f"{date.strftime('%d/%m/%Y')} "
                        f"{time}"
                    )

            # Evento non presente
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
                    f"{home} - "
                    f"{away}: "
                    f"{date.strftime('%d/%m/%Y')} "
                    f"{time}"
                )

    # --------------------------------------------------------
    # RICOSTRUZIONE ICS
    # --------------------------------------------------------

    output = rebuild_calendar(
        original,
        events
    )

    # --------------------------------------------------------
    # SALVATAGGIO
    # --------------------------------------------------------

    if output != original:

        with open(
            ICS_FILE,
            "w",
            encoding="utf-8",
            newline="\n"
        ) as file:

            file.write(
                output
            )

        print(
            "\n"
            "=============================="
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
