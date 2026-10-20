"""The email outbox (SAD §5.4): a QUEUED email_messages row commits with the change that sends
it, then `emails.send_email` delivers it over SMTP on queue email.

A link token in an email's body is usable only until the row ends SENT or FAILED: from then on
the database keeps the body with the token masked.
"""

import logging
import os
import smtplib
import uuid
from email.message import EmailMessage
from typing import Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.worker import tenant_task

log = logging.getLogger(__name__)


def deliver(message: EmailMessage) -> None:
    """Hand message to the SMTP server: Mailpit locally, SES or Resend in production."""
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"]), timeout=30) as smtp:
        # Mailpit takes plain SMTP without login; a provider that wants a login wants TLS too.
        if username := os.environ.get("SMTP_USERNAME"):
            smtp.starttls()
            smtp.login(username, os.environ["SMTP_PASSWORD"])
        smtp.send_message(message)


@tenant_task(name="emails.send_email", queue="email")
def send_email(tenant_id: uuid.UUID, session: Session, email_id: str) -> None:
    """Send one QUEUED email; the row lock keeps a redelivered task from sending it twice."""
    email = session.execute(
        text(
            "SELECT id, to_address, subject, body FROM email_messages"
            " WHERE id = :id AND status = 'QUEUED' FOR UPDATE"
        ),
        {"id": email_id},
    ).one_or_none()
    if email is None:
        return  # redelivered (acks_late) after it finished
    message = EmailMessage()
    message["From"] = os.environ["EMAIL_FROM"]
    message["To"] = email.to_address
    message["Subject"] = email.subject
    # The idempotency key: a provider or mail client drops a second message with the same id.
    # ponytail: a worker that dies after sending and before committing sends again on
    # redelivery; plain SMTP has nothing better than the Message-ID.
    message["Message-ID"] = f"<{email.id}@smart-ats>"
    message.set_content(email.body)
    try:
        deliver(message)
    except (OSError, smtplib.SMTPException) as e:
        # Only the type: SMTP errors quote the recipient's address (NFR-SEC-10).
        log.warning("sending email %s failed: %s", email.id, type(e).__name__)
        finish(session, email.id, "FAILED")
        return
    finish(session, email.id, "SENT")


def finish(session: Session, email_id: uuid.UUID, status: Literal["SENT", "FAILED"]) -> None:
    """End the email as status, masking any link token in its body."""
    session.execute(
        text(
            "UPDATE email_messages SET status = :status,"
            "  sent_at = CASE WHEN :status = 'SENT' THEN now() END,"
            "  body = regexp_replace(body, 'token=[A-Za-z0-9_-]+', 'token=[redacted]', 'g')"
            " WHERE id = :id"
        ),
        {"id": email_id, "status": status},
    )
