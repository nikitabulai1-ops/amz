"""One-time interactive Google authorization for AMZ-VA.

Run this yourself, once, from a terminal:

    python3 backend/google_auth_setup.py

It is NOT meant to be run automatically by Claude, and this task
deliberately does not run it — connecting your Google account is your
call to make, when you're ready.

Before running it:
  1. In Google Cloud Console, create an OAuth Client ID of type
     "Desktop app" (enable the Drive, Sheets, and Docs APIs on that
     project first).
  2. Download its JSON file.
  3. Save it at exactly the path this script expects — printed below if
     it's missing, and documented in backend/.env.example.

What it does: opens your browser to Google's own consent screen, you log
in and approve, and the resulting authorization is saved to a token file
— both files living outside this repository. Nothing here prints, logs,
or stores any secret or token content anywhere in this codebase; the only
things printed are a plain confirmation message and the file path.
"""

import sys

from google_client import DEFAULT_CLIENT_SECRET_PATH, DEFAULT_TOKEN_PATH, SCOPES


def main() -> None:
    if not DEFAULT_CLIENT_SECRET_PATH.exists():
        print(
            f"No Google client secret found at {DEFAULT_CLIENT_SECRET_PATH}\n\n"
            "Before running this script:\n"
            "  1. In Google Cloud Console, create an OAuth Client ID of type "
            "'Desktop app' (with the Drive, Sheets, and Docs APIs enabled on that project).\n"
            "  2. Download its JSON file.\n"
            f"  3. Save it at exactly this path: {DEFAULT_CLIENT_SECRET_PATH}\n"
            "     (create the parent folder first if it doesn't exist yet)\n",
            file=sys.stderr,
        )
        sys.exit(1)

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(DEFAULT_CLIENT_SECRET_PATH), SCOPES)
    creds = flow.run_local_server(port=0)

    DEFAULT_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_TOKEN_PATH.write_text(creds.to_json())

    print(f"Google authorization complete. Token saved to: {DEFAULT_TOKEN_PATH}")
    print("(Nothing else was printed — the token contents were never shown here.)")


if __name__ == "__main__":
    main()
