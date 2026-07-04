"""Minimal Strava API client: OAuth token refresh, athlete profile.

Strava rotates the refresh token on every refresh; the newest one is
persisted to a gitignored local file immediately, before any other call,
because losing it forces a full browser re-authorization.

Token values must never appear in logs, exceptions, or reprs.
"""

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import requests

from running_pipeline.config import Settings

AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
API_BASE = "https://www.strava.com/api/v3"

DEFAULT_SCOPE = "read,activity:read_all"
# Refresh a bit before the reported expiry to avoid using a token that
# dies mid-request.
EXPIRY_MARGIN_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 30


class StravaAuthError(RuntimeError):
    """Auth/token exchange failed. Message is safe to print (no tokens)."""


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str
    expires_at: int  # unix epoch seconds

    def is_fresh(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return self.expires_at > now + EXPIRY_MARGIN_SECONDS


class TokenStore:
    """Persists the token trio outside version control (0600 perms)."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> TokenSet | None:
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text())
        return TokenSet(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=int(data["expires_at"]),
        )

    def save(self, tokens: TokenSet) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "expires_at": tokens.expires_at,
            },
            indent=2,
        )
        # Atomic replace: a crash mid-write must never lose the previous
        # (still-valid) rotated refresh token.
        fd, tmp_path = tempfile.mkstemp(dir=self.path.parent, prefix=".tokens-")
        try:
            with os.fdopen(fd, "w") as tmp_file:
                tmp_file.write(payload)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self.path)
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise


class StravaClient:
    def __init__(self, settings: Settings, store: TokenStore | None = None):
        self._settings = settings
        self._store = store or TokenStore(settings.token_file)
        self._session = requests.Session()

    # ── OAuth ─────────────────────────────────────────────────────────

    def authorize_url(self, scope: str = DEFAULT_SCOPE) -> str:
        """URL for the one-time browser authorization (initial or re-auth)."""
        params = urlencode(
            {
                "client_id": self._settings.strava_client_id,
                "redirect_uri": "http://localhost/exchange_token",
                "response_type": "code",
                "approval_prompt": "auto",
                "scope": scope,
            }
        )
        return f"{AUTHORIZE_URL}?{params}"

    def exchange_code(self, code: str) -> TokenSet:
        """Exchange an authorization code for tokens and persist them."""
        return self._token_request(grant_type="authorization_code", code=code)

    def refresh_access_token(self) -> TokenSet:
        """Refresh using the newest known refresh token and persist the rotation."""
        stored = self._store.load()
        if stored is not None:
            refresh_token = stored.refresh_token
        elif self._settings.strava_refresh_token is not None:
            refresh_token = self._settings.strava_refresh_token.get_secret_value()
        else:
            raise StravaAuthError(
                "No refresh token available: token file "
                f"{self._store.path} does not exist and STRAVA_REFRESH_TOKEN "
                "is unset. Run `running-pipeline authorize` first."
            )
        return self._token_request(grant_type="refresh_token", refresh_token=refresh_token)

    def get_access_token(self) -> str:
        """Reuse the stored access token while fresh; refresh otherwise."""
        stored = self._store.load()
        if stored is not None and stored.is_fresh():
            return stored.access_token
        return self.refresh_access_token().access_token

    def _token_request(self, **grant_fields: str) -> TokenSet:
        response = self._session.post(
            TOKEN_URL,
            data={
                "client_id": self._settings.strava_client_id,
                "client_secret": self._settings.strava_client_secret.get_secret_value(),
                **grant_fields,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            # Strava error bodies for the token endpoint describe the failed
            # field (e.g. invalid refresh_token) without echoing secrets.
            raise StravaAuthError(
                f"Strava token request failed (HTTP {response.status_code}): "
                f"{_safe_error_body(response)}"
            )
        data = response.json()
        tokens = TokenSet(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=int(data["expires_at"]),
        )
        # Persist before returning: the old refresh token is already dead.
        self._store.save(tokens)
        return tokens

    # ── API ───────────────────────────────────────────────────────────

    def get_athlete(self) -> dict:
        response = self._session.get(
            f"{API_BASE}/athlete",
            headers={"Authorization": f"Bearer {self.get_access_token()}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()


def _safe_error_body(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return "<non-JSON error body>"
    # Belt and braces: token-shaped keys never make it into the message.
    if isinstance(body, dict):
        body = {k: v for k, v in body.items() if "token" not in k.lower()}
    return json.dumps(body)
