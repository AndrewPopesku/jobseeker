"""
Google Drive + Sheets integration for job application tracking.

Drive uploads are handled by the compiler service.
This module handles Sheets logging only.
"""

from __future__ import annotations

import os
from pathlib import Path

import requests
import google.auth.transport.requests
import google.oauth2.id_token
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

_HERE = Path(__file__).parent
_CREDENTIALS_FILE = Path(os.environ.get("GOOGLE_CREDENTIALS_FILE", str(_HERE / "credentials.json")))
_TOKEN_FILE = Path(os.environ.get("GOOGLE_TOKEN_FILE", str(_HERE / "token.json")))
# Secret-mounted files are read-only; keep refreshed tokens in a writable path.
_WRITABLE_TOKEN_FILE = Path("/tmp/google_sheets_token.json")

_SHEETS_HEADERS = ["job_link", "company", "position", "cv_url", "status"]
_DEFAULT_STATUS = "draft"

_COMPILER_URL = os.environ.get("COMPILER_SERVICE_URL", "http://localhost:8081")


def _auth_headers() -> dict:
    """Return auth headers for Cloud Run service-to-service calls."""
    if _COMPILER_URL.startswith("http://"):
        return {}
    token = google.oauth2.id_token.fetch_id_token(
        google.auth.transport.requests.Request(), _COMPILER_URL
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _get_credentials() -> Credentials:
    creds: Credentials | None = None

    for token_path in (_WRITABLE_TOKEN_FILE, _TOKEN_FILE):
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), _SCOPES)
            break

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not _CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Google credentials not found at {_CREDENTIALS_FILE}. "
                    "Download OAuth 2.0 credentials from Google Cloud Console "
                    "and save them as jobseeker/credentials.json"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(_CREDENTIALS_FILE), _SCOPES
            )
            creds = flow.run_local_server(port=0)

        _WRITABLE_TOKEN_FILE.write_text(creds.to_json())

    return creds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_tab_name(sheets_svc, sheet_id: str) -> str:
    """Return the tab name from GOOGLE_SHEETS_TAB env var, or look it up by gid."""
    tab_name = os.environ.get("GOOGLE_SHEETS_TAB", "")
    if tab_name:
        return tab_name

    gid = os.environ.get("GOOGLE_SHEETS_GID", "")
    if gid:
        meta = sheets_svc.spreadsheets().get(spreadsheetId=sheet_id).execute()
        for sheet in meta.get("sheets", []):
            props = sheet.get("properties", {})
            if str(props.get("sheetId", "")) == gid:
                return props["title"]

    meta = sheets_svc.spreadsheets().get(spreadsheetId=sheet_id).execute()
    return meta["sheets"][0]["properties"]["title"]


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------

def upload_cv_to_drive(pdf_path: str, job_position: str) -> dict:
    """
    Upload a CV PDF to Google Drive via the compiler service.

    Args:
        pdf_path: Absolute local path to the compiled CV PDF.
        job_position: The job position title (used in the filename).

    Returns:
        Dict with: status, file_id, cv_url, filename.
    """
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    resp = requests.post(
        f"{_COMPILER_URL}/upload-to-drive",
        files={"pdf": ("cv.pdf", pdf_bytes, "application/pdf")},
        data={"job_position": job_position},
        headers=_auth_headers(),
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Upload service error ({resp.status_code}): {resp.text}")

    return resp.json()


def log_application_to_sheets(
    job_link: str,
    company: str,
    position: str,
    cv_url: str,
) -> dict:
    """
    Append a job application row to the Google Sheets tracking spreadsheet.

    Columns: job_link | company | position | cv_url | status (default: draft)

    Args:
        job_link: URL of the job posting.
        company: Company name.
        position: Job position / title.
        cv_url: Google Drive URL of the uploaded CV.

    Returns:
        Dict with: status, spreadsheet_url, row_added.
    """
    sheet_id = os.environ.get("GOOGLE_SHEETS_ID", "")
    if not sheet_id:
        raise ValueError("GOOGLE_SHEETS_ID is not set. Add it to your .env file.")

    creds = _get_credentials()
    sheets_svc = build("sheets", "v4", credentials=creds)

    tab = _resolve_tab_name(sheets_svc, sheet_id)
    row = [job_link, company, position, cv_url, _DEFAULT_STATUS]

    # Find the actual last occupied row to avoid appending after 1000 empty table rows.
    result = sheets_svc.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range=f"'{tab}'!A:A",
    ).execute()
    existing_rows = len(result.get("values", []))
    next_row = existing_rows + 1

    sheets_svc.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=f"'{tab}'!A{next_row}",
        valueInputOption="RAW",
        body={"values": [row]},
    ).execute()

    spreadsheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    return {
        "status": "ok",
        "spreadsheet_url": spreadsheet_url,
        "row_added": row,
    }
