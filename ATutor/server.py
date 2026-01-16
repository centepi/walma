# ATutor/server.py
import os
import json
import re
import requests
import google.generativeai as genai
from fastapi import FastAPI, Header, HTTPException, status  # ✅ UPDATED
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List
from dotenv import load_dotenv
import asyncio

from firebase_admin import firestore as admin_firestore  # ✅ NEW
from utils import FirebaseManager  # ✅ NEW
from auth_utils import verify_request_and_get_user  # ✅ NEW
from email_service import send_welcome_email  # ✅ NEW

# Prompts for tutor features
from prompts import get_analysis_prompt, get_chat_prompt, get_help_prompt

# Mount the new, focused routers
from leaderboard_routes import router as leaderboard_router
from profile_routes import router as profile_router

load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

app = FastAPI()

# --- Models for our API requests ---
class AnalysisRequest(BaseModel):
    image_data: str
    question_stem: str
    question_part: str
    solution_text: str

class ChatMessage(BaseModel):
    text: str
    is_user: bool

class ChatRequest(BaseModel):
    question_stem: str
    question_part: str
    solution_text: str
    student_work: str
    conversation_history: List[ChatMessage]

# --- Helpers ---

def _strip_status_tag(text: str):
    """
    Recognize an optional trailing tag of the form [[STATUS: COMPLETE]] or [[STATUS: INCOMPLETE]]
    and return (clean_text, complete_bool). Robust to extra whitespace; ignores mid-message tags.
    """
    prefix = "[[STATUS:"
    i = text.rfind(prefix)
    complete = False
    if i != -1:
        j = text.find("]]", i)
        # treat it as a tag only if it closes and nothing but whitespace follows
        if j != -1 and text[j + 2 :].strip() == "":
            value = text[i + len(prefix) : j].strip().upper()
            complete = value == "COMPLETE"
            text = text[:i].rstrip()
    return text, complete


def _extract_json_block(text: str) -> str:
    """Return the substring from the first '{' to the last '}' if present."""
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1].strip()
    return text.strip()


# Valid JSON single-character escapes after a backslash
_VALID_AFTER_BACKSLASH = set('\\/"bfnrtu"')

def _escape_invalid_backslashes(json_text: str) -> str:
    """
    Replace any backslash that is NOT followed by a valid JSON escape char
    with a double backslash. This safely fixes LaTeX sequences like \ln, \(
    inside JSON strings without touching proper escapes like \\n, \\u, \\",
    etc.
    """
    # We operate on the whole text; backslashes only appear inside strings
    # in our responses, so this is safe for our use-case.
    return re.sub(r'\\(?![\\/"bfnrtu])', r'\\\\', json_text)


def _safe_parse_model_json(raw_text: str):
    """
    Try to parse model JSON. On failure due to invalid escapes, attempt a
    minimal, safe repair by escaping illegal backslashes and retry.
    """
    block = _extract_json_block(raw_text)
    try:
        return json.loads(block)
    except json.JSONDecodeError as e1:
        repaired = _escape_invalid_backslashes(block)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as e2:
            # Log both errors to help debugging
            print(f"❌ First JSON parse error: {e1}")
            print(f"❌ Second JSON parse error after repair: {e2}")
            raise

# --- Main analysis endpoint ---
@app.post("/analyse-work")
async def analyse_work(request: AnalysisRequest):
    image_b64_string = "data:image/jpeg;base64," + request.image_data
    try:
        r = requests.post(
            "https://api.mathpix.com/v3/text",
            headers={
                "app_id": os.getenv("MATHPIX_APP_ID"),
                "app_key": os.getenv("MATHPIX_APP_KEY"),
                "Content-type": "application/json",
            },
            json={"src": image_b64_string, "formats": ["text"]},
        )
        r.raise_for_status()
        transcribed_text = r.json().get("text", "")
        print(f"✅ Mathpix Response: {transcribed_text}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Error calling Mathpix API: {e}")
        return {"status": "error", "message": "Failed to call Mathpix API."}

    # --- Use the imported prompt function ---
    prompt = get_analysis_prompt(
        question_part=request.question_part,
        solution_text=request.solution_text,
        transcribed_text=transcribed_text,
    )

    try:
        generation_config = genai.types.GenerationConfig(response_mime_type="application/json")
        model = genai.GenerativeModel("gemini-2.5-flash", generation_config=generation_config)
        gemini_response = model.generate_content(prompt)

        try:
            analysis_data = _safe_parse_model_json(gemini_response.text)
            if "analysis" not in analysis_data or "reason" not in analysis_data:
                raise ValueError("Missing 'analysis' or 'reason' key in Gemini response.")
        except (json.JSONDecodeError, ValueError) as e:
            print(f"❌ Gemini response was not valid JSON or was missing keys: {e}")
            print(f"Raw Gemini response: {gemini_response.text}")
            return {"status": "error", "message": "AI response was malformed."}

        print(f"✅ Gemini Analysis: {analysis_data}")

        response = {
            "status": "success",
            "result": analysis_data,
            "transcribed_text": transcribed_text,
        }

        print(f"➡️ Sending this JSON to the app: {response}")

        return response

    except Exception as e:
        print(f"❌ Error calling Gemini API: {e}")
        return {"status": "error", "message": f"Failed to call Gemini API: {e}"}

# --- Main help endpoint ---
@app.post("/stuck-at-question")
async def stuck_at_question(request: AnalysisRequest):
    image_b64_string = "data:image/jpeg;base64," + request.image_data
    try:
        r = requests.post(
            "https://api.mathpix.com/v3/text",
            headers={
                "app_id": os.getenv("MATHPIX_APP_ID"),
                "app_key": os.getenv("MATHPIX_APP_KEY"),
                "Content-type": "application/json",
            },
            json={"src": image_b64_string, "formats": ["text"]},
        )
        r.raise_for_status()
        transcribed_text = r.json().get("text", "")
        print(f"✅ Mathpix Response: {transcribed_text}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Error calling Mathpix API: {e}")
        return {"status": "error", "message": "Failed to call Mathpix API."}

    # --- Use the imported prompt function ---
    prompt = get_help_prompt(
        question_part=request.question_part,
        solution_text=request.solution_text,
        transcribed_text=transcribed_text,
    )

    try:
        generation_config = genai.types.GenerationConfig(response_mime_type="application/json")
        model = genai.GenerativeModel("gemini-2.5-flash", generation_config=generation_config)
        gemini_response = model.generate_content(prompt)

        try:
            analysis_data = _safe_parse_model_json(gemini_response.text)
            if "analysis" not in analysis_data or "reason" not in analysis_data:
                raise ValueError("Missing 'analysis' or 'reason' key in Gemini response.")
            # Ensure is_complete exists (default False) for UI logic
            analysis_data["is_complete"] = bool(analysis_data.get("is_complete", False))
        except (json.JSONDecodeError, ValueError) as e:
            print(f"❌ Gemini response was not valid JSON or was missing keys: {e}")
            print(f"Raw Gemini response: {gemini_response.text}")
            return {"status": "error", "message": "AI response was malformed."}

        print(f"✅ Gemini Analysis: {analysis_data}")

        response = {
            "status": "success",
            "result": analysis_data,
            "transcribed_text": transcribed_text,
        }

        print(f"➡️ Sending this JSON to the app: {response}")

        return response

    except Exception as e:
        print(f"❌ Error calling Gemini API: {e}")
        return {"status": "error", "message": f"Failed to call Gemini API: {e}"}

# --- Chat endpoint ---
@app.post("/chat")
async def chat(request: ChatRequest):
    print(f"💬 Received chat request. History has {len(request.conversation_history)} messages.")

    formatted_history = "\n".join(
        [f"{'Student' if msg.is_user else 'Tutor'}: {msg.text}" for msg in request.conversation_history]
    )

    # --- Use the imported prompt function ---
    prompt = get_chat_prompt(
        question_part=request.question_part,
        student_work=request.student_work,
        solution_text=request.solution_text,
        formatted_history=formatted_history,
    )

    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        gemini_response = model.generate_content(prompt)

        ai_reply = gemini_response.text.strip()
        print(f"🤖 AI Reply (raw): {ai_reply}")

        # Safe, regex-free parsing of optional trailing [[STATUS: ...]] tag
        ai_reply, complete = _strip_status_tag(ai_reply)

        print(f"🤖 AI Reply (clean): {ai_reply}")
        print(f"📌 Completion flag: {complete}")

        # (Optional) could add capabilities here later without breaking old apps
        return {"status": "success", "reply": ai_reply, "complete": complete}
    except Exception as e:
        print(f"❌ Error in chat endpoint: {e}")
        return {"status": "error", "message": f"Failed in chat endpoint: {e}"}

# --- Streaming chat endpoint (new, additive) ---
@app.post("/chat-stream")
async def chat_stream(request: ChatRequest):
    """
    Streaming version of /chat. This is ADDITIVE: existing apps can keep using /chat.
    New apps can call /chat-stream to get tokens as they are generated.
    """
    print(f"💬 (stream) Received chat request. History has {len(request.conversation_history)} messages.")

    formatted_history = "\n".join(
        [f"{'Student' if msg.is_user else 'Tutor'}: {msg.text}" for msg in request.conversation_history]
    )

    prompt = get_chat_prompt(
        question_part=request.question_part,
        student_work=request.student_work,
        solution_text=request.solution_text,
        formatted_history=formatted_history,
    )

    async def event_generator():
        try:
            model = genai.GenerativeModel("gemini-2.5-flash")
            # Gemini supports streaming with stream=True
            stream = model.generate_content(prompt, stream=True)
            for chunk in stream:
                if chunk.text:
                    # send each chunk immediately
                    yield chunk.text
                    # tiny pause helps some hosts flush output
                    await asyncio.sleep(0)
        except Exception as e:
            print(f"❌ Error in chat-stream endpoint: {e}")
            # send some marker to the client
            yield "\n[stream-error]\n"

    # plain text streaming; client can rebuild and then strip [[STATUS: ...]] at the end
    return StreamingResponse(event_generator(), media_type="text/plain")

# --- Welcome email endpoint (new, secure + idempotent) ---
@app.post("/welcome-email")
async def welcome_email(authorization: str | None = Header(default=None)):
    """
    Sends the welcome email ONCE per Firebase user.
    Requires: Authorization: Bearer <Firebase ID token>
    """
    user = verify_request_and_get_user(authorization)
    uid = user["uid"]
    email = user.get("email")
    name = user.get("name")

    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User token does not include an email. Cannot send welcome email.",
        )

    db = FirebaseManager().get_db_client()

    # ✅ IMPORTANT: Use the canonical iOS user doc path (`users/{uid}`), NOT legacy `Users/{uid}`
    user_ref = db.collection("users").document(uid)

    snap = user_ref.get()
    if snap.exists:
        data = snap.to_dict() or {}
        if data.get("welcomeEmailSentAt"):
            return {"ok": True, "sent": False, "reason": "already_sent"}

    # Send email
    try:
        send_welcome_email(to_email=email, first_name=(name or None))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send welcome email: {e}")

    # Mark as sent (idempotency)
    user_ref.set(
        {
            "email": email,
            "welcomeEmailSentAt": admin_firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )

    return {"ok": True, "sent": True}

# ---- Mount feature routers (leaderboard & profile) ----
app.include_router(leaderboard_router)
app.include_router(profile_router)