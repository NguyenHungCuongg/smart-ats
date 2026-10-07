"""Smoke tests for the mailpit service (Infra 04).

Run against the Compose stack from the host: see README "Infrastructure".
"""

import json
import os
import smtplib
import urllib.parse
import urllib.request
import uuid
from email.message import EmailMessage

# The addresses Compose publishes on.
SMTP_PORT = 1025
API_URL = "http://127.0.0.1:8025/api/v1"


def test_sent_email_is_retrievable_from_the_api() -> None:
    subject = f"smoke-{uuid.uuid4().hex}"
    recipient = "candidate@example.com"
    message = EmailMessage()
    message["From"] = os.environ["EMAIL_FROM"]
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content("Hello from the smoke test.")
    with smtplib.SMTP("127.0.0.1", SMTP_PORT, timeout=10) as smtp:
        smtp.send_message(message)

    query = urllib.parse.urlencode({"query": f"subject:{subject}"})
    with urllib.request.urlopen(f"{API_URL}/search?{query}", timeout=10) as response:
        found = json.load(response)["messages"]
    assert [(m["Subject"], m["To"][0]["Address"]) for m in found] == [(subject, recipient)]
