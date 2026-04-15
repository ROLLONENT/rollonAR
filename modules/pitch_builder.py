"""Pitch Campaign Builder — mirrors Airtable filter logic."""
from datetime import datetime, timedelta

PITCH_FILTERS = {
    'Dance': {'field_has':['MGMT','Record A&R','A&R'],'tags_has':['Dance Pitch'],'tags_not':['Dont Pitch','Need Email','Blocked',"Don't Mass Pitch"]},
    'Pop': {'field_has':['MGMT','Record A&R','A&R'],'tags_has':['Pop Pitch'],'tags_not':['Dont Pitch','Need Email','Blocked',"Don't Mass Pitch"]},
    'KPOP': {'field_has':['MGMT','Record A&R','A&R'],'tags_has':['KPOP Pitch'],'tags_not':['Dont Pitch','Need Email','Blocked',"Don't Mass Pitch"]},
    'Singer-Songwriter': {'field_has':['MGMT','Record A&R','A&R'],'tags_has':['Singer-Songwriter Pitch','SSW Pitch'],'tags_not':['Dont Pitch','Need Email','Blocked',"Don't Mass Pitch"]},
    'Sync': {'field_has':['Sync','Music Supervisor','Sync Agent'],'tags_has':['Sync Pitch'],'tags_not':['Dont Pitch','Need Email','Blocked',"Don't Mass Pitch"]},
    'Writing Trip': {'field_has':['MGMT','Record A&R','A&R'],'tags_has':['Writing Trip'],'tags_not':['Dont Pitch','Need Email','Blocked',"Don't Mass Pitch"]},
}

class PitchBuilder:
    def __init__(self, sm): self.sheets = sm

    def _fc(self, headers, *terms):
        for t in terms:
            tl = t.lower()
            for i, h in enumerate(headers):
                if tl in h.lower(): return i
        return None

    def _gv(self, row, idx):
        return str(row[idx]).strip() if idx is not None and idx < len(row) else ''

    def get_contacts_for_type(self, pitch_type):
        data = self.sheets.get_all_rows('Personnel')
        if not data: return []
        h = data[0]; rows = data[1:]
        cols = {t: self._fc(h, *terms) for t, terms in [('name',['name']),('email',['email']),('field',['field']),('tags',['tags']),('city',['city']),('country',['countries','country']),('outreach',['outreach notes']),('company',['mgmt company','publishing company','record label']),('artists',['artists'])]}
        f = PITCH_FILTERS.get(pitch_type, {})
        fh = [x.lower() for x in f.get('field_has', [])]
        th = [x.lower() for x in f.get('tags_has', [])]
        tn = [x.lower() for x in f.get('tags_not', [])]
        contacts = []
        for i, r in enumerate(rows):
            email = self._gv(r, cols['email'])
            if not email: continue
            if fh:
                fv = self._gv(r, cols['field']).lower()
                if not any(x in fv for x in fh): continue
            if th:
                tv = self._gv(r, cols['tags']).lower()
                if not any(x in tv for x in th): continue
            if tn:
                tv = self._gv(r, cols['tags']).lower()
                if any(x in tv for x in tn): continue
            contacts.append({'row_index':i+2,'name':self._gv(r,cols['name']),'email':email,'field':self._gv(r,cols['field']),'tags':self._gv(r,cols['tags']),'city':self._gv(r,cols['city']),'country':self._gv(r,cols['country']),'outreach':self._gv(r,cols['outreach']),'company':self._gv(r,cols['company']),'artists':self._gv(r,cols['artists']),'selected':True})
        return contacts

    def generate_campaign(self, pitch_type, playlist_link, round_number, bespoke_paragraph, contacts, send_day='Tuesday', send_time='11:00'):
        headers = ['First Name','Email Address','Scheduled Date','File Attachments','Mail Merge Status']
        dm = {'Monday':0,'Tuesday':1,'Wednesday':2,'Thursday':3,'Friday':4}
        td = dm.get(send_day, 1); today = datetime.now()
        da = td - today.weekday()
        if da <= 0: da += 7
        default_date = f"{(today + timedelta(days=da)).strftime('%Y-%m-%d')} {send_time}"
        rows = [[c.get('name','').split()[0] if c.get('name','') else '', c.get('email',''), default_date, playlist_link, ''] for c in contacts if c.get('selected', True)]
        email = self._email(bespoke_paragraph, playlist_link, round_number)
        title = f"ROLLON Pitch - {pitch_type} - Round {round_number} - {datetime.now().strftime('%Y-%m-%d')}"
        try:
            r = self.sheets.create_new_spreadsheet(title, headers, rows)
            # Log to Pitch Log
            self.log_pitches(pitch_type, round_number, playlist_link, contacts)
            return {'success':True,'spreadsheet_url':r['url'],'total_contacts':len(rows),'email_body':email,'title':title}
        except Exception as e:
            return {'success':False,'error':str(e),'total_contacts':len(rows),'email_body':email}

    def _ensure_pitch_log(self):
        """Create Pitch Log sheet tab if it doesn't exist."""
        try:
            data = self.sheets.get_all_rows('Pitch Log')
            if data: return True
        except Exception:
            pass
        try:
            self.sheets.service.spreadsheets().batchUpdate(
                spreadsheetId=self.sheets.spreadsheet_id,
                body={'requests': [{'addSheet': {'properties': {'title': 'Pitch Log'}}}]}
            ).execute()
            headers = ['Date','Round','Pitch Type','Contact Name','Contact Email','Song Title','DISCO Link','Status','Response Date','Notes']
            self.sheets.service.spreadsheets().values().update(
                spreadsheetId=self.sheets.spreadsheet_id, range="'Pitch Log'!A1",
                valueInputOption='USER_ENTERED', body={'values': [headers]}
            ).execute()
            self.sheets._invalidate_cache('Pitch Log')
            return True
        except Exception as e:
            print(f"Failed to create Pitch Log: {e}")
            return False

    def log_pitches(self, pitch_type, round_number, disco_link, contacts):
        """Log each pitch to the Pitch Log sheet."""
        if not self._ensure_pitch_log(): return
        today = datetime.now().strftime('%Y-%m-%d')
        rows = []
        for c in contacts:
            if not c.get('selected', True): continue
            rows.append([
                today, round_number, pitch_type,
                c.get('name', ''), c.get('email', ''),
                '', disco_link, 'Sent', '', ''
            ])
        if rows:
            try:
                self.sheets.batch_append('Pitch Log', rows)
            except Exception as e:
                print(f"Failed to log pitches: {e}")

    def get_pitch_history(self, contact_name=None, song_title=None, limit=50):
        """Get pitch history filtered by contact or song."""
        try:
            data = self.sheets.get_all_rows('Pitch Log')
            if not data or len(data) < 2: return []
            headers = data[0]; rows = data[1:]
            results = []
            for i, row in enumerate(rows):
                rec = {}
                for j, h in enumerate(headers):
                    rec[h] = row[j] if j < len(row) else ''
                if contact_name and contact_name.lower() not in rec.get('Contact Name', '').lower():
                    continue
                if song_title and song_title.lower() not in rec.get('Song Title', '').lower():
                    continue
                rec['_row'] = i + 2
                results.append(rec)
            return results[-limit:]
        except Exception as e:
            import logging; logging.warning(f"Pitch history load: {e}")
            return []

    def check_duplicates(self, contact_email, song_title=''):
        """Check if a contact was already pitched (optionally for a specific song)."""
        history = self.get_pitch_history(contact_name=None)
        for entry in history:
            if entry.get('Contact Email', '').lower() == contact_email.lower():
                if not song_title or song_title.lower() in entry.get('Song Title', '').lower():
                    return entry
        return None

    def draft_email(self, pt, rn, pl):
        starters = {'Dance':"Massive dance/electronic cuts this round — uptempo bangers and deeper groove-led tracks.",'Pop':"Strong pop batch — big hooks, clever lyrics, unexpected melodic twists.",'KPOP':"Exciting K-pop ready tracks — strong toplines with signature energy.",'Singer-Songwriter':"Beautiful singer-songwriter cuts — raw, honest, songs that stick.",'Sync':"Strong sync-ready tracks — versatile moods, clean stems, easy to clear.",'Writing Trip':"Putting together the next writing trip — here's what our writers have been cooking."}
        return self._email(starters.get(pt, "Fresh batch of tracks for you."), pl, rn)

    def _email(self, bespoke, link, rn):
        return f"Hey {{{{First Name}}}},\n\nHow are you? Hope all is well in your world!\n\n{bespoke}\nListen: {link} ROLLON Toplines [{rn}]\n\nMassive thanks for taking the time to check out our pitches. Appreciated big time.\n\ncheers,\nCelina\n\nCelina Rollon | Rollon Ent\n+1 (747) 258-5952\ncelina@rollonent.com\nhttp://www.rollonent.com"
