"""Activity pagination, bounded retries, and rate-limit handling (all HTTP mocked)."""

import time
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest
import requests
import responses

from running_pipeline.config import Settings
from running_pipeline.strava_client import (
    API_BASE,
    TOKEN_URL,
    RateLimitApproaching,
    RateLimitExceeded,
    StravaApiError,
    StravaAuthError,
    StravaClient,
    TokenSet,
    TokenStore,
)

ACTIVITIES_URL = f"{API_BASE}/athlete/activities"
AFTER = datetime(2024, 1, 1, tzinfo=UTC)  # epoch 1704067200


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


def make_client(tmp_path, sleeps: list[float] | None = None) -> StravaClient:
    """Client with a fresh stored access token; backoff sleeps are recorded."""
    settings = make_settings(tmp_path)
    TokenStore(settings.token_file).save(
        TokenSet(
            access_token="stored-access-token",
            refresh_token="stored-refresh-token",
            expires_at=int(time.time()) + 3600,
        )
    )
    sink = [] if sleeps is None else sleeps
    return StravaClient(settings, sleep=sink.append)


def activities(start: int, count: int) -> list[dict]:
    return [{"id": i, "sport_type": "Run"} for i in range(start, start + count)]


def query_of(call) -> dict:
    return parse_qs(urlparse(call.request.url).query)


# ── Pagination ────────────────────────────────────────────────────────


@responses.activate
def test_paginates_until_short_page(tmp_path):
    responses.get(ACTIVITIES_URL, json=activities(0, 2))
    responses.get(ACTIVITIES_URL, json=activities(2, 2))
    responses.get(ACTIVITIES_URL, json=activities(4, 1))

    pages = list(make_client(tmp_path).iter_activity_pages(after=AFTER, per_page=2))

    assert [len(page) for page in pages] == [2, 2, 1]
    assert [a["id"] for page in pages for a in page] == [0, 1, 2, 3, 4]
    assert [query_of(call)["page"] for call in responses.calls] == [["1"], ["2"], ["3"]]


@responses.activate
def test_request_carries_after_epoch_and_max_per_page(tmp_path):
    responses.get(ACTIVITIES_URL, json=[])

    assert list(make_client(tmp_path).iter_activity_pages(after=AFTER)) == []

    query = query_of(responses.calls[0])
    assert query["after"] == ["1704067200"]
    assert query["per_page"] == ["200"]


@responses.activate
def test_exactly_full_final_page_ends_on_next_empty_page(tmp_path):
    responses.get(ACTIVITIES_URL, json=activities(0, 2))
    responses.get(ACTIVITIES_URL, json=[])

    pages = list(make_client(tmp_path).iter_activity_pages(after=AFTER, per_page=2))

    assert [len(page) for page in pages] == [2]
    assert len(responses.calls) == 2


def test_naive_after_datetime_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="timezone-aware"):
        next(make_client(tmp_path).iter_activity_pages(after=datetime(2024, 1, 1)))


# ── Bounded retries ───────────────────────────────────────────────────


@responses.activate
def test_transient_500_is_retried_with_backoff(tmp_path):
    responses.get(ACTIVITIES_URL, status=500)
    responses.get(ACTIVITIES_URL, json=[])
    sleeps = []

    assert list(make_client(tmp_path, sleeps).iter_activity_pages(after=AFTER)) == []

    assert sleeps == [1]
    assert len(responses.calls) == 2


@responses.activate
def test_persistent_500_raises_after_bounded_retries(tmp_path):
    for _ in range(4):
        responses.get(ACTIVITIES_URL, status=500, json={"message": "server error"})
    sleeps = []

    with pytest.raises(StravaApiError) as excinfo:
        list(make_client(tmp_path, sleeps).iter_activity_pages(after=AFTER))

    assert sleeps == [1, 2, 4]
    assert len(responses.calls) == 4
    message = str(excinfo.value)
    assert "500" in message
    assert "stored-access-token" not in message


@responses.activate
def test_connection_errors_are_retried_then_actionable(tmp_path):
    for _ in range(4):
        responses.get(ACTIVITIES_URL, body=requests.ConnectionError("connection refused"))
    sleeps = []

    with pytest.raises(StravaApiError, match="unreachable"):
        list(make_client(tmp_path, sleeps).iter_activity_pages(after=AFTER))

    assert sleeps == [1, 2, 4]


@responses.activate
def test_client_error_is_immediate_and_actionable(tmp_path):
    responses.get(ACTIVITIES_URL, status=404, json={"message": "Record Not Found"})
    sleeps = []

    with pytest.raises(StravaApiError) as excinfo:
        list(make_client(tmp_path, sleeps).iter_activity_pages(after=AFTER))

    assert sleeps == []
    assert len(responses.calls) == 1
    assert "404" in str(excinfo.value)


# ── Rate limits ───────────────────────────────────────────────────────


@responses.activate
def test_429_stops_immediately_without_retry(tmp_path):
    responses.get(
        ACTIVITIES_URL,
        status=429,
        json={"message": "Rate Limit Exceeded"},
        headers={"X-RateLimit-Limit": "100,1000", "X-RateLimit-Usage": "101,350"},
    )
    sleeps = []

    with pytest.raises(RateLimitExceeded) as excinfo:
        list(make_client(tmp_path, sleeps).iter_activity_pages(after=AFTER))

    assert sleeps == []
    assert len(responses.calls) == 1
    assert "101/100" in str(excinfo.value)


@responses.activate
def test_stops_cleanly_after_current_page_when_usage_approaches_limit(tmp_path):
    responses.get(
        ACTIVITIES_URL,
        json=activities(0, 2),
        headers={"X-RateLimit-Limit": "100,1000", "X-RateLimit-Usage": "95,300"},
    )
    received = []

    with pytest.raises(RateLimitApproaching) as excinfo:
        for page in make_client(tmp_path).iter_activity_pages(after=AFTER, per_page=2):
            received.append(page)

    assert [a["id"] for page in received for a in page] == [0, 1]  # full page kept
    assert len(responses.calls) == 1  # page 2 never requested
    assert "95/100" in str(excinfo.value)


@responses.activate
def test_short_final_page_completes_even_at_high_usage(tmp_path):
    # A short page means the sync is finished; crossing the threshold on
    # the way out must not mark the run as stopped early.
    responses.get(
        ACTIVITIES_URL,
        json=activities(0, 1),
        headers={"X-RateLimit-Limit": "100,1000", "X-RateLimit-Usage": "99,300"},
    )

    pages = list(make_client(tmp_path).iter_activity_pages(after=AFTER, per_page=2))

    assert [len(page) for page in pages] == [1]


@responses.activate
def test_read_rate_limit_headers_also_stop(tmp_path):
    responses.get(
        ACTIVITIES_URL,
        json=activities(0, 2),
        headers={
            "X-RateLimit-Limit": "100,1000",
            "X-RateLimit-Usage": "10,100",  # overall fine
            "X-ReadRateLimit-Limit": "100,1000",
            "X-ReadRateLimit-Usage": "50,950",  # daily read usage at 95%
        },
    )

    with pytest.raises(RateLimitApproaching) as excinfo:
        list(make_client(tmp_path).iter_activity_pages(after=AFTER, per_page=2))

    assert "950/1000" in str(excinfo.value)


@responses.activate
def test_missing_rate_limit_headers_never_stop_the_sync(tmp_path):
    responses.get(ACTIVITIES_URL, json=activities(0, 2))
    responses.get(ACTIVITIES_URL, json=[])

    pages = list(make_client(tmp_path).iter_activity_pages(after=AFTER, per_page=2))

    assert [len(page) for page in pages] == [2]


# ── Auth failures ─────────────────────────────────────────────────────


@responses.activate
def test_401_forces_one_refresh_and_retries(tmp_path):
    responses.get(ACTIVITIES_URL, status=401, json={"message": "Authorization Error"})
    responses.post(
        TOKEN_URL,
        json={
            "access_token": "fresh-access-token",
            "refresh_token": "rotated-refresh-token",
            "expires_at": int(time.time()) + 21600,
        },
    )
    responses.get(ACTIVITIES_URL, json=[])
    settings_path = tmp_path / "strava_tokens.json"

    assert list(make_client(tmp_path).iter_activity_pages(after=AFTER)) == []

    retried = responses.calls[-1].request
    assert retried.headers["Authorization"] == "Bearer fresh-access-token"
    # The forced refresh persisted the rotation (Phase 0 invariant).
    assert TokenStore(settings_path).load().refresh_token == "rotated-refresh-token"


@responses.activate
def test_persistent_401_is_actionable_and_token_free(tmp_path):
    responses.get(ACTIVITIES_URL, status=401, json={"message": "Authorization Error"})
    responses.post(
        TOKEN_URL,
        json={
            "access_token": "fresh-access-token",
            "refresh_token": "rotated-refresh-token",
            "expires_at": int(time.time()) + 21600,
        },
    )
    responses.get(ACTIVITIES_URL, status=401, json={"message": "Authorization Error"})

    with pytest.raises(StravaAuthError, match="authorize") as excinfo:
        list(make_client(tmp_path).iter_activity_pages(after=AFTER))

    message = str(excinfo.value)
    for secret in (
        "stored-access-token",
        "fresh-access-token",
        "stored-refresh-token",
        "rotated-refresh-token",
    ):
        assert secret not in message
