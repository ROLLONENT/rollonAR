"""Google Sheets Manager with retry logic."""
import os, time, threading, logging, random
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

class SheetsManager:
    def __init__(self, spreadsheet_id, credentials_path, token_path):
        self.spreadsheet_id = spreadsheet_id
        self.credentials_path = credentials_path
        self.token_path = token_path
        self._service = None
        self._cache = {}
        self._cache_time = {}
        self._lock = threading.Lock()
        self.CACHE_TTL = 120

    def _get_creds(self):
        creds = None
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(self.token_path, 'w') as f:
                f.write(creds.to_json())
        return creds

    @property
    def service(self):
        if self._service is None:
            self._service = build('sheets', 'v4', credentials=self._get_creds())
        return self._service

    def _retry(self, func, max_retries=3):
        """Execute func with exponential backoff on 429/500/503. Refresh creds on 401."""
        for attempt in range(max_retries + 1):
            try:
                return func()
            except HttpError as e:
                status = e.resp.status if hasattr(e, 'resp') else 0
                if status == 401:
                    # Refresh credentials and rebuild service
                    logging.warning("Sheets API 401: refreshing credentials")
                    self._service = None
                    try:
                        creds = self._get_creds()
                        self._service = build('sheets', 'v4', credentials=creds)
                    except Exception as refresh_err:
                        logging.warning(f"Credential refresh failed: {refresh_err}")
                    if attempt < max_retries:
                        continue
                    raise
                elif status in (429, 500, 503):
                    if attempt < max_retries:
                        delay = (2 ** attempt) + random.uniform(0, 1)
                        logging.warning(f"Sheets API {status}: retry {attempt + 1}/{max_retries} in {delay:.1f}s")
                        time.sleep(delay)
                        continue
                    raise
                else:
                    raise

    def _invalidate_cache(self, sheet_name):
        with self._lock:
            for k in [k for k in self._cache if k.startswith(sheet_name)]:
                self._cache.pop(k, None); self._cache_time.pop(k, None)

    def _get_cached(self, key):
        with self._lock:
            if key in self._cache and (time.time() - self._cache_time.get(key, 0)) < self.CACHE_TTL:
                # Return a copy to prevent concurrent mutation
                data = self._cache[key]
                return [row[:] for row in data] if isinstance(data, list) else data
            return None

    def _set_cached(self, key, data):
        with self._lock:
            self._cache[key] = data; self._cache_time[key] = time.time()

    def list_sheets(self):
        meta = self._retry(lambda: self.service.spreadsheets().get(
            spreadsheetId=self.spreadsheet_id).execute())
        return [s['properties']['title'] for s in meta.get('sheets', [])]

    def get_all_rows(self, sheet_name):
        ck = f"{sheet_name}:all"
        cached = self._get_cached(ck)
        if cached is not None: return cached
        result = self._retry(lambda: self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id, range=f"'{sheet_name}'").execute())
        data = result.get('values', [])
        self._set_cached(ck, data)
        return data

    def get_headers(self, sheet_name):
        ck = f"{sheet_name}:headers"
        cached = self._get_cached(ck)
        if cached is not None: return cached
        result = self._retry(lambda: self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id, range=f"'{sheet_name}'!1:1").execute())
        headers = result.get('values', [[]])[0]
        self._set_cached(ck, headers)
        return headers

    def get_row(self, sheet_name, row_index):
        result = self._retry(lambda: self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id, range=f"'{sheet_name}'!{row_index}:{row_index}").execute())
        rows = result.get('values', [[]])
        return rows[0] if rows else []

    def get_row_count(self, sheet_name):
        return max(0, len(self.get_all_rows(sheet_name)) - 1)

    def update_cell(self, sheet_name, row_index, col_index, value):
        col_letter = self._col_to_letter(col_index)
        self._retry(lambda: self.service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id, range=f"'{sheet_name}'!{col_letter}{row_index}",
            valueInputOption='USER_ENTERED', body={'values': [[value]]}).execute())
        self._invalidate_cache(sheet_name)

    def append_row(self, sheet_name, values):
        self._retry(lambda: self.service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id, range=f"'{sheet_name}'!A:A",
            valueInputOption='USER_ENTERED', insertDataOption='INSERT_ROWS',
            body={'values': [values]}).execute())
        self._invalidate_cache(sheet_name)

    def batch_append(self, sheet_name, rows):
        """Append multiple rows in a single API call. Google determines next empty row."""
        if not rows: return
        self._retry(lambda: self.service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id, range=f"'{sheet_name}'!A:A",
            valueInputOption='USER_ENTERED', insertDataOption='INSERT_ROWS',
            body={'values': rows}).execute())
        self._invalidate_cache(sheet_name)

    def batch_update_cells(self, sheet_name, updates):
        """Update multiple individual cells in one API call. updates = [(row, col, value), ...]"""
        if not updates: return
        data = []
        for row, col, value in updates:
            col_letter = self._col_to_letter(col)
            data.append({'range': f"'{sheet_name}'!{col_letter}{row}", 'values': [[value]]})
        self._retry(lambda: self.service.spreadsheets().values().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={'valueInputOption': 'USER_ENTERED', 'data': data}).execute())
        self._invalidate_cache(sheet_name)

    def clear_sheet(self, sheet_name):
        self._retry(lambda: self.service.spreadsheets().values().clear(
            spreadsheetId=self.spreadsheet_id, range=f"'{sheet_name}'").execute())
        self._invalidate_cache(sheet_name)

    def batch_update(self, sheet_name, rows, start_row=2):
        if not rows: return
        end_row = start_row + len(rows) - 1
        max_col = max(len(r) for r in rows)
        col_letter = self._col_to_letter(max_col)
        self._retry(lambda: self.service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"'{sheet_name}'!A{start_row}:{col_letter}{end_row}",
            valueInputOption='USER_ENTERED', body={'values': rows}).execute())
        self._invalidate_cache(sheet_name)

    def create_new_sheet(self, title):
        self._retry(lambda: self.service.spreadsheets().batchUpdate(spreadsheetId=self.spreadsheet_id,
            body={'requests': [{'addSheet': {'properties': {'title': title}}}]}).execute())

    def create_new_spreadsheet(self, title, headers, rows):
        spreadsheet = self._retry(lambda: self.service.spreadsheets().create(body={
            'properties': {'title': title},
            'sheets': [{'properties': {'title': 'Mail Merge'}}]}).execute())
        new_id = spreadsheet['spreadsheetId']
        self._retry(lambda: self.service.spreadsheets().values().update(
            spreadsheetId=new_id, range="'Mail Merge'!A1",
            valueInputOption='USER_ENTERED', body={'values': [headers] + rows}).execute())
        return {'spreadsheet_id': new_id, 'url': f"https://docs.google.com/spreadsheets/d/{new_id}/edit"}

    def _col_to_letter(self, col_num):
        result = ''
        while col_num > 0:
            col_num, remainder = divmod(col_num - 1, 26)
            result = chr(65 + remainder) + result
        return result
