#!/usr/bin/env python3
"""Aggiorna il calendario ICS delle partite casalinghe, senza toccare altri eventi."""
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

ICS_FILE = Path(__file__).with_name('calendario-eventi.ics')
ROME = ZoneInfo('Europe/Rome')
TEAMS = {
    'NAPOLI': {'url': 'https://www.corrieredellosport.it/squadra/calcio/napoli/calendario/t459', 'source': 'corriere', 'competitions': ['Serie A', 'Champions League', 'UEFA Champions League'], 'location': 'STADIO DIEGO ARMANDO MARADONA, NAPOLI, ITALIA', 'aliases': ['Napoli']},
    'CASERTANA': {'url': 'https://www.corrieredellosport.it/squadra/calcio/casertana/calendario/t2478', 'source': 'corriere', 'competitions': ['Serie C Girone C'], 'location': 'STADIO ALBERTO PINTO, CASERTA, ITALY', 'aliases': ['Casertana']},
    'SAVOIA': {'url': 'https://www.corrieredellosport.it/squadra/calcio/savoia/calendario/t3629', 'source': 'corriere', 'competitions': ['Serie C Girone C'], 'location': 'STADIO ALFREDO GIRAUD, TORRE ANNUNZIATA, ITALIA', 'aliases': ['Savoia']},
    'JUVE STABIA': {'url': 'https://www.corrieredellosport.it/squadra/calcio/juve-stabia/calendario/t2184', 'source': 'corriere', 'competitions': ['Serie B'], 'location': 'STADIO ROMEO MENTI, CASTELLAMMARE DI STABIA, ITALY', 'aliases': ['Juve Stabia']},
    'PSA NAPOLI EST': {'url': 'https://www.legapallacanestro.com/serie-b/psa-napoli-est', 'source': 'lnp', 'location': 'PALADENNERLEIN, NAPOLI, ITALIA', 'aliases': ['PSA Napoli Est', 'PSA Basket Napoli', 'PSA Napoli']},
}
ALIASES = {
    'internazionale ii': ['inter u23', 'inter ii', 'internazionale u23'],
    'cerignola': ['audace cerignola', 'audace cerig'],
    'fc sudtirol': ['sudtirol', 'südtirol'],
    'verona': ['hellas verona'],
    'psa napoli est': ['psa basket napoli', 'psa napoli'],
}

def normalize(s):
    s = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', s.lower()).split())

def canonical(s):
    n = normalize(s)
    for main, variants in ALIASES.items():
        if n in {normalize(x) for x in [main, *variants]}:
            return normalize(main)
    return n

def equivalent(a, b):
    return canonical(a) == canonical(b)

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, data):
        value = ' '.join(data.split())
        if value:
            self.parts.append(value)

class TableExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None
    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = []
    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            if self.row:
                self.rows.append(self.row)
            self.row = None

def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (compatible; CalendarUpdater/5.0)'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode('utf-8', errors='replace')

def parse_corriere(html, team):
    parser = TextExtractor()
    parser.feed(html)
    lines = parser.parts
    matches = []
    allowed = {normalize(x) for x in team['competitions']}
    for i in range(len(lines) - 4):
        competition = lines[i].strip()
        if normalize(competition) not in allowed:
            continue
        date_match = re.search(r'(\d{2}\.\d{2}\.\d{4})', lines[i + 1])
        if not date_match:
            continue
        try:
            date = datetime.strptime(date_match.group(1), '%d.%m.%Y').date()
        except ValueError:
            continue
        home, time, away = (x.strip() for x in lines[i + 2:i + 5])
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', time) or time in {'00:00', '01:00', '02:00'}:
            continue
        matches.append((date, time, home, away, 'Champions League' if 'champions' in normalize(competition) else competition))
    return matches

def parse_lnp(html):
    parser = TableExtractor()
    parser.feed(html)
    matches = []
    for row in parser.rows:
        for i, value in enumerate(row):
            found = re.search(r'(\d{2}/\d{2}/\d{4})\s+([01]\d|2[0-3]):([0-5]\d)', value)
            if not found or len(row) < i + 3:
                continue
            try:
                date = datetime.strptime(found.group(1), '%d/%m/%Y').date()
            except ValueError:
                continue
            matches.append((date, found.group(2) + ':' + found.group(3), row[i + 1], row[i + 2], 'Serie B Nazionale'))
            break
    return matches

EVENT_RE = re.compile(r'BEGIN:VEVENT\r?\n.*?\r?\nEND:VEVENT', re.S)

def field(event, name):
    found = re.search(r'^' + re.escape(name) + r':(.*)$', event, re.M)
    return found.group(1).strip() if found else ''

def summary_teams(summary):
    summary = re.sub(r'^(?:PARTITA|CALCIO)\s+', '', summary.strip(), flags=re.I)
    summary = re.sub(r'\s*[-–—]\s*CHAMPIONS LEAGUE\s*$', '', summary, flags=re.I)
    parts = re.split(r'\s+VS\s+|\s+[-–—]\s+', summary, maxsplit=1, flags=re.I)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else None

def managed_home(home):
    return any(any(equivalent(home, alias) for alias in team['aliases']) for team in TEAMS.values())

def event_key(event):
    teams = summary_teams(field(event, 'SUMMARY'))
    if not teams or not managed_home(teams[0]):
        return None
    return canonical(teams[0]), canonical(teams[1])

def utc_string(date, time, hours=0):
    h, m = map(int, time.split(':'))
    local = datetime(date.year, date.month, date.day, h, m, tzinfo=ROME) + timedelta(hours=hours)
    return local.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')

def set_field(event, name, value):
    pattern = re.compile(r'^' + re.escape(name) + r':[^\r\n]*', re.M)
    if pattern.search(event):
        return pattern.sub(lambda _: name + ':' + value, event, count=1)
    return event.replace('END:VEVENT', name + ':' + value + '\nEND:VEVENT', 1)

def update_event(event, date, time, location):
    for name, value in [('DTSTART', utc_string(date, time)), ('DTEND', utc_string(date, time, 2)), ('LOCATION', location)]:
        event = set_field(event, name, value)
    return event

def create_event(team_name, home, away, date, time, location, competition):
    uid = '-'.join([canonical(home).replace(' ', '-'), canonical(away).replace(' ', '-'), date.isoformat()]) + '@firemonster16'
    title = f'{home.upper()} VS {away.upper()}'
    if competition == 'Champions League':
        title += ' - CHAMPIONS LEAGUE'
    lines = [
        'BEGIN:VEVENT', f'UID:{uid}', f'SUMMARY:{title}',
        f'DTSTART:{utc_string(date, time)}', f'DTEND:{utc_string(date, time, 2)}',
        f'LOCATION:{location}', f'DESCRIPTION:PARTITA IN CASA DEL {team_name} CONTRO {away.upper()} - {competition}',
        f'X-AUTO-TEAM:{team_name}', 'BEGIN:VALARM', 'ACTION:DISPLAY',
        f'DESCRIPTION:{title}', 'TRIGGER:-P1W', 'END:VALARM', 'END:VEVENT',
    ]
    return '\n'.join(lines)

def main():
    original = ICS_FILE.read_text(encoding='utf-8')
    original_matches = list(EVENT_RE.finditer(original))
    if not original_matches or 'END:VCALENDAR' not in original:
        raise RuntimeError('Calendario ICS non valido o privo di eventi.')
    events = [m.group(0) for m in original_matches]
    # Elimina duplicati soltanto per partite riconosciute delle squadre gestite.
    seen, cleaned, removed = set(), [], []
    for event in events:
        key = event_key(event)
        if key is not None and key in seen:
            removed.append(field(event, 'SUMMARY'))
            continue
        if key is not None:
            seen.add(key)
        cleaned.append(event)
    events = cleaned
    changed, added = [], []
    failures = []
    for team_name, team in TEAMS.items():
        print(f'\nControllo {team_name}...')
        try:
            html = fetch(team['url'])
            matches = parse_lnp(html) if team['source'] == 'lnp' else parse_corriere(html, team)
            home_matches = [m for m in matches if any(equivalent(m[2], alias) for alias in team['aliases'])]
            print(f'{len(home_matches)} partite casalinghe trovate')
            if not home_matches:
                failures.append(team_name + ': nessuna partita trovata')
                continue
            for date, time, home, away, competition in home_matches:
                key = canonical(home), canonical(away)
                index = next((i for i, e in enumerate(events) if event_key(e) == key), None)
                if index is not None:
                    updated = update_event(events[index], date, time, team['location'])
                    if updated != events[index]:
                        events[index] = updated
                        changed.append(f'{home} - {away}: {date:%d/%m/%Y} {time}')
                else:
                    events.append(create_event(team_name, home, away, date, time, team['location'], competition))
                    added.append(f'{home} - {away}: {date:%d/%m/%Y} {time} ({competition})')
        except Exception as exc:
            failures.append(f'{team_name}: {exc}')
            print(f'ERRORE {team_name}: {exc}', file=sys.stderr)
    # Preserva intestazione, chiusura e tutti gli eventi non gestiti.
    prefix = original[:original_matches[0].start()]
    suffix = original[original_matches[-1].end():]
    output = prefix.rstrip('\r\n') + '\n' + '\n'.join(events) + '\n' + suffix.lstrip('\r\n')
    if output != original:
        ICS_FILE.write_text(output, encoding='utf-8', newline='\n')
        print('\nCALENDARIO AGGIORNATO')
    else:
        print('\nNessuna modifica necessaria.')
    for label, items in [('RIMOSSO DUPLICATO', removed), ('MODIFICATA', changed), ('AGGIUNTA', added)]:
        for item in items:
            print(f'{label}: {item}')
    if failures:
        for item in failures:
            print('ATTENZIONE:', item, file=sys.stderr)
        # Segnala il problema nel workflow: evita un commit automatico parziale.
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
