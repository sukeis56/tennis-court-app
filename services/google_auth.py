import json
import os
from pathlib import Path
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

TOKEN_PATH = Path(__file__).parent.parent / "token.json"
CREDENTIALS_PATH = Path(__file__).parent.parent / "credentials.json"

# calendar-app の credentials を共有（なければ自前を使う）
CALENDAR_APP_CREDS = Path(__file__).parent.parent.parent / "calendar-app" / "credentials.json"
CALENDAR_APP_TOKEN = Path(__file__).parent.parent.parent / "calendar-app" / "token.json"


def _find_credentials_path() -> Path | None:
    if CREDENTIALS_PATH.exists():
        return CREDENTIALS_PATH
    if CALENDAR_APP_CREDS.exists():
        return CALENDAR_APP_CREDS
    return None


def get_flow(redirect_uri: str) -> Flow | None:
    # ローカルファイル
    creds_path = _find_credentials_path()
    if creds_path:
        return Flow.from_client_secrets_file(
            str(creds_path),
            scopes=SCOPES,
            redirect_uri=redirect_uri,
        )

    # 環境変数（Render用）
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
    if creds_json:
        try:
            parsed = json.loads(creds_json)
            web = parsed.get("web", parsed.get("installed", {}))
            client_config = {
                "web": {
                    "client_id": web.get("client_id", ""),
                    "client_secret": web.get("client_secret", ""),
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [redirect_uri],
                }
            }
            return Flow.from_client_config(
                client_config,
                scopes=SCOPES,
                redirect_uri=redirect_uri,
            )
        except Exception:
            pass

    return None


def save_credentials(creds: Credentials):
    data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else SCOPES,
    }
    try:
        TOKEN_PATH.write_text(json.dumps(data))
    except OSError:
        pass
    # 環境変数にも保存（Render等）
    os.environ["GOOGLE_TOKEN_JSON"] = json.dumps(data)


def load_credentials() -> Credentials | None:
    """token.json を探して認証情報を返す（ファイル → 環境変数の順）"""
    data = None

    # ファイルから読み込み
    for path in [TOKEN_PATH, CALENDAR_APP_TOKEN]:
        if path.exists():
            try:
                data = json.loads(path.read_text())
                break
            except Exception:
                pass

    # 環境変数から読み込み（Render用）
    if not data:
        token_json = os.getenv("GOOGLE_TOKEN_JSON", "")
        if token_json:
            try:
                data = json.loads(token_json)
            except Exception:
                pass

    if not data:
        return None

    try:
        creds = Credentials(
            token=data.get("token"),
            refresh_token=data.get("refresh_token"),
            token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            scopes=data.get("scopes", SCOPES),
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            save_credentials(creds)
        return creds if creds.valid else None
    except Exception:
        return None


def clear_credentials():
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
    os.environ.pop("GOOGLE_TOKEN_JSON", None)
