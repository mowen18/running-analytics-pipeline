"""Command-line interface. Never prints or logs token values."""

import sys
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import click

from running_pipeline.config import load_settings
from running_pipeline.strava_client import DEFAULT_SCOPE, StravaAuthError, StravaClient


@click.group()
def cli():
    """Running Analytics Pipeline."""


@cli.command()
def athlete():
    """Fetch and print the authenticated athlete's profile."""
    client = StravaClient(load_settings())
    try:
        profile = client.get_athlete()
    except StravaAuthError as exc:
        raise click.ClickException(
            f"{exc}\nIf the refresh token is invalid or under-scoped, run "
            "`running-pipeline authorize` to re-authorize."
        ) from exc

    name = f"{profile.get('firstname', '')} {profile.get('lastname', '')}".strip()
    location = ", ".join(
        part for part in (profile.get("city"), profile.get("state"), profile.get("country")) if part
    )
    click.echo(f"Athlete id:  {profile.get('id')}")
    click.echo(f"Name:        {name or '<none>'}")
    click.echo(f"Username:    {profile.get('username') or '<none>'}")
    click.echo(f"Location:    {location or '<none>'}")
    click.echo(f"Created:     {profile.get('created_at') or '<unknown>'}")
    click.echo(f"Followers:   {profile.get('follower_count', '<hidden>')}")
    click.echo(f"Following:   {profile.get('friend_count', '<hidden>')}")


@cli.command()
@click.option("--scope", default=DEFAULT_SCOPE, show_default=True, help="OAuth scopes to request.")
@click.option(
    "--code",
    default=None,
    help="Authorization code, or the full redirect URL it came from. "
    "Skips the interactive prompt (needed in non-TTY shells).",
)
def authorize(scope: str, code: str | None):
    """One-time browser authorization (initial setup or re-scoping)."""
    settings = load_settings()
    client = StravaClient(settings)

    if code is None:
        click.echo("1. Open this URL in your browser and click Authorize:\n")
        click.echo(f"   {client.authorize_url(scope)}\n")
        click.echo(
            "2. You will be redirected to a localhost URL that fails to load —\n"
            "   that is expected. Copy the value of the `code` parameter from\n"
            "   the address bar (or copy the whole URL).\n"
        )
        code = click.prompt("3. Paste the authorization code or redirect URL")

    try:
        tokens = client.exchange_code(_extract_code(code))
    except StravaAuthError as exc:
        raise click.ClickException(str(exc)) from exc

    expires = datetime.fromtimestamp(tokens.expires_at, tz=UTC).isoformat()
    click.echo(f"\nAuthorized. Tokens saved to {settings.token_file} (access token")
    click.echo(f"expires {expires}). The STRAVA_REFRESH_TOKEN line in .env is now")
    click.echo("stale by design; the token file is authoritative from here on.")


def _extract_code(raw: str) -> str:
    """Accept either the bare authorization code or the full redirect URL."""
    raw = raw.strip()
    if "code=" not in raw:
        return raw
    query = urlparse(raw).query or raw.split("?", 1)[-1]
    values = parse_qs(query).get("code", [])
    if not values:
        raise click.ClickException("Could not find a `code` parameter in the pasted value.")
    return values[0]


if __name__ == "__main__":
    sys.exit(cli())
