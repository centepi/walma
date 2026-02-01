# ATutor/email_service.py
import os
import requests
from typing import Optional, Dict, Any

import firebase_admin
from firebase_admin import firestore

from utils import FirebaseManager  # your existing initializer

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_SEND_URL = "https://api.resend.com/emails"

# Default sender. You chose benj@almamath.com
WELCOME_FROM = os.getenv("WELCOME_FROM_EMAIL", "Ben @ Alma <benj@almamath.com>")

# Firestore collection for all outbound emails
EMAIL_LOG_COLLECTION = os.getenv("EMAIL_LOG_COLLECTION", "EmailSends")


def _ensure_firebase_initialized() -> None:
    try:
        firebase_admin.get_app()
    except ValueError:
        FirebaseManager().initialize()


def _db():
    _ensure_firebase_initialized()
    return firestore.client()


def send_welcome_email(
    to_email: str,
    first_name: Optional[str] = None,
    uid: Optional[str] = None,
) -> str:
    """
    Sends the welcome email via Resend and logs attempts/results to Firestore.

    Returns:
        log_id (Firestore doc id) so callers can correlate with user events.
    """
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY is not set in environment variables.")

    html = """
    <div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Arial,sans-serif;
                line-height:1.5; color:#111;">
      <p><b>Fellow mathematician,</b></p>

      <p>
        I’m building Alma Math because I wanted something that doesn’t really exist yet:
        an AI tutor that can actually read your work and respond to it.
      </p>

      <p>
        Alma is still early, and I’m improving it constantly. Learning about your experience
        and thoughts on the app would genuinely mean a lot to me.
      </p>

      <p>
        If you notice anything that feels wrong, confusing, or incomplete, or if you have
        ideas or feedback, feel free to reply. I read every message myself and will respond.
      </p>

      <p>
        Many thanks, and I hope you enjoy your mathematical journey with us.
      </p>

      <p style="margin-top:20px;">
        Ben J
        <br/>
        <span style="color:#666;">Founder, Alma Math</span>
      </p>
    </div>
    """

    payload: Dict[str, Any] = {
        "from": WELCOME_FROM,
        "to": [to_email],
        "subject": "Welcome to Alma 👋",
        "html": html,
    }

    # 1) Create a durable audit log entry BEFORE sending
    db = _db()
    doc = db.collection(EMAIL_LOG_COLLECTION).document()
    log_id = doc.id

    doc.set(
        {
            "type": "welcome",
            "uid": uid,
            "to": to_email,
            "from": WELCOME_FROM,
            "subject": payload["subject"],
            "status": "attempted",  # attempted -> accepted|failed
            "createdAt": firestore.SERVER_TIMESTAMP,
        }
    )

    # 2) Send via Resend
    try:
        r = requests.post(
            RESEND_SEND_URL,
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
    except Exception as e:
        doc.update(
            {
                "status": "failed",
                "failedAt": firestore.SERVER_TIMESTAMP,
                "error": f"request_exception: {repr(e)}",
            }
        )
        raise

    # 3) Update log with provider response
    if r.status_code >= 300:
        doc.update(
            {
                "status": "failed",
                "failedAt": firestore.SERVER_TIMESTAMP,
                "provider": "resend",
                "httpStatus": r.status_code,
                "providerBody": r.text,
            }
        )
        raise RuntimeError(f"Resend send failed ({r.status_code}): {r.text}")

    # Resend typically returns JSON with an "id"
    resend_id = None
    try:
        data = r.json()
        resend_id = data.get("id")
    except Exception:
        data = None

    doc.update(
        {
            "status": "accepted",
            "acceptedAt": firestore.SERVER_TIMESTAMP,
            "provider": "resend",
            "httpStatus": r.status_code,
            "resendId": resend_id,
            "providerJson": data,
        }
    )

    return log_id