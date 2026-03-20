"""CV Compiler microservice — LaTeX → PDF + optional Google Drive upload."""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, Form, UploadFile
from fastapi.responses import Response
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from pydantic import BaseModel
import re

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="CV Compiler")

# ---------------------------------------------------------------------------
# Google auth
# ---------------------------------------------------------------------------

_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
]

_CREDENTIALS_FILE = Path(
    os.environ.get("GOOGLE_CREDENTIALS_FILE", "/secrets/gcp-creds/credentials.json")
)
_TOKEN_FILE = Path(
    os.environ.get("GOOGLE_TOKEN_FILE", "/secrets/gcp-token/token.json")
)
# Secret-mounted files are read-only; keep refreshed tokens in a writable path.
_WRITABLE_TOKEN_FILE = Path("/tmp/google_token.json")


def _get_credentials() -> Credentials:
    creds: Credentials | None = None
    # Try writable copy first (has refreshed token), then fall back to mounted secret.
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
                    f"Google credentials not found at {_CREDENTIALS_FILE}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(_CREDENTIALS_FILE), _SCOPES
            )
            creds = flow.run_local_server(port=0)
        _WRITABLE_TOKEN_FILE.write_text(creds.to_json())
    return creds


# ---------------------------------------------------------------------------
# pdflatex helpers
# ---------------------------------------------------------------------------


def _find_pdflatex() -> str:
    for candidate in [
        "/root/bin/pdflatex",
        "/usr/local/bin/pdflatex",
        "pdflatex",
        "/opt/homebrew/bin/pdflatex",
        "/Library/TeX/texbin/pdflatex",
    ]:
        try:
            subprocess.run([candidate, "--version"], capture_output=True, check=True)
            return candidate
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    raise FileNotFoundError("pdflatex not found")


_PDFLATEX: str | None = None


def _get_pdflatex() -> str:
    global _PDFLATEX
    if _PDFLATEX is None:
        _PDFLATEX = _find_pdflatex()
    return _PDFLATEX


def _compile(latex_source: str) -> bytes:
    """Compile LaTeX source to PDF bytes."""
    tmp_dir = tempfile.mkdtemp(prefix="cv_")
    tex_path = os.path.join(tmp_dir, "cv.tex")

    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(latex_source)

    result = subprocess.run(
        [_get_pdflatex(), "-interaction=nonstopmode", f"-output-directory={tmp_dir}", tex_path],
        capture_output=True,
        text=True,
        timeout=120,
    )

    pdf_path = os.path.join(tmp_dir, "cv.pdf")
    if not os.path.isfile(pdf_path):
        raise RuntimeError(f"pdflatex compilation failed: {result.stderr or result.stdout}")

    with open(pdf_path, "rb") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Drive upload helper
# ---------------------------------------------------------------------------


def _sanitize_position(position: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", position).strip()
    return re.sub(r"[\s]+", "_", cleaned)


def _upload_to_drive(pdf_bytes: bytes, job_position: str) -> dict:
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")
    position_slug = _sanitize_position(job_position)
    filename = f"Andrii_Popesku_{position_slug}.pdf"

    creds = _get_credentials()
    drive_svc = build("drive", "v3", credentials=creds)

    def _upload(parent: str | None) -> dict:
        metadata: dict = {"name": filename, "mimeType": "application/pdf"}
        if parent:
            metadata["parents"] = [parent]
        media = MediaIoBaseUpload(
            io.BytesIO(pdf_bytes), mimetype="application/pdf", resumable=False
        )
        return (
            drive_svc.files()
            .create(body=metadata, media_body=media, fields="id,name,webViewLink")
            .execute()
        )

    uploaded_to_folder = False
    try:
        if folder_id:
            file = _upload(folder_id)
            uploaded_to_folder = True
        else:
            file = _upload(None)
    except Exception as folder_err:
        if folder_id and "404" in str(folder_err):
            file = _upload(None)
        else:
            raise

    file_id = file["id"]
    cv_url = file.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")

    drive_svc.permissions().create(
        fileId=file_id, body={"type": "anyone", "role": "reader"}
    ).execute()

    result = {"status": "ok", "file_id": file_id, "filename": filename, "cv_url": cv_url}
    if folder_id and not uploaded_to_folder:
        result["warning"] = f"Folder {folder_id!r} not accessible — uploaded to Drive root."
    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class CompileRequest(BaseModel):
    latex_source: str


class CompileAndUploadRequest(BaseModel):
    latex_source: str
    job_position: str


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/compile")
def compile_endpoint(body: CompileRequest):
    pdf_bytes = _compile(body.latex_source)
    return Response(content=pdf_bytes, media_type="application/pdf")


@app.post("/upload-to-drive")
async def upload_to_drive_endpoint(
    pdf: UploadFile,
    job_position: str = Form(...),
):
    pdf_bytes = await pdf.read()
    return _upload_to_drive(pdf_bytes, job_position)


@app.post("/compile-and-upload")
def compile_and_upload_endpoint(body: CompileAndUploadRequest):
    pdf_bytes = _compile(body.latex_source)
    return _upload_to_drive(pdf_bytes, body.job_position)
