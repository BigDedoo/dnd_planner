"""Small transactional SMTP adapter. Never expose SMTP replies or recipients in errors."""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass, field
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .config import Settings


def usable_email(value: str | None) -> str | None:
    if (
        not value
        or not value.isascii()
        or any(ord(char) < 33 or ord(char) == 127 for char in value)
    ):
        return None
    try:
        address = Address(addr_spec=value)
        if not address.username or not address.domain or "." not in address.domain:
            return None
        return address.addr_spec
    except (ValueError, IndexError):
        return None


@dataclass(frozen=True)
class ReminderEmail:
    recipient: str = field(repr=False)
    subject: str = field(repr=False)
    body: str = field(repr=False)


class ReminderSender(Protocol):
    def send(self, message: ReminderEmail) -> None: ...


class EmailDeliveryError(RuntimeError):
    """Sanitized delivery failure; SMTP may include credentials or addresses."""


class SmtpReminderSender:
    def __init__(self, settings: Settings):
        if not settings.email_delivery_enabled:
            raise EmailDeliveryError("Email delivery is disabled")
        self.settings = settings

    def _authenticated_connection(self) -> smtplib.SMTP:
        server = smtplib.SMTP(
            self.settings.smtp_host, self.settings.smtp_port, timeout=15
        )
        try:
            server.ehlo()
            if self.settings.smtp_starttls:
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            server.login(
                self.settings.smtp_username,
                self.settings.smtp_password.get_secret_value(),
            )
            return server
        except Exception:
            server.close()
            raise

    def check_connection(self) -> None:
        try:
            server = self._authenticated_connection()
            server.close()
        except Exception:
            raise EmailDeliveryError(
                "SMTP connection or authentication failed"
            ) from None

    def send(self, message: ReminderEmail) -> None:
        server = None
        try:
            recipient = usable_email(message.recipient)
            if recipient is None:
                raise ValueError("Invalid recipient")
            email = EmailMessage()
            email["From"] = Address(
                self.settings.smtp_from_name, addr_spec=self.settings.smtp_from_email
            )
            email["Reply-To"] = self.settings.smtp_from_email
            email["To"] = recipient
            email["Subject"] = " ".join(message.subject.splitlines())
            email["Date"] = formatdate(localtime=False)
            email["Message-ID"] = make_msgid(
                domain=self.settings.smtp_from_email.split("@")[-1]
            )
            email.set_content(message.body)
            server = self._authenticated_connection()
            refused = server.send_message(
                email, from_addr=self.settings.smtp_from_email, to_addrs=[recipient]
            )
            if refused:
                raise EmailDeliveryError("SMTP delivery failed")
        except Exception:
            raise EmailDeliveryError("SMTP delivery failed") from None
        finally:
            # SMTP acceptance, not a subsequent QUIT reply, determines success.
            if server is not None:
                try:
                    server.close()
                except Exception:
                    pass
