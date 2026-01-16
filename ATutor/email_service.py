# ATutor/email_service.py
import os
import requests

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_SEND_URL = "https://api.resend.com/emails"

# Default sender. You chose benj@almamath.com
WELCOME_FROM = os.getenv("WELCOME_FROM_EMAIL", "Ben @ Alma <benj@almamath.com>")

def send_welcome_email(to_email: str, first_name: str | None = None) -> None:
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY is not set in environment variables.")

    name = (first_name or "").strip()
    greet = f"Hi {name}," if name else "Hi,"

    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Arial,sans-serif;
                line-height:1.5; color:#111;">
      <p>{greet}</p>

      <p>Welcome to <b>Alma</b> 👋</p>

      <p>
        Alma turns your homework into interactive questions and helps you like a tutor.
        If anything feels confusing or broken, reply to this email — I read everything.
      </p>

      <p style="margin-top:20px;">
        — Ben
        <br/>
        <span style="color:#666;">Founder, Alma</span>
      </p>
    </div>
    """

    payload = {
        "from": WELCOME_FROM,
        "to": [to_email],
        "subject": "Welcome to Alma 👋",
        "html": html,
    }

    r = requests.post(
        RESEND_SEND_URL,
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=20,
    )

    if r.status_code >= 300:
        raise RuntimeError(f"Resend send failed ({r.status_code}): {r.text}")