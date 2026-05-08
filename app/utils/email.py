"""SMTP email dispatch utility for password-reset (and future) transactional email.

Only stdlib ``smtplib`` / ``email`` are used — no additional packages required.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Callable

logger = logging.getLogger(__name__)

_RESET_EMAIL_SUBJECT = "Password reset request"

_RESET_EMAIL_TEXT = """\
Hi,

We received a request to reset the password for the account associated with this email.

Click the link below to choose a new password. The link is valid for {ttl_minutes} minutes.

{reset_url}

If you did not request a password reset, you can safely ignore this email.
""".strip()

_RESET_EMAIL_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"></head>
<body style="font-family:sans-serif;color:#1a1a1a;max-width:520px;margin:40px auto">
  <h2 style="color:#0d9488">Password Reset</h2>
  <p>We received a request to reset the password for the account associated with this email.</p>
  <p>
    <a href="{reset_url}"
       style="display:inline-block;padding:10px 20px;background:#0d9488;color:#fff;
              border-radius:4px;text-decoration:none;font-weight:bold">
      Reset password
    </a>
  </p>
  <p style="color:#666;font-size:13px">
    This link expires in {ttl_minutes} minutes.<br>
    If you did not request a reset, you can safely ignore this email.
  </p>
</body>
</html>
""".strip()


def build_smtp_dispatch(
    smtp_host: str,
    smtp_port: int,
    smtp_username: str | None,
    smtp_password: str | None,
    from_address: str,
    use_tls: bool,
    ttl_minutes: int = 30,
) -> Callable[[str, str, str], None]:
    """Return a dispatch callable ``(to_email, token, reset_url) -> None``.

    The returned callable opens a fresh SMTP connection for each call so that
    it is safe to use across threads / gunicorn workers without shared state.
    Errors are logged and re-raised so the caller can decide to mask them.
    """

    def _dispatch(to_email: str, token: str, reset_url: str) -> None:  # noqa: ARG001  (token unused here)
        msg = MIMEMultipart("alternative")
        msg["Subject"] = _RESET_EMAIL_SUBJECT
        msg["From"] = from_address
        msg["To"] = to_email

        msg.attach(MIMEText(_RESET_EMAIL_TEXT.format(reset_url=reset_url, ttl_minutes=ttl_minutes), "plain"))
        msg.attach(MIMEText(_RESET_EMAIL_HTML.format(reset_url=reset_url, ttl_minutes=ttl_minutes), "html"))

        try:
            if use_tls:
                context = ssl.create_default_context()
                with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                    server.ehlo()
                    server.starttls(context=context)
                    server.ehlo()
                    if smtp_username and smtp_password:
                        server.login(smtp_username, smtp_password)
                    server.sendmail(from_address, [to_email], msg.as_string())
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                    server.ehlo()
                    if smtp_username and smtp_password:
                        server.login(smtp_username, smtp_password)
                    server.sendmail(from_address, [to_email], msg.as_string())
        except smtplib.SMTPException as exc:
            logger.error(
                "PASSWORD_RESET_EMAIL_SMTP_ERROR to=%s error=%s",
                to_email.split("@", 1)[-1],  # log domain only, not full address
                exc,
            )
            raise
        except OSError as exc:
            logger.error(
                "PASSWORD_RESET_EMAIL_CONNECT_ERROR host=%s port=%s error=%s",
                smtp_host,
                smtp_port,
                exc,
            )
            raise

        domain = to_email.split("@", 1)[-1] if "@" in to_email else "unknown"
        logger.info("PASSWORD_RESET_EMAIL_SENT recipient_domain=%s", domain)

    return _dispatch
