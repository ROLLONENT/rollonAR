"""Timezone mapping for ROLLON AR v36.

Resolves a contact's City / Country to an IANA timezone name and converts
target-local wall-clock times into America/Los_Angeles wall-clock strings
suitable for Mail Merge with Attachments (DD/MM/YYYY HH:MM:SS).

Inputs come from the Personnel sheet:
  - City     (column '[\u2713] City')            e.g. 'Los Angeles, CA'
  - Country  (column '[\u2713] Countries')        e.g. 'United States'
  - Cities sheet Timezone column (informal code, e.g. 'Pacific US')

The mapping below was built by auditing every distinct value in the Cities
tab plus the top-N Personnel cities that were NOT in the Cities tab. Keep
the map exhaustive for what the sheet actually contains rather than the
full IANA corpus.
"""

from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

LA = 'America/Los_Angeles'

# Friendly code (as stored in Cities.Timezone) -> IANA zone
TIMEZONE_ALIAS_MAP = {
    'eastern us': 'America/New_York',
    'central us': 'America/Chicago',
    'mountain us': 'America/Denver',
    'pacific us': 'America/Los_Angeles',
    'hst [hawaii]': 'Pacific/Honolulu',
    'hawaii': 'Pacific/Honolulu',
    'cest [eu]': 'Europe/Berlin',
    'cest': 'Europe/Berlin',
    'eest [eastern eu]': 'Europe/Athens',
    'eest': 'Europe/Athens',
    'gmt / bst [uk]': 'Europe/London',
    'gmt/bst [uk]': 'Europe/London',
    'gmt [uk]': 'Europe/London',
    'bst [uk]': 'Europe/London',
    'gmt': 'Europe/London',
    'bst': 'Europe/London',
    'brt [brazil]': 'America/Sao_Paulo',
    'brt': 'America/Sao_Paulo',
    'aest [australia]': 'Australia/Sydney',
    'aest': 'Australia/Sydney',
    'aedt': 'Australia/Sydney',
    'pht [philappines]': 'Asia/Manila',
    'pht [philippines]': 'Asia/Manila',
    'pht': 'Asia/Manila',
    'wib [indonesia]': 'Asia/Jakarta',
    'wib': 'Asia/Jakarta',
    'cst [china]': 'Asia/Shanghai',
    'ist [india]': 'Asia/Kolkata',
    'sst [singapore]': 'Asia/Singapore',
    'idt [isreal]': 'Asia/Jerusalem',
    'idt [israel]': 'Asia/Jerusalem',
    'idt': 'Asia/Jerusalem',
    'kst [seoul]': 'Asia/Seoul',
    'kst': 'Asia/Seoul',
    'ict [indochina]': 'Asia/Bangkok',
    'ict': 'Asia/Bangkok',
    'hkt [hong kong]': 'Asia/Hong_Kong',
    'hkt': 'Asia/Hong_Kong',
    'jst': 'Asia/Tokyo',
    'msk': 'Europe/Moscow',
    'west': 'Europe/Lisbon',
    'wet': 'Europe/Lisbon',
}

# Common Personnel City strings that aren't in the Cities tab.
# Key is cityname.lower().strip(), value is IANA zone.
CITY_IANA_MAP = {
    'los angeles': 'America/Los_Angeles',
    'los angeles, ca': 'America/Los_Angeles',
    'la': 'America/Los_Angeles',
    'san francisco': 'America/Los_Angeles',
    'san francisco, ca': 'America/Los_Angeles',
    'san diego': 'America/Los_Angeles',
    'seattle': 'America/Los_Angeles',
    'portland': 'America/Los_Angeles',
    'las vegas': 'America/Los_Angeles',
    'vegas': 'America/Los_Angeles',
    'new york': 'America/New_York',
    'new york city': 'America/New_York',
    'new york, ny': 'America/New_York',
    'nyc': 'America/New_York',
    'brooklyn': 'America/New_York',
    'manhattan': 'America/New_York',
    'boston': 'America/New_York',
    'miami': 'America/New_York',
    'atlanta': 'America/New_York',
    'philadelphia': 'America/New_York',
    'baltimore': 'America/New_York',
    'washington': 'America/New_York',
    'washington, dc': 'America/New_York',
    'dc': 'America/New_York',
    'raleigh': 'America/New_York',
    'charlotte': 'America/New_York',
    'jacksonville': 'America/New_York',
    'orlando': 'America/New_York',
    'tampa': 'America/New_York',
    'chicago': 'America/Chicago',
    'chicago, il': 'America/Chicago',
    'nashville': 'America/Chicago',
    'nashville, tn': 'America/Chicago',
    'houston': 'America/Chicago',
    'dallas': 'America/Chicago',
    'austin': 'America/Chicago',
    'san antonio': 'America/Chicago',
    'fort worth': 'America/Chicago',
    'oklahoma city': 'America/Chicago',
    'new orleans': 'America/Chicago',
    'minneapolis': 'America/Chicago',
    'memphis': 'America/Chicago',
    'kansas city': 'America/Chicago',
    'st louis': 'America/Chicago',
    'saint louis': 'America/Chicago',
    'milwaukee': 'America/Chicago',
    'denver': 'America/Denver',
    'denver, co': 'America/Denver',
    'boulder': 'America/Denver',
    'salt lake city': 'America/Denver',
    'phoenix': 'America/Phoenix',
    'tucson': 'America/Phoenix',
    'albuquerque': 'America/Denver',
    'honolulu': 'Pacific/Honolulu',
    'anchorage': 'America/Anchorage',
    'london': 'Europe/London',
    'london, uk': 'Europe/London',
    'manchester': 'Europe/London',
    'birmingham': 'Europe/London',
    'liverpool': 'Europe/London',
    'glasgow': 'Europe/London',
    'edinburgh': 'Europe/London',
    'dublin': 'Europe/Dublin',
    'paris': 'Europe/Paris',
    'berlin': 'Europe/Berlin',
    'munich': 'Europe/Berlin',
    'hamburg': 'Europe/Berlin',
    'amsterdam': 'Europe/Amsterdam',
    'rotterdam': 'Europe/Amsterdam',
    'stockholm': 'Europe/Stockholm',
    'gothenburg': 'Europe/Stockholm',
    'copenhagen': 'Europe/Copenhagen',
    'oslo': 'Europe/Oslo',
    'helsinki': 'Europe/Helsinki',
    'madrid': 'Europe/Madrid',
    'barcelona': 'Europe/Madrid',
    'lisbon': 'Europe/Lisbon',
    'rome': 'Europe/Rome',
    'milan': 'Europe/Rome',
    'naples': 'Europe/Rome',
    'florence': 'Europe/Rome',
    'vienna': 'Europe/Vienna',
    'zurich': 'Europe/Zurich',
    'geneva': 'Europe/Zurich',
    'brussels': 'Europe/Brussels',
    'warsaw': 'Europe/Warsaw',
    'prague': 'Europe/Prague',
    'budapest': 'Europe/Budapest',
    'athens': 'Europe/Athens',
    'istanbul': 'Europe/Istanbul',
    'moscow': 'Europe/Moscow',
    'saint petersburg': 'Europe/Moscow',
    'st petersburg': 'Europe/Moscow',
    'st. petersburg': 'Europe/Moscow',
    'toronto': 'America/Toronto',
    'toronto, on': 'America/Toronto',
    'ottawa': 'America/Toronto',
    'montreal': 'America/Montreal',
    'montreal, qc': 'America/Montreal',
    'montr\u00e9al': 'America/Montreal',
    'vancouver': 'America/Vancouver',
    'calgary': 'America/Edmonton',
    'edmonton': 'America/Edmonton',
    'mexico city': 'America/Mexico_City',
    'guadalajara': 'America/Mexico_City',
    'monterrey': 'America/Monterrey',
    'sao paulo': 'America/Sao_Paulo',
    's\u00e3o paulo': 'America/Sao_Paulo',
    'rio de janeiro': 'America/Sao_Paulo',
    'rio': 'America/Sao_Paulo',
    'buenos aires': 'America/Argentina/Buenos_Aires',
    'santiago': 'America/Santiago',
    'bogota': 'America/Bogota',
    'bogot\u00e1': 'America/Bogota',
    'lima': 'America/Lima',
    'caracas': 'America/Caracas',
    'tokyo': 'Asia/Tokyo',
    'osaka': 'Asia/Tokyo',
    'kyoto': 'Asia/Tokyo',
    'seoul': 'Asia/Seoul',
    'busan': 'Asia/Seoul',
    'shanghai': 'Asia/Shanghai',
    'beijing': 'Asia/Shanghai',
    'guangzhou': 'Asia/Shanghai',
    'shenzhen': 'Asia/Shanghai',
    'hong kong': 'Asia/Hong_Kong',
    'taipei': 'Asia/Taipei',
    'singapore': 'Asia/Singapore',
    'bangkok': 'Asia/Bangkok',
    'ho chi minh city': 'Asia/Ho_Chi_Minh',
    'hanoi': 'Asia/Ho_Chi_Minh',
    'manila': 'Asia/Manila',
    'jakarta': 'Asia/Jakarta',
    'kuala lumpur': 'Asia/Kuala_Lumpur',
    'mumbai': 'Asia/Kolkata',
    'delhi': 'Asia/Kolkata',
    'new delhi': 'Asia/Kolkata',
    'bangalore': 'Asia/Kolkata',
    'chennai': 'Asia/Kolkata',
    'kolkata': 'Asia/Kolkata',
    'dubai': 'Asia/Dubai',
    'abu dhabi': 'Asia/Dubai',
    'riyadh': 'Asia/Riyadh',
    'doha': 'Asia/Qatar',
    'tel aviv': 'Asia/Jerusalem',
    'jerusalem': 'Asia/Jerusalem',
    'cairo': 'Africa/Cairo',
    'johannesburg': 'Africa/Johannesburg',
    'cape town': 'Africa/Johannesburg',
    'lagos': 'Africa/Lagos',
    'nairobi': 'Africa/Nairobi',
    'accra': 'Africa/Accra',
    'sydney': 'Australia/Sydney',
    'sydney - australia/sydney': 'Australia/Sydney',
    'melbourne': 'Australia/Melbourne',
    'brisbane': 'Australia/Brisbane',
    'perth': 'Australia/Perth',
    'adelaide': 'Australia/Adelaide',
    'auckland': 'Pacific/Auckland',
    'wellington': 'Pacific/Auckland',
}

# Country -> default IANA zone (last-ditch fallback).
COUNTRY_DEFAULT_TZ = {
    'united states': 'America/New_York',
    'usa': 'America/New_York',
    'us': 'America/New_York',
    'united kingdom': 'Europe/London',
    'uk': 'Europe/London',
    'england': 'Europe/London',
    'scotland': 'Europe/London',
    'wales': 'Europe/London',
    'ireland': 'Europe/Dublin',
    'france': 'Europe/Paris',
    'germany': 'Europe/Berlin',
    'netherlands': 'Europe/Amsterdam',
    'sweden': 'Europe/Stockholm',
    'denmark': 'Europe/Copenhagen',
    'norway': 'Europe/Oslo',
    'finland': 'Europe/Helsinki',
    'spain': 'Europe/Madrid',
    'portugal': 'Europe/Lisbon',
    'italy': 'Europe/Rome',
    'austria': 'Europe/Vienna',
    'switzerland': 'Europe/Zurich',
    'belgium': 'Europe/Brussels',
    'poland': 'Europe/Warsaw',
    'czech republic': 'Europe/Prague',
    'hungary': 'Europe/Budapest',
    'greece': 'Europe/Athens',
    'turkey': 'Europe/Istanbul',
    'russia': 'Europe/Moscow',
    'ukraine': 'Europe/Kyiv',
    'canada': 'America/Toronto',
    'mexico': 'America/Mexico_City',
    'brazil': 'America/Sao_Paulo',
    'argentina': 'America/Argentina/Buenos_Aires',
    'chile': 'America/Santiago',
    'colombia': 'America/Bogota',
    'peru': 'America/Lima',
    'venezuela': 'America/Caracas',
    'japan': 'Asia/Tokyo',
    'south korea': 'Asia/Seoul',
    'korea': 'Asia/Seoul',
    'china': 'Asia/Shanghai',
    'taiwan': 'Asia/Taipei',
    'singapore': 'Asia/Singapore',
    'thailand': 'Asia/Bangkok',
    'vietnam': 'Asia/Ho_Chi_Minh',
    'philippines': 'Asia/Manila',
    'indonesia': 'Asia/Jakarta',
    'malaysia': 'Asia/Kuala_Lumpur',
    'india': 'Asia/Kolkata',
    'united arab emirates': 'Asia/Dubai',
    'uae': 'Asia/Dubai',
    'saudi arabia': 'Asia/Riyadh',
    'qatar': 'Asia/Qatar',
    'israel': 'Asia/Jerusalem',
    'egypt': 'Africa/Cairo',
    'south africa': 'Africa/Johannesburg',
    'nigeria': 'Africa/Lagos',
    'kenya': 'Africa/Nairobi',
    'ghana': 'Africa/Accra',
    'australia': 'Australia/Sydney',
    'new zealand': 'Pacific/Auckland',
    'hong kong': 'Asia/Hong_Kong',
}


def _norm(s):
    return (s or '').strip().lower()


def resolve_timezone(city, country='', cities_lookup=None):
    """Resolve an IANA timezone for a Personnel contact.

    Order:
      1. If the Cities sheet has a row for this city and its Timezone is an
         alias we know, return the IANA mapping.
      2. If the city (stripped, lowercased) is in CITY_IANA_MAP, use it.
      3. If the country is in COUNTRY_DEFAULT_TZ, use it.
      4. Return '' (caller logs a miss).

    cities_lookup is the CITY_LOOKUP dict from app.py (key: city_name.lower(),
    value: {'country': ..., 'timezone': ...}). Pass None to skip step 1.
    """
    c = _norm(city)
    country_n = _norm(country)
    if cities_lookup and c in cities_lookup:
        tz_code = _norm(cities_lookup[c].get('timezone', ''))
        if tz_code:
            if tz_code in TIMEZONE_ALIAS_MAP:
                return TIMEZONE_ALIAS_MAP[tz_code]
            if '/' in tz_code:
                return cities_lookup[c]['timezone']
    if c in CITY_IANA_MAP:
        return CITY_IANA_MAP[c]
    for stem in c.split(','):
        stem = stem.strip()
        if stem and stem in CITY_IANA_MAP:
            return CITY_IANA_MAP[stem]
    if country_n in COUNTRY_DEFAULT_TZ:
        return COUNTRY_DEFAULT_TZ[country_n]
    return ''


def parse_iso(value):
    """Parse common Airtable / Sheets datetime representations.

    Returns (year, month, day, hour, minute) tuple or None on miss.
    """
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    fmts = [
        '%Y-%m-%dT%H:%M:%S.%fZ',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M',
        '%Y-%m-%d',
        '%d/%m/%Y %H:%M:%S',
        '%d/%m/%Y %H:%M',
        '%m/%d/%Y %H:%M:%S',
        '%m/%d/%Y %H:%M',
    ]
    for f in fmts:
        try:
            dt = datetime.strptime(s, f)
            return (dt.year, dt.month, dt.day, dt.hour, dt.minute)
        except ValueError:
            continue
    return None


def to_la_string(target_wall_clock, recipient_tz):
    """Take a (y,m,d,H,M) tuple *interpreted in recipient_tz* and return a
    DD/MM/YYYY HH:MM:SS string in America/Los_Angeles."""
    if not target_wall_clock:
        return ''
    y, m, d, H, M = target_wall_clock
    if ZoneInfo is None:
        dt = datetime(y, m, d, H, M, 0)
        return dt.strftime('%d/%m/%Y %H:%M:%S')
    tz_name = recipient_tz or LA
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo(LA)
    local_dt = datetime(y, m, d, H, M, 0, tzinfo=tz)
    la_dt = local_dt.astimezone(ZoneInfo(LA))
    return la_dt.strftime('%d/%m/%Y %H:%M:%S')


def to_la_from_sheet(value, recipient_tz):
    """Read a raw Set Out Reach Date/Time cell, return LA-formatted string."""
    parsed = parse_iso(value)
    if not parsed:
        return ''
    return to_la_string(parsed, recipient_tz)


def to_zone_wall_clock(wall_clock, from_tz, to_tz):
    """General-purpose: given a (y,m,d,H,M) *interpreted in from_tz*, return
    DD/MM/YYYY HH:MM:SS in to_tz."""
    if not wall_clock:
        return ''
    y, m, d, H, M = wall_clock
    if ZoneInfo is None:
        dt = datetime(y, m, d, H, M, 0)
        return dt.strftime('%d/%m/%Y %H:%M:%S')
    try:
        src = ZoneInfo(from_tz)
    except Exception:
        src = ZoneInfo(LA)
    try:
        dst = ZoneInfo(to_tz)
    except Exception:
        dst = ZoneInfo(LA)
    local = datetime(y, m, d, H, M, 0, tzinfo=src)
    return local.astimezone(dst).strftime('%d/%m/%Y %H:%M:%S')
