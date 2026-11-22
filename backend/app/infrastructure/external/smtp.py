"""Opt-in password-reset SMTP with verified TLS and sanitized failure categories."""
from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.headerregistry import Address
from email.message import EmailMessage
from urllib.parse import quote

import anyio

from app.core.config import Settings

log = logging.getLogger(__name__)


class SMTPPasswordResetSender:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, *, recipient: str, token: str) -> bool:
        if not self._settings.can_send_password_reset:
            return False
        worker = asyncio.create_task(asyncio.to_thread(self._send, recipient, token))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            # Keep the admission slot until the socket-bounded SMTP thread has really closed.
            with anyio.CancelScope(shield=True):
                while not worker.done():
                    try:
                        await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        continue
            raise

    def _send(self, recipient: str, token: str) -> bool:
        settings = self._settings
        if not settings.can_send_password_reset:
            return False
        try:
            if any(char in recipient for char in "\r\n"):
                raise ValueError("Invalid recipient")
            message = EmailMessage()
            message["Subject"] = "Reset your SupplyOS password"
            message["From"] = Address(settings.smtp_from_name, addr_spec=settings.smtp_from)
            message["To"] = Address(addr_spec=recipient)
            link = f"{settings.password_reset_url}#token={quote(token, safe='')}"
            message.set_content(
                "A password reset was requested for your SupplyOS account.\n\n"
                f"Reset your password: {link}\n\n"
                f"This single-use link expires in {settings.password_reset_hours} hour(s).\n"
                "If you did not request this, ignore this email.\n"
            )
            context = ssl.create_default_context() if settings.smtp_tls_mode != "plain" else None
            options = {"host": settings.smtp_host, "port": settings.smtp_port,
                       "timeout": settings.smtp_timeout_seconds}
            relay = (
                smtplib.SMTP_SSL(**options, context=context)
                if settings.smtp_tls_mode == "tls" else smtplib.SMTP(**options)
            )
            with relay:
                relay.set_debuglevel(0)
                relay.ehlo()
                if settings.smtp_tls_mode == "starttls":
                    relay.starttls(context=context)
                    relay.ehlo()
                if settings.smtp_username:
                    relay.login(settings.smtp_username, settings.smtp_password)
                refused = relay.send_message(
                    message, from_addr=settings.smtp_from, to_addrs=[recipient],
                )
            if refused:
                log.warning("Password reset SMTP failed (recipient_refused)")
                return False
            return True
        except smtplib.SMTPAuthenticationError:
            category = "authentication"
        except smtplib.SMTPRecipientsRefused:
            category = "recipient_refused"
        except ssl.SSLError:
            category = "tls"
        except TimeoutError:
            category = "timeout"
        except (OSError, smtplib.SMTPServerDisconnected):
            category = "connection"
        except smtplib.SMTPException:
            category = "relay"
        except Exception:
            category = "delivery"
        log.warning("Password reset SMTP failed (%s)", category)
        return False
