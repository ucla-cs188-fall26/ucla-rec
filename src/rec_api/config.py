from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./rec.db"
    stale_after_minutes: int = 30

    # --- community reports -------------------------------------------------
    report_window_minutes: int = 45
    allowed_email_domains: tuple[str, ...] = ("ucla.edu", "g.ucla.edu")
    code_ttl_minutes: int = 10
    code_resend_seconds: int = 60
    code_max_attempts: int = 5
    session_days: int = 30
    # Signs stored email and token hashes. Set your own in production: changing
    # it signs everyone out.
    secret: str = "change-me"
    # Show the sign-in code in the API response. For local testing only.
    show_codes: bool = False

    # Outgoing email for sign-in codes. Without a host, codes print to the
    # server's console instead.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "no-reply@localhost"


def _stored_secret(database_url: str) -> str:
    """Make a random key on first run and keep it next to the database."""
    import secrets
    from pathlib import Path

    prefix = "sqlite:///"
    folder = Path(database_url[len(prefix):]).parent if database_url.startswith(prefix) else Path(".")
    path = folder / "rec.secret"
    try:
        if path.exists():
            return path.read_text().strip()
        value = secrets.token_hex(32)
        path.write_text(value)
        return value
    except OSError:
        return secrets.token_hex(32)  # read-only disk: works until restart


def settings_from_env() -> Settings:
    env = os.environ.get
    return Settings(
        database_url=env("REC_DATABASE_URL", "sqlite:///./rec.db"),
        stale_after_minutes=int(env("REC_STALE_AFTER_MINUTES", "30")),
        report_window_minutes=int(env("REC_REPORT_WINDOW_MINUTES", "45")),
        secret=env("REC_SECRET") or _stored_secret(env("REC_DATABASE_URL", "sqlite:///./rec.db")),
        show_codes=env("REC_SHOW_CODES", "").lower() in ("1", "true", "yes"),
        smtp_host=env("REC_SMTP_HOST") or None,
        smtp_port=int(env("REC_SMTP_PORT", "587")),
        smtp_user=env("REC_SMTP_USER") or None,
        smtp_password=env("REC_SMTP_PASSWORD") or None,
        smtp_from=env("REC_SMTP_FROM", "no-reply@localhost"),
    )
