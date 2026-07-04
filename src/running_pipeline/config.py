"""Environment-backed settings.

Mirrors the full contract in .env.example. Later-phase variables (sync,
metrics, streams) are parsed and validated here so the contract stays in
one place, even though Phase 0 code only uses the Strava credentials.

Secrets are SecretStr so they can never leak through repr()/logging;
call .get_secret_value() only at the point of use.
"""

from datetime import date
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Rotated Strava tokens are persisted here, outside version control
# (.secrets/ and strava_tokens.json are both gitignored).
DEFAULT_TOKEN_FILE = Path(".secrets/strava_tokens.json")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Strava API (Phase 0)
    strava_client_id: str
    strava_client_secret: SecretStr
    # Bootstrap only: used for the very first refresh when no token file
    # exists yet. After that the rotated token in the token file wins.
    strava_refresh_token: SecretStr | None = None

    # Database (decision D2)
    postgres_host: str = "localhost"
    postgres_port: int = 5433
    postgres_db: str = "running_analytics_db"
    postgres_user: str = "running_user"
    postgres_password: SecretStr

    # Sync configuration (decisions D5, D6)
    sync_start_date: date = date(2024, 1, 1)
    sync_overlap_days: int = 14

    # Metrics configuration (decision D9)
    easy_hr_max: int = 152

    # Stream ingestion (decision D15 — used from Phase 5 / Release 1.1)
    stream_min_moving_minutes: int = 45
    stream_max_activities_per_run: int = 50

    token_file: Path = DEFAULT_TOKEN_FILE


def load_settings() -> Settings:
    return Settings()
