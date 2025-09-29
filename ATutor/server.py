# ATutor/server.py
import os
import json
import re
import requests
import google.generativeai as genai
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
from dotenv import load_dotenv

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

# --- Helpers: robust JSON parsing for model output ---

def _strip_code_fences(s: str) -> str:
    """Remove ```json ... ``` code fences if present."""
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()

def _extract_json_object(s: str) -> str:
    """
    If the model wrapped the JSON with extra prose, pull out the first {...} block.
    """
    m = re.search(r"\{.*\}", s, flags=re.DOTALL)
    return m.group(0).strip() if m else s

def _escape_illegal_backslashes(s: str) -> str:
    """
    In JSON strings, backslashes must either escape one of [\"\\/bfnrtu] or be doubled.
    This turns occurrences like \frac, \ln, \sqrt into \\frac, \\ln, \\sqrt, etc.
    """
    return re.sub(r'\\(?![\\/"bfnrtu])', r'\\\\', s)

def _parse_model_json(raw_text: str) -> dict:
    """
    Best-effort JSON parse:
      1) strip code fences
      2) try loads
      3) extract {...} region and retry
      4) escape illegal backslashes and retry
    Raises JSONDecodeError if all fail.
    """
    if not raw_text or not raw_text.strip():
        raise json.JSONDecodeError("empty response", raw_text or "", 0)

    s = _strip_code_fences(raw_text)

    # First pass
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    # Try extracting the object region
    s2 = _extract_json_object(s)
    try:
        return json.loads(s2)
    except json.JSONDecodeError:
        pass

    # Last resort: escape illegal backslashes
    s3 = _escape_illegal_backslashes(s2)
    return json.loads(s3)

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

        raw = (gemini_response.text or "").strip()
        try:
            analysis_data = _parse_model_json(raw)
        except json.JSONDecodeError as e:
            print(f"❌ Gemini response was not valid JSON after repairs: {e}")
            print(f"Raw Gemini response: {raw}")
            return {"status": "error", "message": "AI response was malformed."}

        if "analysis" not in analysis_data or "reason" not in analysis_data:
            print(f"❌ Gemini JSON missing required keys. JSON: {analysis_data}")
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

        raw = (gemini_response.text or "").strip()
        try:
            analysis_data = _parse_model_json(raw)
        except json.JSONDecodeError as e:
            print(f"❌ Gemini response was not valid JSON after repairs: {e}")
            print(f"Raw Gemini response: {raw}")
            return {"status": "error", "message": "AI response was malformed."}

        if "analysis" not in analysis_data or "reason" not in analysis_data:
            print(f"❌ Gemini JSON missing required keys. JSON: {analysis_data}")
            return {"status": "error", "message": "AI response was malformed."}

        # Ensure is_complete exists (default False) for UI logic
        analysis_data["is_complete"] = bool(analysis_data.get("is_complete", False))

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

        ai_reply = (gemini_response.text or "").strip()
        print(f"🤖 AI Reply (raw): {ai_reply}")

        # Parse completion tag at the very end of the reply
        complete = False
        m = re.search(r"$begin:math:display$\\[STATUS:\\s*(COMPLETE|INCOMPLETE)\\s*$end:math:display$\]\s*$", ai_reply, re.IGNORECASE)
        if m:
            complete = m.group(1).upper() == "COMPLETE"
            # Strip the status tag from the reply shown to the user
            ai_reply = re.sub(
                r"\s*$begin:math:display$\\[STATUS:\\s*(?:COMPLETE|INCOMPLETE)\\s*$end:math:display$\]\s*$", "", ai_reply, flags=re.IGNORECASE
            ).strip()

        print(f"🤖 AI Reply (clean): {ai_reply}")
        print(f"📌 Completion flag: {complete}")

        return {"status": "success", "reply": ai_reply, "complete": complete}
    except Exception as e:
        print(f"❌ Error in chat endpoint: {e}")
        return {"status": "error", "message": f"Failed in chat endpoint: {e}"}

# ---- Mount feature routers (leaderboard & profile) ----
app.include_router(leaderboard_router)
app.include_router(profile_router)