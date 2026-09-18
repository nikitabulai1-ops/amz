"""Tests for backend/google_client.py using fake/mock Google API service
objects. No real network calls, no real Google account, no real
credentials anywhere in this file.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import google_client as gc  # noqa: E402
from googleapiclient.errors import HttpError  # noqa: E402


class FakeHttpResponse:
    """Duck-typed stand-in for the httplib2.Response HttpError expects."""
    def __init__(self, status: int):
        self.status = status
        self.reason = "mocked error"


def http_error(status: int, message: str = "error") -> HttpError:
    return HttpError(resp=FakeHttpResponse(status), content=message.encode())


def make_fake_service(create_result=None, create_error=None, list_result=None, list_error=None):
    service = mock.MagicMock()
    if create_error is not None:
        service.files.return_value.create.return_value.execute.side_effect = create_error
    elif create_result is not None:
        service.files.return_value.create.return_value.execute.return_value = create_result
    if list_error is not None:
        service.files.return_value.list.return_value.execute.side_effect = list_error
    elif list_result is not None:
        service.files.return_value.list.return_value.execute.return_value = list_result
    return service


def make_fake_sheets_service(append_result=None, append_error=None, get_result=None,
                              get_error=None, update_result=None, update_error=None):
    service = mock.MagicMock()
    values = service.spreadsheets.return_value.values.return_value
    if append_error is not None:
        values.append.return_value.execute.side_effect = append_error
    elif append_result is not None:
        values.append.return_value.execute.return_value = append_result
    if get_error is not None:
        values.get.return_value.execute.side_effect = get_error
    elif get_result is not None:
        values.get.return_value.execute.return_value = get_result
    if update_error is not None:
        values.update.return_value.execute.side_effect = update_error
    elif update_result is not None:
        values.update.return_value.execute.return_value = update_result
    return service


SAMPLE_FILE_RESULT = {
    "id": "file123", "name": "report.txt", "mimeType": "text/plain",
    "webViewLink": "https://drive.google.com/file/d/file123", "parents": ["folder1"],
}


class CredentialLoadingTests(unittest.TestCase):
    def test_missing_token_file_returns_missing_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "does-not-exist.json"
            creds, status, err = gc._load_credentials(token_path=token_path)
            self.assertIsNone(creds)
            self.assertEqual(status, gc.GoogleStatus.MISSING_TOKEN)
            self.assertIn("google_auth_setup.py", err)

    def test_corrupt_token_file_returns_invalid_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "token.json"
            token_path.write_text("not valid json at all {{{")
            creds, status, err = gc._load_credentials(token_path=token_path)
            self.assertIsNone(creds)
            self.assertEqual(status, gc.GoogleStatus.INVALID_CREDENTIALS)

    def test_token_file_missing_required_fields_returns_invalid_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "token.json"
            token_path.write_text(json.dumps({"not": "a real token structure"}))
            creds, status, err = gc._load_credentials(token_path=token_path)
            self.assertIsNone(creds)
            self.assertEqual(status, gc.GoogleStatus.INVALID_CREDENTIALS)


class ApprovalGateTests(unittest.TestCase):
    """Every write action must refuse before touching any service when
    confirmed=False — proven here by passing a mock service and asserting
    it was never called."""

    def test_upload_without_confirmation_is_refused(self):
        fake_service = mock.MagicMock()
        result = gc.upload_file_to_drive(
            gc.DriveUploadRequest(local_path="/tmp/whatever.txt", confirmed=False),
            _drive_service=fake_service,
        )
        self.assertEqual(result.status, gc.GoogleStatus.APPROVAL_REQUIRED)
        fake_service.files.assert_not_called()

    def test_create_doc_without_confirmation_is_refused(self):
        fake_service = mock.MagicMock()
        result = gc.create_google_doc(
            gc.GoogleDocCreateRequest(local_path="/tmp/whatever.txt", confirmed=False),
            _drive_service=fake_service,
        )
        self.assertEqual(result.status, gc.GoogleStatus.APPROVAL_REQUIRED)
        fake_service.files.assert_not_called()

    def test_create_sheet_without_confirmation_is_refused(self):
        fake_service = mock.MagicMock()
        result = gc.create_google_sheet(
            gc.GoogleSheetCreateRequest(local_path="/tmp/whatever.csv", confirmed=False),
            _drive_service=fake_service,
        )
        self.assertEqual(result.status, gc.GoogleStatus.APPROVAL_REQUIRED)
        fake_service.files.assert_not_called()

    def test_append_rows_without_confirmation_is_refused(self):
        fake_service = mock.MagicMock()
        result = gc.append_sheet_rows(
            gc.SheetAppendRequest(spreadsheet_id="sheet1", rows=[["a", "b"]], confirmed=False),
            _sheets_service=fake_service,
        )
        self.assertEqual(result.status, gc.GoogleStatus.APPROVAL_REQUIRED)
        fake_service.spreadsheets.assert_not_called()

    def test_update_values_without_confirmation_is_refused(self):
        fake_service = mock.MagicMock()
        result = gc.update_sheet_values(
            gc.SheetUpdateRequest(spreadsheet_id="sheet1", values=[["x"]], sheet_range="A1", confirmed=False),
            _sheets_service=fake_service,
        )
        self.assertEqual(result.status, gc.GoogleStatus.APPROVAL_REQUIRED)
        fake_service.spreadsheets.assert_not_called()

    def test_read_values_needs_no_confirmation(self):
        fake_service = make_fake_sheets_service(get_result={"values": [["a"]], "range": "Sheet1!A1"})
        result = gc.read_sheet_values(
            gc.SheetReadRequest(spreadsheet_id="sheet1", sheet_range="Sheet1"),
            _sheets_service=fake_service,
        )
        self.assertEqual(result.status, gc.GoogleStatus.SUCCESS)

    def test_find_files_needs_no_confirmation(self):
        fake_service = make_fake_service(list_result={"files": [SAMPLE_FILE_RESULT]})
        result = gc.find_drive_files(gc.DriveFindRequest(), _drive_service=fake_service)
        self.assertEqual(result.status, gc.GoogleStatus.SUCCESS)


class MissingCredentialsAtCallTimeTests(unittest.TestCase):
    """Confirms the credential gate applies even for an approved write —
    approval alone doesn't skip the missing-token check."""

    def test_confirmed_upload_without_credentials_returns_missing_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "no-token-here.json"
            with tempfile.NamedTemporaryFile(suffix=".txt") as f:
                f.write(b"draft content")
                f.flush()
                with mock.patch.object(gc, "DEFAULT_TOKEN_PATH", token_path):
                    result = gc.upload_file_to_drive(
                        gc.DriveUploadRequest(local_path=f.name, confirmed=True)
                    )
            self.assertEqual(result.status, gc.GoogleStatus.MISSING_TOKEN)


class InvalidInputTests(unittest.TestCase):
    def test_upload_missing_local_file(self):
        result = gc.upload_file_to_drive(
            gc.DriveUploadRequest(local_path="/no/such/file/anywhere.txt", confirmed=True),
            _drive_service=mock.MagicMock(),
        )
        self.assertEqual(result.status, gc.GoogleStatus.INVALID_INPUT)

    def test_create_doc_missing_local_file(self):
        result = gc.create_google_doc(
            gc.GoogleDocCreateRequest(local_path="/no/such/file.md", confirmed=True),
            _drive_service=mock.MagicMock(),
        )
        self.assertEqual(result.status, gc.GoogleStatus.INVALID_INPUT)

    def test_create_sheet_missing_local_file(self):
        result = gc.create_google_sheet(
            gc.GoogleSheetCreateRequest(local_path="/no/such/file.csv", confirmed=True),
            _drive_service=mock.MagicMock(),
        )
        self.assertEqual(result.status, gc.GoogleStatus.INVALID_INPUT)

    def test_append_empty_rows_rejected(self):
        result = gc.append_sheet_rows(
            gc.SheetAppendRequest(spreadsheet_id="sheet1", rows=[], confirmed=True),
            _sheets_service=mock.MagicMock(),
        )
        self.assertEqual(result.status, gc.GoogleStatus.INVALID_INPUT)

    def test_update_empty_values_rejected(self):
        result = gc.update_sheet_values(
            gc.SheetUpdateRequest(spreadsheet_id="sheet1", values=[], sheet_range="A1", confirmed=True),
            _sheets_service=mock.MagicMock(),
        )
        self.assertEqual(result.status, gc.GoogleStatus.INVALID_INPUT)


class DriveUploadTests(unittest.TestCase):
    def test_successful_upload(self):
        with tempfile.NamedTemporaryFile(suffix=".txt") as f:
            f.write(b"a drafted report")
            f.flush()
            service = make_fake_service(create_result=SAMPLE_FILE_RESULT)
            result = gc.upload_file_to_drive(
                gc.DriveUploadRequest(local_path=f.name, confirmed=True),
                _drive_service=service,
            )
        self.assertEqual(result.status, gc.GoogleStatus.SUCCESS)
        self.assertEqual(result.file.id, "file123")
        self.assertEqual(result.file.name, "report.txt")

    def test_upload_permission_denied(self):
        with tempfile.NamedTemporaryFile(suffix=".txt") as f:
            f.write(b"content")
            f.flush()
            service = make_fake_service(create_error=http_error(403))
            result = gc.upload_file_to_drive(
                gc.DriveUploadRequest(local_path=f.name, confirmed=True),
                _drive_service=service,
            )
        self.assertEqual(result.status, gc.GoogleStatus.PERMISSION_DENIED)

    def test_upload_not_found_error(self):
        with tempfile.NamedTemporaryFile(suffix=".txt") as f:
            f.write(b"content")
            f.flush()
            service = make_fake_service(create_error=http_error(404))
            result = gc.upload_file_to_drive(
                gc.DriveUploadRequest(local_path=f.name, confirmed=True),
                _drive_service=service,
            )
        self.assertEqual(result.status, gc.GoogleStatus.NOT_FOUND)

    def test_upload_generic_exception_is_api_error(self):
        with tempfile.NamedTemporaryFile(suffix=".txt") as f:
            f.write(b"content")
            f.flush()
            service = mock.MagicMock()
            service.files.return_value.create.return_value.execute.side_effect = RuntimeError("boom")
            result = gc.upload_file_to_drive(
                gc.DriveUploadRequest(local_path=f.name, confirmed=True),
                _drive_service=service,
            )
        self.assertEqual(result.status, gc.GoogleStatus.API_ERROR)
        self.assertIn("boom", result.error)


class DriveFindTests(unittest.TestCase):
    def test_find_returns_files(self):
        service = make_fake_service(list_result={"files": [SAMPLE_FILE_RESULT]})
        result = gc.find_drive_files(gc.DriveFindRequest(query="report"), _drive_service=service)
        self.assertEqual(result.status, gc.GoogleStatus.SUCCESS)
        self.assertEqual(len(result.files), 1)
        self.assertEqual(result.files[0].id, "file123")

    def test_find_empty_result_warns_about_drive_file_scope(self):
        service = make_fake_service(list_result={"files": []})
        result = gc.find_drive_files(gc.DriveFindRequest(), _drive_service=service)
        self.assertEqual(result.status, gc.GoogleStatus.SUCCESS)
        self.assertEqual(result.files, [])
        self.assertTrue(any("drive.file" in w for w in result.warnings))


class GoogleDocTests(unittest.TestCase):
    def test_create_doc_success(self):
        with tempfile.NamedTemporaryFile(suffix=".md") as f:
            f.write(b"# Draft Agreement\n\nTerms...")
            f.flush()
            service = make_fake_service(create_result={
                "id": "doc123", "name": "Draft Agreement", "mimeType": gc.DOC_MIME_TYPE,
                "webViewLink": "https://docs.google.com/document/d/doc123", "parents": [],
            })
            result = gc.create_google_doc(
                gc.GoogleDocCreateRequest(local_path=f.name, confirmed=True),
                _drive_service=service,
            )
        self.assertEqual(result.status, gc.GoogleStatus.SUCCESS)
        self.assertEqual(result.file.mime_type, gc.DOC_MIME_TYPE)


class GoogleSheetCreateTests(unittest.TestCase):
    def test_create_sheet_success(self):
        with tempfile.NamedTemporaryFile(suffix=".csv") as f:
            f.write(b"date,product,margin\n2026-01-01,Widget,28.5\n")
            f.flush()
            service = make_fake_service(create_result={
                "id": "sheet123", "name": "Deal Tracker", "mimeType": gc.SHEET_MIME_TYPE,
                "webViewLink": "https://docs.google.com/spreadsheets/d/sheet123", "parents": [],
            })
            result = gc.create_google_sheet(
                gc.GoogleSheetCreateRequest(local_path=f.name, confirmed=True),
                _drive_service=service,
            )
        self.assertEqual(result.status, gc.GoogleStatus.SUCCESS)
        self.assertEqual(result.spreadsheet_id, "sheet123")


class SheetAppendTests(unittest.TestCase):
    def test_append_success(self):
        service = make_fake_sheets_service(append_result={
            "updates": {"updatedRange": "Sheet1!A2:C2", "updatedRows": 1, "updatedCells": 3}
        })
        result = gc.append_sheet_rows(
            gc.SheetAppendRequest(spreadsheet_id="sheet1", rows=[["a", "b", "c"]], confirmed=True),
            _sheets_service=service,
        )
        self.assertEqual(result.status, gc.GoogleStatus.SUCCESS)
        self.assertEqual(result.updated_rows, 1)
        self.assertEqual(result.updated_cells, 3)

    def test_append_permission_denied(self):
        service = make_fake_sheets_service(append_error=http_error(403))
        result = gc.append_sheet_rows(
            gc.SheetAppendRequest(spreadsheet_id="sheet1", rows=[["a"]], confirmed=True),
            _sheets_service=service,
        )
        self.assertEqual(result.status, gc.GoogleStatus.PERMISSION_DENIED)


class SheetReadTests(unittest.TestCase):
    def test_read_success(self):
        service = make_fake_sheets_service(get_result={"values": [["a", "b"], ["1", "2"]], "range": "Sheet1!A1:B2"})
        result = gc.read_sheet_values(
            gc.SheetReadRequest(spreadsheet_id="sheet1", sheet_range="Sheet1"),
            _sheets_service=service,
        )
        self.assertEqual(result.status, gc.GoogleStatus.SUCCESS)
        self.assertEqual(result.values, [["a", "b"], ["1", "2"]])

    def test_read_not_found(self):
        service = make_fake_sheets_service(get_error=http_error(404))
        result = gc.read_sheet_values(
            gc.SheetReadRequest(spreadsheet_id="nonexistent", sheet_range="Sheet1"),
            _sheets_service=service,
        )
        self.assertEqual(result.status, gc.GoogleStatus.NOT_FOUND)


class SheetUpdateTests(unittest.TestCase):
    def test_update_success(self):
        service = make_fake_sheets_service(update_result={
            "updatedRange": "Sheet1!A1:B1", "updatedRows": 1, "updatedCells": 2,
        })
        result = gc.update_sheet_values(
            gc.SheetUpdateRequest(spreadsheet_id="sheet1", values=[["x", "y"]], sheet_range="A1:B1", confirmed=True),
            _sheets_service=service,
        )
        self.assertEqual(result.status, gc.GoogleStatus.SUCCESS)
        self.assertEqual(result.updated_cells, 2)

    def test_update_api_error(self):
        service = make_fake_sheets_service(update_error=http_error(500))
        result = gc.update_sheet_values(
            gc.SheetUpdateRequest(spreadsheet_id="sheet1", values=[["x"]], sheet_range="A1", confirmed=True),
            _sheets_service=service,
        )
        self.assertEqual(result.status, gc.GoogleStatus.API_ERROR)


if __name__ == "__main__":
    unittest.main()
