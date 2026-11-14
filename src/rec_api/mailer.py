"""Sending sign-in codes."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Protocol

from .config import Settings


class Mailer(Protocol):
    def send_code(self, to: str, code: str) -> None: ...


class ConsoleMailer:
    """No email server set up: print the code where the API is running."""

    def send_code(self, to: str, code: str) -> None:
        print(f"[rec-api] sign-in code for {to}: {code}", flush=True)


class SMTPMailer:
    def __init__(self, settings: Settings):
        self.s = settings

    def send_code(self, to: str, code: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = "Your UCLA Rec sign-in code"
        msg["From"], msg["To"] = self.s.smtp_from, to
        msg.set_content(
            f"Your code is {code}. It expires in {self.s.code_ttl_minutes} minutes.\n"
            "If you did not ask for it, ignore this email."
        )
        with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            if self.s.smtp_user:
                smtp.login(self.s.smtp_user, self.s.smtp_password or "")
            smtp.send_message(msg)


def default_mailer(settings: Settings) -> Mailer:
    return SMTPMailer(settings) if settings.smtp_host else ConsoleMailer()
