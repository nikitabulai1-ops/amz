"""Tests for backend/google_auth_setup.py's pre-flight check only — the
actual interactive OAuth flow needs a real browser and a real Google
account, so it is deliberately not run or mocked here. This only proves
the script refuses cleanly (no crash, no secret printed) when the
client-secret file hasn't been placed yet.
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import google_auth_setup  # noqa: E402


class MissingClientSecretTests(unittest.TestCase):
    def test_exits_cleanly_with_guidance_when_client_secret_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_path = Path(tmp) / "google_client_secret.json"
            stderr = io.StringIO()
            with mock.patch.object(google_auth_setup, "DEFAULT_CLIENT_SECRET_PATH", missing_path):
                with contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as ctx:
                        google_auth_setup.main()
            self.assertEqual(ctx.exception.code, 1)
            message = stderr.getvalue()
            self.assertIn(str(missing_path), message)
            self.assertIn("Desktop app", message)
            # Never prints anything resembling a secret/token value.
            self.assertNotIn("access_token", message)
            self.assertNotIn("refresh_token", message)


if __name__ == "__main__":
    unittest.main()
