"""Google Drive/Docs/Sheets client for AMZ-VA — the delivery layer only.

This module holds every call to Google's APIs. It contains no business
logic (no deal analysis, no formatting decisions about what a report
should say) — it only moves already-drafted local files to/from Google,
exactly like keepa_client.py is a pure data client for Keepa. Callers
(the tool registry, and ultimately Claude) decide what to draft and when
a write action has actually been approved.

AUTHENTICATION — Google's official installed-app OAuth flow, your own
personal Google account, narrowest practical scope:

    SCOPES = ["https://www.googleapis.com/auth/drive.file"]

`drive.file` only grants access to files this app itself creates, or that
you explicitly open with it — never your whole Drive. That is intentional
(least privilege) and it is a real limitation, not a bug: `find_drive_files`
and `read_sheet_values` can only see/read files this app already has a
relationship with. If you later need this app to reach pre-existing files
it didn't create, that must be a deliberate, separate scope decision (e.g.
adding `drive.readonly`) — never silently widened here.

This module NEVER launches an interactive login itself — see
`backend/google_auth_setup.py` for the one-time setup step you run
yourself, from a terminal. If no valid saved authorization is found, every
function below returns a clear `missing_token`/`invalid_credentials`
status pointing at that script — never a guess, never a fake success.

CREDENTIALS LOCATION — outside this repository entirely, so there is
nothing here for git to ever pick up:

    GOOGLE_CLIENT_SECRET_PATH   default: ~/.config/amz-va/google_client_secret.json
    GOOGLE_TOKEN_PATH           default: ~/.config/amz-va/google_token.json

Both are plain file paths (override with the environment variables above
if you want them elsewhere) — nothing secret is ever hardcoded, printed,
logged, or committed by this module.

APPROVAL — every write action (upload, create Doc, create Sheet, append,
update) requires `confirmed=true` on its request. Without it, the
function returns `status: approval_required` and makes no API call at
all — this is enforced in code, not just by instruction. Set `confirmed`
to true only after the owner has explicitly approved that specific
action in the conversation. Read-only actions (`find_drive_files`,
`read_sheet_values`) need no confirmation since they change nothing.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from pydantic import BaseModel, Field

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

DEFAULT_CLIENT_SECRET_PATH = Path(
    os.getenv("GOOGLE_CLIENT_SECRET_PATH", str(Path.home() / ".config" / "amz-va" / "google_client_secret.json"))
).expanduser()
DEFAULT_TOKEN_PATH = Path(
    os.getenv("GOOGLE_TOKEN_PATH", str(Path.home() / ".config" / "amz-va" / "google_token.json"))
).expanduser()

DOC_MIME_TYPE = "application/vnd.google-apps.document"
SHEET_MIME_TYPE = "application/vnd.google-apps.spreadsheet"


class GoogleStatus(str, Enum):
    SUCCESS = "success"
    APPROVAL_REQUIRED = "approval_required"
    MISSING_TOKEN = "missing_token"
    INVALID_CREDENTIALS = "invalid_credentials"
    INVALID_INPUT = "invalid_input"
    NOT_FOUND = "not_found"
    PERMISSION_DENIED = "permission_denied"
    API_ERROR = "api_error"


# ============================================================
# Schema
# ============================================================

class DriveFileInfo(BaseModel):
    id: str
    name: str
    mime_type: Optional[str] = None
    web_view_link: Optional[str] = None
    parents: list[str] = Field(default_factory=list)


class GoogleActionResult(BaseModel):
    status: GoogleStatus
    error: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class DriveUploadResult(GoogleActionResult):
    file: Optional[DriveFileInfo] = None


class DriveListResult(GoogleActionResult):
    files: list[DriveFileInfo] = Field(default_factory=list)


class DocResult(GoogleActionResult):
    file: Optional[DriveFileInfo] = None


class SheetResult(GoogleActionResult):
    file: Optional[DriveFileInfo] = None
    spreadsheet_id: Optional[str] = None


class SheetWriteResult(GoogleActionResult):
    updated_range: Optional[str] = None
    updated_rows: Optional[int] = None
    updated_cells: Optional[int] = None


class SheetReadResult(GoogleActionResult):
    values: list[list[str]] = Field(default_factory=list)
    range_returned: Optional[str] = None


class DriveUploadRequest(BaseModel):
    local_path: str
    folder_id: Optional[str] = None
    filename: Optional[str] = None
    confirmed: bool = Field(False, description="Must be true — set only after the owner has "
                             "explicitly approved this specific upload in this conversation.")


class DriveFindRequest(BaseModel):
    query: Optional[str] = Field(None, description="Substring to match against file names")
    folder_id: Optional[str] = None
    max_results: int = 20


class GoogleDocCreateRequest(BaseModel):
    local_path: str
    title: Optional[str] = None
    folder_id: Optional[str] = None
    confirmed: bool = Field(False, description="Must be true — set only after explicit owner approval.")


class GoogleSheetCreateRequest(BaseModel):
    local_path: str = Field(..., description="Path to a local CSV file, e.g. an export of the deal tracker")
    title: Optional[str] = None
    folder_id: Optional[str] = None
    confirmed: bool = Field(False, description="Must be true — set only after explicit owner approval.")


class SheetAppendRequest(BaseModel):
    spreadsheet_id: str
    rows: list[list[str]]
    sheet_range: str = "Sheet1!A1"
    confirmed: bool = Field(False, description="Must be true — set only after explicit owner approval.")


class SheetReadRequest(BaseModel):
    spreadsheet_id: str
    sheet_range: str = "Sheet1"


class SheetUpdateRequest(BaseModel):
    spreadsheet_id: str
    values: list[list[str]]
    sheet_range: str
    confirmed: bool = Field(False, description="Must be true — set only after explicit owner approval.")


# ============================================================
# Auth / service construction
# ============================================================

def _load_credentials(token_path: Optional[Path] = None) -> tuple[Optional[Credentials], Optional[GoogleStatus], Optional[str]]:
    """Loads and, if needed, refreshes the saved Google authorization.

    Never launches an interactive login — that only happens in
    google_auth_setup.py. Returns (creds, None, None) on success, or
    (None, status, message) on any failure, so callers never have to
    guess why Google access isn't available."""
    token_path = token_path or DEFAULT_TOKEN_PATH

    if not token_path.exists():
        return None, GoogleStatus.MISSING_TOKEN, (
            f"No Google authorization found at {token_path}. Run "
            "backend/google_auth_setup.py once, from a terminal, to connect your account."
        )

    try:
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    except Exception as e:
        return None, GoogleStatus.INVALID_CREDENTIALS, f"Could not read the saved Google authorization: {e}"

    if creds and creds.valid:
        return creds, None, None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(GoogleAuthRequest())
        except Exception as e:
            return None, GoogleStatus.INVALID_CREDENTIALS, (
                f"Google authorization refresh failed: {e}. Run backend/google_auth_setup.py again."
            )
        try:
            token_path.write_text(creds.to_json())
        except OSError:
            pass  # refreshed creds are still usable this run even if the save fails
        return creds, None, None

    return None, GoogleStatus.INVALID_CREDENTIALS, (
        "Saved Google authorization is invalid and cannot be refreshed. "
        "Run backend/google_auth_setup.py again."
    )


def _build_service(name: str, version: str, creds: Credentials):
    return build(name, version, credentials=creds, cache_discovery=False)


def _map_http_error(e: HttpError) -> GoogleStatus:
    status_code = getattr(getattr(e, "resp", None), "status", None)
    if status_code in (401, 403):
        return GoogleStatus.PERMISSION_DENIED
    if status_code == 404:
        return GoogleStatus.NOT_FOUND
    return GoogleStatus.API_ERROR


def _file_info(result: dict) -> DriveFileInfo:
    return DriveFileInfo(
        id=result["id"], name=result.get("name", ""), mime_type=result.get("mimeType"),
        web_view_link=result.get("webViewLink"), parents=result.get("parents", []),
    )


def _drive_or_error(_drive_service: Any) -> tuple[Any, Optional[GoogleStatus], Optional[str]]:
    if _drive_service is not None:
        return _drive_service, None, None
    creds, status, err = _load_credentials()
    if status is not None:
        return None, status, err
    return _build_service("drive", "v3", creds), None, None


def _sheets_or_error(_sheets_service: Any) -> tuple[Any, Optional[GoogleStatus], Optional[str]]:
    if _sheets_service is not None:
        return _sheets_service, None, None
    creds, status, err = _load_credentials()
    if status is not None:
        return None, status, err
    return _build_service("sheets", "v4", creds), None, None


# ============================================================
# Drive
# ============================================================

def upload_file_to_drive(req: DriveUploadRequest, _drive_service: Any = None) -> DriveUploadResult:
    if not req.confirmed:
        return DriveUploadResult(status=GoogleStatus.APPROVAL_REQUIRED,
                                  error="This upload has not been approved yet.")
    path = Path(req.local_path)
    if not path.is_file():
        return DriveUploadResult(status=GoogleStatus.INVALID_INPUT, error=f"Local file not found: {req.local_path}")

    service, status, err = _drive_or_error(_drive_service)
    if status is not None:
        return DriveUploadResult(status=status, error=err)

    try:
        metadata: dict = {"name": req.filename or path.name}
        if req.folder_id:
            metadata["parents"] = [req.folder_id]
        media = MediaFileUpload(str(path), resumable=False)
        result = service.files().create(
            body=metadata, media_body=media, fields="id, name, mimeType, webViewLink, parents"
        ).execute()
        return DriveUploadResult(status=GoogleStatus.SUCCESS, file=_file_info(result))
    except HttpError as e:
        return DriveUploadResult(status=_map_http_error(e), error=str(e))
    except Exception as e:
        return DriveUploadResult(status=GoogleStatus.API_ERROR, error=str(e))


def find_drive_files(req: DriveFindRequest, _drive_service: Any = None) -> DriveListResult:
    service, status, err = _drive_or_error(_drive_service)
    if status is not None:
        return DriveListResult(status=status, error=err)

    query_parts = ["trashed = false"]
    if req.query:
        safe = req.query.replace("\\", "\\\\").replace("'", "\\'")
        query_parts.append(f"name contains '{safe}'")
    if req.folder_id:
        query_parts.append(f"'{req.folder_id}' in parents")

    try:
        resp = service.files().list(
            q=" and ".join(query_parts), pageSize=req.max_results,
            fields="files(id, name, mimeType, webViewLink, parents)",
        ).execute()
        files = [_file_info(f) for f in resp.get("files", [])]
        warnings = []
        if not files:
            warnings.append(
                "No files found. With the drive.file scope, this can only see files this app "
                "created or that you explicitly opened with it — not your whole Drive."
            )
        return DriveListResult(status=GoogleStatus.SUCCESS, files=files, warnings=warnings)
    except HttpError as e:
        return DriveListResult(status=_map_http_error(e), error=str(e))
    except Exception as e:
        return DriveListResult(status=GoogleStatus.API_ERROR, error=str(e))


# ============================================================
# Docs (created via Drive's own format-conversion-on-upload — no
# separate Docs API scope or client needed for creation)
# ============================================================

def create_google_doc(req: GoogleDocCreateRequest, _drive_service: Any = None) -> DocResult:
    if not req.confirmed:
        return DocResult(status=GoogleStatus.APPROVAL_REQUIRED, error="Doc creation has not been approved yet.")
    path = Path(req.local_path)
    if not path.is_file():
        return DocResult(status=GoogleStatus.INVALID_INPUT, error=f"Local file not found: {req.local_path}")

    service, status, err = _drive_or_error(_drive_service)
    if status is not None:
        return DocResult(status=status, error=err)

    try:
        metadata: dict = {"name": req.title or path.stem, "mimeType": DOC_MIME_TYPE}
        if req.folder_id:
            metadata["parents"] = [req.folder_id]
        media = MediaFileUpload(str(path), mimetype="text/plain", resumable=False)
        result = service.files().create(
            body=metadata, media_body=media, fields="id, name, mimeType, webViewLink, parents"
        ).execute()
        return DocResult(status=GoogleStatus.SUCCESS, file=_file_info(result))
    except HttpError as e:
        return DocResult(status=_map_http_error(e), error=str(e))
    except Exception as e:
        return DocResult(status=GoogleStatus.API_ERROR, error=str(e))


# ============================================================
# Sheets
# ============================================================

def create_google_sheet(req: GoogleSheetCreateRequest, _drive_service: Any = None) -> SheetResult:
    if not req.confirmed:
        return SheetResult(status=GoogleStatus.APPROVAL_REQUIRED, error="Sheet creation has not been approved yet.")
    path = Path(req.local_path)
    if not path.is_file():
        return SheetResult(status=GoogleStatus.INVALID_INPUT, error=f"Local file not found: {req.local_path}")

    service, status, err = _drive_or_error(_drive_service)
    if status is not None:
        return SheetResult(status=status, error=err)

    try:
        metadata: dict = {"name": req.title or path.stem, "mimeType": SHEET_MIME_TYPE}
        if req.folder_id:
            metadata["parents"] = [req.folder_id]
        media = MediaFileUpload(str(path), mimetype="text/csv", resumable=False)
        result = service.files().create(
            body=metadata, media_body=media, fields="id, name, mimeType, webViewLink, parents"
        ).execute()
        return SheetResult(status=GoogleStatus.SUCCESS, file=_file_info(result), spreadsheet_id=result["id"])
    except HttpError as e:
        return SheetResult(status=_map_http_error(e), error=str(e))
    except Exception as e:
        return SheetResult(status=GoogleStatus.API_ERROR, error=str(e))


def append_sheet_rows(req: SheetAppendRequest, _sheets_service: Any = None) -> SheetWriteResult:
    if not req.confirmed:
        return SheetWriteResult(status=GoogleStatus.APPROVAL_REQUIRED, error="This append has not been approved yet.")
    if not req.rows:
        return SheetWriteResult(status=GoogleStatus.INVALID_INPUT, error="No rows supplied to append.")

    service, status, err = _sheets_or_error(_sheets_service)
    if status is not None:
        return SheetWriteResult(status=status, error=err)

    try:
        resp = service.spreadsheets().values().append(
            spreadsheetId=req.spreadsheet_id, range=req.sheet_range,
            valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
            body={"values": req.rows},
        ).execute()
        updates = resp.get("updates", {})
        return SheetWriteResult(
            status=GoogleStatus.SUCCESS, updated_range=updates.get("updatedRange"),
            updated_rows=updates.get("updatedRows"), updated_cells=updates.get("updatedCells"),
        )
    except HttpError as e:
        return SheetWriteResult(status=_map_http_error(e), error=str(e))
    except Exception as e:
        return SheetWriteResult(status=GoogleStatus.API_ERROR, error=str(e))


def read_sheet_values(req: SheetReadRequest, _sheets_service: Any = None) -> SheetReadResult:
    service, status, err = _sheets_or_error(_sheets_service)
    if status is not None:
        return SheetReadResult(status=status, error=err)

    try:
        resp = service.spreadsheets().values().get(
            spreadsheetId=req.spreadsheet_id, range=req.sheet_range,
        ).execute()
        return SheetReadResult(status=GoogleStatus.SUCCESS, values=resp.get("values", []),
                                range_returned=resp.get("range"))
    except HttpError as e:
        return SheetReadResult(status=_map_http_error(e), error=str(e))
    except Exception as e:
        return SheetReadResult(status=GoogleStatus.API_ERROR, error=str(e))


def update_sheet_values(req: SheetUpdateRequest, _sheets_service: Any = None) -> SheetWriteResult:
    if not req.confirmed:
        return SheetWriteResult(status=GoogleStatus.APPROVAL_REQUIRED, error="This update has not been approved yet.")
    if not req.values:
        return SheetWriteResult(status=GoogleStatus.INVALID_INPUT, error="No values supplied to update.")

    service, status, err = _sheets_or_error(_sheets_service)
    if status is not None:
        return SheetWriteResult(status=status, error=err)

    try:
        resp = service.spreadsheets().values().update(
            spreadsheetId=req.spreadsheet_id, range=req.sheet_range,
            valueInputOption="USER_ENTERED", body={"values": req.values},
        ).execute()
        return SheetWriteResult(
            status=GoogleStatus.SUCCESS, updated_range=resp.get("updatedRange"),
            updated_rows=resp.get("updatedRows"), updated_cells=resp.get("updatedCells"),
        )
    except HttpError as e:
        return SheetWriteResult(status=_map_http_error(e), error=str(e))
    except Exception as e:
        return SheetWriteResult(status=GoogleStatus.API_ERROR, error=str(e))
