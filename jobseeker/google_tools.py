"""
Google Drive + Sheets integration for job application tracking.

Setup (one-time):
  1. Go to https://console.cloud.google.com
  2. Create a project, enable "Google Drive API" and "Google Sheets API"
  3. Create OAuth 2.0 credentials (Desktop app), download as:
       jobseeker/credentials.json
  4. Set env vars (or add to .env):
       GOOGLE_DRIVE_FOLDER_ID  — ID of the Drive folder where CVs will be stored
       GOOGLE_SHEETS_ID        — ID of the tracking spreadsheet
                                 (leave empty to auto-create on first run)
  5. First run will open a browser to authorise access; token saved to:
       jobseeker/token.json
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]

_HERE = Path(__file__).parent
_CREDENTIALS_FILE = _HERE / "credentials.json"
_TOKEN_FILE = _HERE / "token.json"

_SHEETS_HEADERS = ["job_link", "company", "position", "cv_url", "status"]
_DEFAULT_STATUS = "draft"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _get_credentials() -> Credentials:
    creds: Credentials | None = None

    if _TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_FILE), _SCOPES)

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

        _TOKEN_FILE.write_text(creds.to_json())

    return creds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize_position(position: str) -> str:
    """Convert job position to a safe filename segment."""
    cleaned = re.sub(r"[^\w\s-]", "", position).strip()
    return re.sub(r"[\s]+", "_", cleaned)


def _resolve_tab_name(sheets_svc, sheet_id: str) -> str:
    """Return the tab name from GOOGLE_SHEETS_TAB env var, or look it up by gid."""
    tab_name = os.environ.get("GOOGLE_SHEETS_TAB", "")
    if tab_name:
        return tab_name

    # Look up by gid if provided
    gid = os.environ.get("GOOGLE_SHEETS_GID", "")
    if gid:
        meta = sheets_svc.spreadsheets().get(spreadsheetId=sheet_id).execute()
        for sheet in meta.get("sheets", []):
            props = sheet.get("properties", {})
            if str(props.get("sheetId", "")) == gid:
                return props["title"]

    # Fall back to the first sheet
    meta = sheets_svc.spreadsheets().get(spreadsheetId=sheet_id).execute()
    return meta["sheets"][0]["properties"]["title"]


# ---------------------------------------------------------------------------
# Public tools
# ---------------------------------------------------------------------------

def upload_cv_to_drive(pdf_path: str, job_position: str) -> dict:
    """
    Upload a CV PDF to Google Drive and return the shareable file URL.

    The file is named "Andrii_Popesku_<job_position>.pdf" and stored in the
    folder specified by the GOOGLE_DRIVE_FOLDER_ID environment variable.

    Args:
        pdf_path: Absolute local path to the compiled CV PDF.
        job_position: The job position title (used in the filename).

    Returns:
        Dict with: status, file_id, cv_url, filename.
    """
    if not os.path.isfile(pdf_path):
        return {"status": "error", "error": f"PDF not found: {pdf_path}"}

    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")
    position_slug = _sanitize_position(job_position)
    filename = f"Andrii_Popesku_{position_slug}.pdf"

    try:
        creds = _get_credentials()
        drive_svc = build("drive", "v3", credentials=creds)

        def _upload(parent: str | None) -> dict:
            metadata: dict = {"name": filename, "mimeType": "application/pdf"}
            if parent:
                metadata["parents"] = [parent]
            media = MediaFileUpload(pdf_path, mimetype="application/pdf", resumable=False)
            f = drive_svc.files().create(
                body=metadata,
                media_body=media,
                fields="id,name,webViewLink",
            ).execute()
            return f

        # Try the configured folder first; fall back to Drive root on 404
        uploaded_to_folder = False
        try:
            if folder_id:
                file = _upload(folder_id)
                uploaded_to_folder = True
            else:
                file = _upload(None)
        except Exception as folder_err:
            if folder_id and "404" in str(folder_err):
                print(
                    f"[google_tools] Folder {folder_id!r} not accessible "
                    f"({folder_err}); uploading to Drive root instead."
                )
                file = _upload(None)
            else:
                raise

        file_id = file["id"]
        cv_url = file.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")

        # Make the file readable by anyone with the link
        drive_svc.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
        ).execute()

        result = {
            "status": "ok",
            "file_id": file_id,
            "filename": filename,
            "cv_url": cv_url,
        }
        if folder_id and not uploaded_to_folder:
            result["warning"] = (
                f"Folder ID {folder_id!r} was not accessible — file uploaded to Drive root. "
                "To fix: open the folder in Drive, click Share, and add your Google account with Editor access."
            )
        return result

    except Exception as e:
        return {"status": "error", "error": str(e)}


def log_application_to_sheets(
    job_link: str,
    company: str,
    position: str,
    cv_url: str,
) -> dict:
    """
    Append a job application row to the Google Sheets tracking spreadsheet.

    Columns: job_link | company | position | cv_url | status (default: draft)

    Requires GOOGLE_SHEETS_ID to be set in the environment.

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
        return {
            "status": "error",
            "error": "GOOGLE_SHEETS_ID is not set. Add it to your .env file.",
        }

    try:
        creds = _get_credentials()
        sheets_svc = build("sheets", "v4", credentials=creds)

        tab = _resolve_tab_name(sheets_svc, sheet_id)
        row = [job_link, company, position, cv_url, _DEFAULT_STATUS]
        sheets_svc.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range=f"'{tab}'!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

        spreadsheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        return {
            "status": "ok",
            "spreadsheet_url": spreadsheet_url,
            "row_added": row,
        }

    except Exception as e:
        return {"status": "error", "error": str(e)}
