"""
Scout Engine — roster-wide auto-discovery for collaborators, tours, and sync briefs.
Uses Spotify, Songkick, Last.fm APIs with graceful fallback when keys unavailable.
"""

import os, json, time, logging, re, threading
from datetime import datetime, timedelta

# Optional HTTP library (requests preferred, urllib fallback)
try:
    import requests as _http
    _HAS_REQUESTS = True
except ImportError:
    import urllib.request, urllib.error
    _HAS_REQUESTS = False


def _get(url, headers=None, timeout=10):
    """HTTP GET with requests or urllib fallback."""
    if _HAS_REQUESTS:
        r = _http.get(url, headers=headers or {}, timeout=timeout)
        r.raise_for_status()
        return r.json()
    else:
        req = urllib.request.Request(url, headers=headers or {})
        req.add_header('User-Agent', 'ROLLON AR Scout / Music Industry Tool')
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())


# ==================== SPOTIFY SCOUT ====================

class SpotifyScout:
    """Spotify Web API client credentials flow for artist discovery."""

    def __init__(self):
        self.client_id = os.environ.get('SPOTIFY_CLIENT_ID', '')
        self.client_secret = os.environ.get('SPOTIFY_CLIENT_SECRET', '')
        self._token = None
        self._token_expires = 0

    @property
    def available(self):
        return bool(self.client_id and self.client_secret)

    def _auth(self):
        if time.time() < self._token_expires and self._token:
            return self._token
        if not self.available:
            return None
        import base64
        creds = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        if _HAS_REQUESTS:
            r = _http.post('https://accounts.spotify.com/api/token',
                data={'grant_type': 'client_credentials'},
                headers={'Authorization': f'Basic {creds}'}, timeout=10)
            d = r.json()
        else:
            import urllib.parse
            data = urllib.parse.urlencode({'grant_type': 'client_credentials'}).encode()
            req = urllib.request.Request('https://accounts.spotify.com/api/token',
                data=data, headers={'Authorization': f'Basic {creds}'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                d = json.loads(resp.read().decode())
        self._token = d.get('access_token')
        self._token_expires = time.time() + d.get('expires_in', 3600) - 60
        return self._token

    def _api(self, endpoint, params=None):
        token = self._auth()
        if not token:
            return None
        url = f"https://api.spotify.com/v1/{endpoint}"
        if params:
            url += '?' + '&'.join(f"{k}={v}" for k, v in params.items())
        return _get(url, headers={'Authorization': f'Bearer {token}'})

    def search_artists(self, query, genre=None, limit=20):
        """Search Spotify for artists by name/genre."""
        q = query
        if genre:
            q += f' genre:"{genre}"'
        data = self._api('search', {
            'q': urllib_quote(q) if not _HAS_REQUESTS else q,
            'type': 'artist', 'limit': str(min(limit, 50))
        })
        if not data:
            return []
        results = []
        for a in data.get('artists', {}).get('items', []):
            img = a['images'][0]['url'] if a.get('images') else ''
            results.append({
                'name': a['name'],
                'spotify_id': a['id'],
                'genres': a.get('genres', []),
                'listeners': a.get('followers', {}).get('total', 0),
                'popularity': a.get('popularity', 0),
                'image': img,
                'spotify_url': a.get('external_urls', {}).get('spotify', ''),
                'source': 'spotify'
            })
        return results

    def get_related_artists(self, artist_id):
        """Get Spotify's related artists for a given artist ID."""
        data = self._api(f'artists/{artist_id}/related-artists')
        if not data:
            return []
        results = []
        for a in data.get('artists', []):
            img = a['images'][0]['url'] if a.get('images') else ''
            results.append({
                'name': a['name'],
                'spotify_id': a['id'],
                'genres': a.get('genres', []),
                'listeners': a.get('followers', {}).get('total', 0),
                'popularity': a.get('popularity', 0),
                'image': img,
                'spotify_url': a.get('external_urls', {}).get('spotify', ''),
                'source': 'spotify_related'
            })
        return results

    def find_artist_id(self, name):
        """Find Spotify artist ID by name."""
        data = self._api('search', {'q': name, 'type': 'artist', 'limit': '5'})
        if not data:
            return None
        items = data.get('artists', {}).get('items', [])
        # Best match: exact name (case-insensitive)
        for a in items:
            if a['name'].lower() == name.lower():
                return a['id']
        return items[0]['id'] if items else None


# ==================== SONGKICK SCOUT ====================

class SongkickScout:
    """Songkick API for tour/event discovery."""

    def __init__(self):
        self.api_key = os.environ.get('SONGKICK_API_KEY', '')

    @property
    def available(self):
        return bool(self.api_key)

    def search_events(self, artist_name=None, location=None, min_date=None, max_date=None, page=1):
        """Search upcoming events/tours."""
        if not self.available:
            return []
        params = {'apikey': self.api_key, 'page': str(page), 'per_page': '25'}
        if min_date:
            params['min_date'] = min_date
        if max_date:
            params['max_date'] = max_date

        # Search by artist or location
        if artist_name:
            # First find artist ID
            try:
                data = _get(f"https://api.songkick.com/api/3.0/search/artists.json?apikey={self.api_key}&query={_url_encode(artist_name)}")
                artists = data.get('resultsPage', {}).get('results', {}).get('artist', [])
                if not artists:
                    return []
                artist_id = artists[0]['id']
                data = _get(f"https://api.songkick.com/api/3.0/artists/{artist_id}/calendar.json?apikey={self.api_key}&per_page=25")
            except Exception as e:
                logging.warning(f"Songkick artist search error: {e}")
                return []
        elif location:
            try:
                loc_data = _get(f"https://api.songkick.com/api/3.0/search/locations.json?apikey={self.api_key}&query={_url_encode(location)}")
                locations = loc_data.get('resultsPage', {}).get('results', {}).get('location', [])
                if not locations:
                    return []
                metro_id = locations[0].get('metroArea', {}).get('id')
                if not metro_id:
                    return []
                data = _get(f"https://api.songkick.com/api/3.0/metro_areas/{metro_id}/calendar.json?apikey={self.api_key}&per_page=25")
            except Exception as e:
                logging.warning(f"Songkick location search error: {e}")
                return []
        else:
            return []

        events = data.get('resultsPage', {}).get('results', {}).get('event', [])
        results = []
        for ev in events:
            performers = [p['displayName'] for p in ev.get('performance', [])]
            headliner = performers[0] if performers else ''
            venue = ev.get('venue', {})
            location_info = ev.get('location', {})
            results.append({
                'headliner': headliner,
                'performers': performers,
                'event_type': ev.get('type', ''),
                'date': ev.get('start', {}).get('date', ''),
                'venue': venue.get('displayName', ''),
                'city': location_info.get('city', ''),
                'capacity': venue.get('capacity', ''),
                'uri': ev.get('uri', ''),
                'source': 'songkick'
            })
        return results


# ==================== LASTFM SCOUT ====================

class LastFmScout:
    """Last.fm API for artist metadata and similar artists."""

    def __init__(self):
        self.api_key = os.environ.get('LASTFM_API_KEY', '')

    @property
    def available(self):
        return bool(self.api_key)

    def get_similar(self, artist_name, limit=20):
        """Get similar artists from Last.fm."""
        if not self.available:
            return []
        try:
            data = _get(f"https://ws.audioscrobbler.com/2.0/?method=artist.getsimilar&artist={_url_encode(artist_name)}&api_key={self.api_key}&format=json&limit={limit}")
            artists = data.get('similarartists', {}).get('artist', [])
            return [{
                'name': a['name'],
                'match_score': float(a.get('match', 0)),
                'listeners': int(a.get('listeners', 0) or 0),
                'url': a.get('url', ''),
                'image': next((img['#text'] for img in a.get('image', []) if img.get('size') == 'large'), ''),
                'source': 'lastfm'
            } for a in artists]
        except Exception as e:
            logging.warning(f"Last.fm similar artists error: {e}")
            return []

    def get_artist_info(self, artist_name):
        """Get detailed artist info from Last.fm."""
        if not self.available:
            return None
        try:
            data = _get(f"https://ws.audioscrobbler.com/2.0/?method=artist.getinfo&artist={_url_encode(artist_name)}&api_key={self.api_key}&format=json")
            a = data.get('artist', {})
            tags = [t['name'] for t in a.get('tags', {}).get('tag', [])]
            return {
                'name': a.get('name', ''),
                'listeners': int(a.get('stats', {}).get('listeners', 0)),
                'playcount': int(a.get('stats', {}).get('playcount', 0)),
                'tags': tags,
                'bio': a.get('bio', {}).get('summary', ''),
                'url': a.get('url', ''),
                'source': 'lastfm'
            }
        except Exception as e:
            logging.warning(f"Last.fm artist info error: {e}")
            return None


# ==================== BANDSINTOWN SCOUT ====================

class BandsintownScout:
    """Bandsintown public API for events."""

    def search_events(self, artist_name, date_range=None):
        """Search events for an artist on Bandsintown."""
        if not artist_name:
            return []
        try:
            encoded = _url_encode(artist_name)
            date_param = date_range or 'upcoming'
            data = _get(
                f"https://rest.bandsintown.com/artists/{encoded}/events?app_id=rollon_ar_scout&date={date_param}",
                headers={'Accept': 'application/json'}
            )
            if not isinstance(data, list):
                return []
            results = []
            for ev in data[:25]:
                venue = ev.get('venue', {})
                results.append({
                    'headliner': artist_name,
                    'date': ev.get('datetime', '')[:10],
                    'venue': venue.get('name', ''),
                    'city': venue.get('city', ''),
                    'country': venue.get('country', ''),
                    'url': ev.get('url', ''),
                    'source': 'bandsintown'
                })
            return results
        except Exception as e:
            logging.warning(f"Bandsintown error for {artist_name}: {e}")
            return []


# ==================== CROSS-REFERENCE ENGINE ====================

def find_warm_connections(entity_name, sheets_manager, find_col_fn, cleanH_fn):
    """Search Personnel for warm connections to an entity.

    Returns list of connection paths: [{name, field, connection_type, last_outreach, row_index}]
    """
    if not entity_name or not entity_name.strip():
        return []

    entity_lower = entity_name.strip().lower()
    connections = []

    try:
        data = sheets_manager.get_all_rows('Personnel')
        if not data or len(data) < 2:
            return []

        headers = data[0]
        rows = data[1:]

        # Column indices
        name_col = find_col_fn(headers, 'name')
        field_col = find_col_fn(headers, 'field')
        works_with_col = find_col_fn(headers, 'works with')
        mgmt_col = find_col_fn(headers, 'mgmt company')
        agent_col = find_col_fn(headers, 'agent')
        label_col = find_col_fn(headers, 'record label')
        pub_col = find_col_fn(headers, 'publishing company')
        outreach_col = find_col_fn(headers, 'last outreach')
        email_col = find_col_fn(headers, 'email')

        for i, row in enumerate(rows):
            name = str(row[name_col]).strip() if name_col is not None and name_col < len(row) else ''
            if not name:
                continue

            connection_type = None

            # Direct name match
            if entity_lower in name.lower() or name.lower() in entity_lower:
                connection_type = 'direct'

            # Works with match
            if not connection_type and works_with_col is not None and works_with_col < len(row):
                ww = str(row[works_with_col]).lower()
                if entity_lower in ww:
                    connection_type = 'works_with'

            # Company matches
            for col, ctype in [(mgmt_col, 'mgmt'), (agent_col, 'agent'),
                               (label_col, 'label'), (pub_col, 'publisher')]:
                if not connection_type and col is not None and col < len(row):
                    val = str(row[col]).lower()
                    if entity_lower in val:
                        connection_type = ctype

            if connection_type:
                field = str(row[field_col]).strip() if field_col is not None and field_col < len(row) else ''
                outreach = str(row[outreach_col]).strip() if outreach_col is not None and outreach_col < len(row) else ''
                email = str(row[email_col]).strip() if email_col is not None and email_col < len(row) else ''
                connections.append({
                    'name': name,
                    'field': field,
                    'connection_type': connection_type,
                    'last_outreach': outreach,
                    'has_email': bool(email),
                    'row_index': i + 2
                })

    except Exception as e:
        logging.warning(f"Warm connections search error for '{entity_name}': {e}")

    return connections


# ==================== MATCH SCORING ====================

def calculate_match_score(candidate, roster_profile):
    """Calculate match score (0-100) between a candidate and a roster artist profile."""
    score = 0
    max_score = 0

    # Genre overlap (40 points)
    max_score += 40
    roster_genres = set(g.strip().lower() for g in (roster_profile.get('genre', '') or '').split('|') if g.strip())
    candidate_genres = set()
    if isinstance(candidate.get('genres'), list):
        candidate_genres = set(g.lower() for g in candidate['genres'])
    elif isinstance(candidate.get('genre'), str):
        candidate_genres = set(g.strip().lower() for g in candidate['genre'].split('|') if g.strip())

    if roster_genres and candidate_genres:
        overlap = roster_genres & candidate_genres
        if overlap:
            score += min(40, int(40 * len(overlap) / max(len(roster_genres), 1)))
        else:
            # Partial credit for related genres
            for rg in roster_genres:
                for cg in candidate_genres:
                    if rg in cg or cg in rg:
                        score += 10
                        break

    # Location proximity (20 points)
    max_score += 20
    roster_loc = (roster_profile.get('city', '') or roster_profile.get('location', '') or '').lower()
    cand_loc = (candidate.get('city', '') or candidate.get('location', '') or '').lower()
    if roster_loc and cand_loc:
        if roster_loc == cand_loc:
            score += 20
        elif any(part in cand_loc for part in roster_loc.split(',')) or any(part in roster_loc for part in cand_loc.split(',')):
            score += 12
        # Same country/region heuristic
        elif any(r in cand_loc for r in ['uk', 'london', 'manchester'] if r in roster_loc):
            score += 8

    # Popularity/momentum fit (20 points)
    max_score += 20
    tier = (roster_profile.get('momentum_tier', '') or '').lower()
    listeners = candidate.get('listeners', 0) or 0
    if isinstance(listeners, str):
        listeners = int(listeners.replace(',', '')) if listeners.replace(',', '').isdigit() else 0
    if tier == 'emerging' and 1000 <= listeners <= 100000:
        score += 20
    elif tier == 'growing' and 50000 <= listeners <= 500000:
        score += 20
    elif tier == 'established' and listeners >= 200000:
        score += 20
    elif listeners > 0:
        score += 8  # Some credit for any data

    # Type match (20 points)
    max_score += 20
    ideal_types = set(t.strip().lower() for t in (roster_profile.get('ideal_collaborator_type', '') or '').split('|') if t.strip())
    cand_type = (candidate.get('type', '') or candidate.get('field', '') or '').lower()
    if ideal_types and cand_type:
        if any(it in cand_type for it in ideal_types):
            score += 20
        elif cand_type:
            score += 5

    return min(100, int(score * 100 / max_score)) if max_score > 0 else 0


# ==================== ROSTER PROFILES ====================

def get_roster_artists(sheets_manager, find_col_fn):
    """Get all roster artists from Personnel (Field=Artist or tags contain ROLLON Artist)."""
    try:
        data = sheets_manager.get_all_rows('Personnel')
        if not data or len(data) < 2:
            return []
        headers = data[0]
        rows = data[1:]

        name_col = find_col_fn(headers, 'name')
        field_col = find_col_fn(headers, 'field')
        tags_col = find_col_fn(headers, 'tags', 'tag')
        genre_col = find_col_fn(headers, 'genre')
        city_col = find_col_fn(headers, 'city')

        artists = []
        for i, row in enumerate(rows):
            name = str(row[name_col]).strip() if name_col is not None and name_col < len(row) else ''
            if not name:
                continue
            field = str(row[field_col]).strip() if field_col is not None and field_col < len(row) else ''
            tags = str(row[tags_col]).strip() if tags_col is not None and tags_col < len(row) else ''

            is_roster = False
            if 'artist' in field.lower():
                is_roster = True
            if 'rollon artist' in tags.lower():
                is_roster = True

            if is_roster:
                genre = str(row[genre_col]).strip() if genre_col is not None and genre_col < len(row) else ''
                city = str(row[city_col]).strip() if city_col is not None and city_col < len(row) else ''
                artists.append({
                    'name': name,
                    'row_index': i + 2,
                    'field': field,
                    'genre': genre,
                    'city': city,
                    'tags': tags
                })
        return artists
    except Exception as e:
        logging.warning(f"Roster artists lookup error: {e}")
        return []


def get_artist_profile(sheets_manager, find_col_fn, artist_name):
    """Get full profile for a roster artist from Personnel."""
    try:
        data = sheets_manager.get_all_rows('Personnel')
        if not data or len(data) < 2:
            return {}
        headers = data[0]
        rows = data[1:]

        name_col = find_col_fn(headers, 'name')
        if name_col is None:
            return {}

        for i, row in enumerate(rows):
            name = str(row[name_col]).strip() if name_col < len(row) else ''
            if name.lower() == artist_name.lower():
                profile = {'name': name, 'row_index': i + 2}
                for j, h in enumerate(headers):
                    key = h.lower().strip().replace(' ', '_').replace('[✓]_', '').replace('[✗]_', '')
                    profile[key] = str(row[j]).strip() if j < len(row) else ''
                return profile
        return {}
    except Exception as e:
        logging.warning(f"Artist profile error for {artist_name}: {e}")
        return {}


def get_artist_songs(sheets_manager, find_col_fn, artist_name):
    """Get songs from Songs table where Artist matches."""
    try:
        data = sheets_manager.get_all_rows('Songs')
        if not data or len(data) < 2:
            return []
        headers = data[0]
        rows = data[1:]

        artist_col = find_col_fn(headers, 'artist')
        title_col = find_col_fn(headers, 'title')
        genre_col = find_col_fn(headers, 'genre')
        status_col = find_col_fn(headers, 'audio status')

        songs = []
        al = artist_name.lower()
        for i, row in enumerate(rows):
            artist = str(row[artist_col]).lower() if artist_col is not None and artist_col < len(row) else ''
            if al in artist:
                title = str(row[title_col]).strip() if title_col is not None and title_col < len(row) else ''
                genre = str(row[genre_col]).strip() if genre_col is not None and genre_col < len(row) else ''
                status = str(row[status_col]).strip() if status_col is not None and status_col < len(row) else ''
                songs.append({'title': title, 'genre': genre, 'status': status, 'row_index': i + 2})
        return songs
    except Exception as e:
        logging.warning(f"Artist songs error for {artist_name}: {e}")
        return []


# ==================== DISCOVERY ORCHESTRATOR ====================

class ScoutDiscovery:
    """Orchestrates discovery across all sources for a roster artist."""

    def __init__(self, sheets_manager, find_col_fn, cleanH_fn):
        self.sheets = sheets_manager
        self.find_col = find_col_fn
        self.cleanH = cleanH_fn
        self.spotify = SpotifyScout()
        self.songkick = SongkickScout()
        self.lastfm = LastFmScout()
        self.bandsintown = BandsintownScout()
        self._rate_limit = 2  # seconds between requests

    def _wait(self):
        time.sleep(self._rate_limit)

    def discover_collaborators(self, artist_name, profile, filters=None):
        """Find potential collaborators for a roster artist."""
        filters = filters or {}
        results = []
        seen = set()

        genre = filters.get('genre') or profile.get('genre', '')
        primary_genre = genre.split('|')[0].strip() if genre else ''

        # Spotify related artists
        if self.spotify.available:
            try:
                sp_id = self.spotify.find_artist_id(artist_name)
                if sp_id:
                    self._wait()
                    related = self.spotify.get_related_artists(sp_id)
                    for a in related:
                        if a['name'].lower() not in seen:
                            seen.add(a['name'].lower())
                            a['match_score'] = calculate_match_score(a, profile)
                            results.append(a)
                    self._wait()
                # Also search by genre
                if primary_genre:
                    genre_results = self.spotify.search_artists(primary_genre, limit=20)
                    for a in genre_results:
                        if a['name'].lower() not in seen:
                            seen.add(a['name'].lower())
                            a['match_score'] = calculate_match_score(a, profile)
                            results.append(a)
                    self._wait()
            except Exception as e:
                logging.warning(f"Spotify discovery error: {e}")

        # Last.fm similar artists
        if self.lastfm.available:
            try:
                similar = self.lastfm.get_similar(artist_name, limit=20)
                for a in similar:
                    if a['name'].lower() not in seen:
                        seen.add(a['name'].lower())
                        a['match_score'] = int(a.get('match_score', 0) * 100)
                        a['genres'] = []
                        results.append(a)
                self._wait()
            except Exception as e:
                logging.warning(f"Last.fm discovery error: {e}")

        # Apply filters
        min_listeners = int(filters.get('min_listeners', 0))
        max_listeners = int(filters.get('max_listeners', 0))
        if min_listeners or max_listeners:
            results = [r for r in results if
                       (not min_listeners or (r.get('listeners', 0) or 0) >= min_listeners) and
                       (not max_listeners or (r.get('listeners', 0) or 0) <= max_listeners)]

        # Cross-reference with Personnel for warm leads
        for r in results:
            conns = find_warm_connections(r['name'], self.sheets, self.find_col, self.cleanH)
            r['warm_connections'] = conns
            r['warm_lead'] = len(conns) > 0

        # Sort by match score desc
        results.sort(key=lambda x: x.get('match_score', 0), reverse=True)
        return results[:50]

    def discover_tours(self, artist_name, profile, filters=None):
        """Find tour opportunities for a roster artist."""
        filters = filters or {}
        results = []
        seen = set()

        genre = profile.get('genre', '')
        city = filters.get('location') or profile.get('city', '')

        min_date = filters.get('min_date', datetime.now().strftime('%Y-%m-%d'))
        max_date = filters.get('max_date', (datetime.now() + timedelta(days=180)).strftime('%Y-%m-%d'))

        # Songkick events in artist's region
        if self.songkick.available and city:
            try:
                events = self.songkick.search_events(location=city, min_date=min_date, max_date=max_date)
                for ev in events:
                    key = f"{ev['headliner']}_{ev['date']}".lower()
                    if key not in seen:
                        seen.add(key)
                        ev['genre_match'] = _genre_overlap_pct(genre, '')  # Would need genre data
                        ev['scouting_for'] = artist_name
                        results.append(ev)
                self._wait()
            except Exception as e:
                logging.warning(f"Songkick discovery error: {e}")

        # Bandsintown for related artists' tours
        if self.spotify.available:
            try:
                sp_id = self.spotify.find_artist_id(artist_name)
                if sp_id:
                    related = self.spotify.get_related_artists(sp_id)[:5]
                    for rel in related:
                        self._wait()
                        try:
                            events = self.bandsintown.search_events(rel['name'])
                            for ev in events[:5]:
                                key = f"{ev['headliner']}_{ev['date']}".lower()
                                if key not in seen:
                                    seen.add(key)
                                    ev['scouting_for'] = artist_name
                                    results.append(ev)
                        except Exception as e:
                            logging.warning(f"Bandsintown error for {rel['name']}: {e}")
            except Exception as e:
                logging.warning(f"Related tour discovery error: {e}")

        # Cross-reference headliners with Personnel
        for r in results:
            headliner = r.get('headliner', '')
            conns = find_warm_connections(headliner, self.sheets, self.find_col, self.cleanH)
            r['warm_connections'] = conns
            r['warm_lead'] = len(conns) > 0

        return results[:30]

    def discover_sync_briefs(self, artist_name, profile, artist_songs):
        """Match artist's catalog against available brief-like criteria.
        Note: Most sync brief sources require authentication. This builds
        the matching framework. Manual briefs from Scout Leads are also matched."""
        results = []

        # Match existing scout sync leads against this artist's songs
        try:
            data = self.sheets.get_all_rows('Scout Leads')
            if data and len(data) > 1:
                headers = data[0]
                rows = data[1:]
                for i, row in enumerate(rows):
                    rec = {}
                    for j, h in enumerate(headers):
                        rec[h.lower().strip().replace(' ', '_')] = str(row[j]).strip() if j < len(row) else ''

                    if rec.get('type', '').lower() != 'sync':
                        continue

                    brief_genre = rec.get('genre', '').lower()
                    brief_mood = rec.get('mood', '').lower()

                    # Count matching songs
                    matching_songs = []
                    for song in artist_songs:
                        song_genre = (song.get('genre', '') or '').lower()
                        if brief_genre and any(g.strip() in song_genre for g in brief_genre.split('|') if g.strip()):
                            matching_songs.append(song['title'])

                    if matching_songs or not brief_genre:
                        rec['matching_songs'] = matching_songs
                        rec['match_count'] = len(matching_songs)
                        rec['scouting_for'] = artist_name
                        rec['row_index'] = i + 2

                        # Cross-reference supervisor
                        sup = rec.get('supervisor', '')
                        if sup:
                            conns = find_warm_connections(sup, self.sheets, self.find_col, self.cleanH)
                            rec['warm_connections'] = conns
                            rec['warm_lead'] = len(conns) > 0
                        else:
                            rec['warm_connections'] = []
                            rec['warm_lead'] = False

                        results.append(rec)
        except Exception as e:
            logging.warning(f"Sync brief matching error: {e}")

        results.sort(key=lambda x: x.get('match_count', 0), reverse=True)
        return results

    def run_full_discovery(self, artist_name, filters=None):
        """Run all discovery panels for a roster artist. Returns dict with all results."""
        profile = get_artist_profile(self.sheets, self.find_col, artist_name)
        songs = get_artist_songs(self.sheets, self.find_col, artist_name)

        collaborators = self.discover_collaborators(artist_name, profile, filters)
        tours = self.discover_tours(artist_name, profile, filters)
        briefs = self.discover_sync_briefs(artist_name, profile, songs)

        return {
            'artist': artist_name,
            'profile': profile,
            'song_count': len(songs),
            'collaborators': collaborators,
            'tours': tours,
            'sync_briefs': briefs,
            'sources': {
                'spotify': self.spotify.available,
                'songkick': self.songkick.available,
                'lastfm': self.lastfm.available,
                'bandsintown': True
            },
            'timestamp': datetime.now().isoformat()
        }


# ==================== UTILITIES ====================

def _url_encode(s):
    """URL-encode a string."""
    if _HAS_REQUESTS:
        import urllib.parse
    else:
        import urllib.parse
    return urllib.parse.quote(s)

# Alias for Spotify search param
urllib_quote = _url_encode

def _genre_overlap_pct(genre1, genre2):
    """Calculate genre overlap percentage."""
    if not genre1 or not genre2:
        return 0
    g1 = set(g.strip().lower() for g in genre1.split('|') if g.strip())
    g2 = set(g.strip().lower() for g in genre2.split('|') if g.strip())
    if not g1 or not g2:
        return 0
    overlap = g1 & g2
    return int(100 * len(overlap) / max(len(g1), len(g2)))
