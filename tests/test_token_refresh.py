"""Token refresh and rotated-refresh-token persistence (all HTTP mocked)."""

import json
import stat
import time

import pytest
import responses

from running_pipeline.config import Settings
from running_pipeline.strava_client import (
    TOKEN_URL,
    StravaAuthError,
    StravaClient,
    TokenSet,
    TokenStore,
)


def make_settings(tmp_path, **overrides) -> Settings:
    defaults = {
        "strava_client_id": "12345",
        "strava_client_secret": "test-client-secret",
        "strava_refresh_token": "env-bootstrap-token",
        "postgres_password": "test-db-password",
        "token_file": tmp_path / "strava_tokens.json",
    }
    defaults.update(overrides)
    # _env_file=None keeps tests hermetic: never read the developer's .env.
    return Settings(_env_file=None, **defaults)


def token_response(refresh_token="rotated-token", expires_in=21600):
    return {
        "access_token": "new-access-token",
        "refresh_token": refresh_token,
        "expires_at": int(time.time()) + expires_in,
    }


@responses.activate
def test_refresh_persists_rotated_refresh_token(tmp_path):
    responses.post(TOKEN_URL, json=token_response(refresh_token="rotated-token"))
    client = StravaClient(make_settings(tmp_path))

    tokens = client.refresh_access_token()

    assert tokens.refresh_token == "rotated-token"
    on_disk = json.loads((tmp_path / "strava_tokens.json").read_text())
    assert on_disk["refresh_token"] == "rotated-token"
    assert on_disk["access_token"] == "new-access-token"


@responses.activate
def test_bootstrap_uses_env_refresh_token_when_no_file(tmp_path):
    responses.post(TOKEN_URL, json=token_response())
    client = StravaClient(make_settings(tmp_path))

    client.refresh_access_token()

    sent = responses.calls[0].request.body
    assert "env-bootstrap-token" in sent


@responses.activate
def test_file_token_wins_over_env_bootstrap(tmp_path):
    settings = make_settings(tmp_path)
    TokenStore(settings.token_file).save(
        TokenSet(access_token="old", refresh_token="file-token", expires_at=0)
    )
    responses.post(TOKEN_URL, json=token_response())

    StravaClient(settings).refresh_access_token()

    sent = responses.calls[0].request.body
    assert "file-token" in sent
    assert "env-bootstrap-token" not in sent


@responses.activate
def test_fresh_access_token_skips_refresh(tmp_path):
    # No responses registered: any HTTP call would raise ConnectionError.
    settings = make_settings(tmp_path)
    TokenStore(settings.token_file).save(
        TokenSet(
            access_token="still-valid",
            refresh_token="unused",
            expires_at=int(time.time()) + 3600,
        )
    )

    assert StravaClient(settings).get_access_token() == "still-valid"


@responses.activate
def test_refresh_failure_is_actionable_and_leaves_file_untouched(tmp_path):
    settings = make_settings(tmp_path)
    original = TokenSet(access_token="old", refresh_token="file-token", expires_at=0)
    TokenStore(settings.token_file).save(original)
    responses.post(
        TOKEN_URL,
        json={"message": "Bad Request", "errors": [{"field": "refresh_token"}]},
        status=400,
    )

    with pytest.raises(StravaAuthError) as excinfo:
        StravaClient(settings).refresh_access_token()

    message = str(excinfo.value)
    assert "400" in message
    assert "file-token" not in message  # never echo token values
    assert TokenStore(settings.token_file).load() == original


@responses.activate
def test_missing_refresh_token_everywhere_is_actionable(tmp_path):
    client = StravaClient(make_settings(tmp_path, strava_refresh_token=None))

    with pytest.raises(StravaAuthError, match="authorize"):
        client.refresh_access_token()


@responses.activate
def test_token_file_written_with_owner_only_permissions(tmp_path):
    responses.post(TOKEN_URL, json=token_response())
    client = StravaClient(make_settings(tmp_path))

    client.refresh_access_token()

    mode = stat.S_IMODE((tmp_path / "strava_tokens.json").stat().st_mode)
    assert mode == 0o600
