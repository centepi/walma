# server.py
import os
import json
import requests
import google.generativeai as genai
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict
from dotenv import load_dotenv

# --- Import the prompt functions from the new file ---
from prompts import get_analysis_prompt, get_chat_prompt, get_help_prompt

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

# --- Main analysis endpoint ---
@app.post("/analyse-work")
async def analyse_work(request: AnalysisRequest):
    image_b64_string = "data:image/jpeg;base64," + request.image_data
    try:
        r = requests.post("https://api.mathpix.com/v3/text", headers={ "app_id": os.getenv("MATHPIX_APP_ID"), "app_key": os.getenv("MATHPIX_APP_KEY"), "Content-type": "application/json" }, json={"src": image_b64_string, "formats": ["text"]})
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
        transcribed_text=transcribed_text
    )
    
    try:
        generation_config = genai.types.GenerationConfig(response_mime_type="application/json")
        model = genai.GenerativeModel('gemini-2.5-flash', generation_config=generation_config)
        gemini_response = model.generate_content(prompt)
        
        try:
            analysis_data = json.loads(gemini_response.text)
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
            "transcribed_text": transcribed_text
        }
        
        print(f"➡️ Sending this JSON to the app: {response}")
        
        return response

    except Exception as e:
        print(f"❌ Error calling Gemini API: {e}")
        return {"status": "error", "message": f"Failed to call Gemini API: {e}"}
    
# --- Main help endpoint ---
@app.post("/stuck-at-question")
async def analyse_work(request: AnalysisRequest):
    image_b64_string = "data:image/jpeg;base64," + request.image_data
    try:
        r = requests.post("https://api.mathpix.com/v3/text", headers={ "app_id": os.getenv("MATHPIX_APP_ID"), "app_key": os.getenv("MATHPIX_APP_KEY"), "Content-type": "application/json" }, json={"src": image_b64_string, "formats": ["text"]})
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
        transcribed_text=transcribed_text
    )
    
    try:
        generation_config = genai.types.GenerationConfig(response_mime_type="application/json")
        model = genai.GenerativeModel('gemini-2.5-flash', generation_config=generation_config)
        gemini_response = model.generate_content(prompt)
        
        try:
            analysis_data = json.loads(gemini_response.text)
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
            "transcribed_text": transcribed_text
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

    formatted_history = "\n".join([f"{'Student' if msg.is_user else 'Tutor'}: {msg.text}" for msg in request.conversation_history])

    # --- Use the imported prompt function ---
    prompt = get_chat_prompt(
        question_part=request.question_part,
        student_work=request.student_work,
        solution_text=request.solution_text,
        formatted_history=formatted_history
    )

    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        gemini_response = model.generate_content(prompt)
        
        ai_reply = gemini_response.text.strip()
        print(f"🤖 AI Reply: {ai_reply}")

        return {"status": "success", "reply": ai_reply}
    except Exception as e:
        print(f"❌ Error in chat endpoint: {e}")
        return {"status": "error", "message": f"Failed in chat endpoint: {e}"}
