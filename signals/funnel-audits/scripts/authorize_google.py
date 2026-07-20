from __future__ import annotations

import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]

CLIENT_SECRET = Path.home() / ".config/gws/client_secret.json"
OUTPUT = Path(__file__).parents[1] / ".secrets/google-oauth.json"


def main() -> None:
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    credentials = flow.run_local_server(port=0, prompt="consent select_account")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(credentials.to_json())
    OUTPUT.chmod(0o600)
    print(f"Authorized {credentials.id_token.get('email') if credentials.id_token else 'account'}")
    print(f"Credential written securely to {OUTPUT}")


if __name__ == "__main__":
    main()
