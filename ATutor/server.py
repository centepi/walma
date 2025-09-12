# server.py
import os
import json
import re
import requests
import google.generativeai as genai
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict
from dotenv import load_dotenv
from utils import initialize_firebase
import datetime
from firebase_admin import credentials, firestore,auth
from leaderboard import tiered_leaderboard_desc,get_friend_leaderboard_desc
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

class AddNewUserRequest(BaseModel):
    user_id: str
    username: str
class AddFriendRequest(BaseModel):
    user_id: str
    friend_username: str
class TieredLeaderboardRequest(BaseModel):
    user_id: str
class FriendLeaderboardRequest(BaseModel):
    user_id: str
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
async def stuck_at_question(request: AnalysisRequest):
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
        model = genai.GenerativeModel('gemini-2.5-flash')
        gemini_response = model.generate_content(prompt)

        ai_reply = gemini_response.text.strip()
        print(f"🤖 AI Reply (raw): {ai_reply}")

        # Parse completion tag at the very end of the reply
        complete = False
        m = re.search(r"\[\[STATUS:\s*(COMPLETE|INCOMPLETE)\s*\]\]\s*$", ai_reply, re.IGNORECASE)
        if m:
            complete = (m.group(1).upper() == "COMPLETE")
            # Strip the status tag from the reply shown to the user
            ai_reply = re.sub(r"\s*\[\[STATUS:\s*(?:COMPLETE|INCOMPLETE)\s*\]\]\s*$", "", ai_reply, flags=re.IGNORECASE).strip()

        print(f"🤖 AI Reply (clean): {ai_reply}")
        print(f"📌 Completion flag: {complete}")

        return {"status": "success", "reply": ai_reply, "complete": complete}
    except Exception as e:
        print(f"❌ Error in chat endpoint: {e}")
        return {"status": "error", "message": f"Failed in chat endpoint: {e}"}
TIERS = [
    {"id": 0, "name": "Copper"},
    {"id": 1, "name": "Bronze"}, 
    {"id": 2, "name": "Silver"},
    {"id": 3, "name": "Gold"},
    {"id": 4, "name": "Platinum"},
    {"id": 5, "name": "Diamond"},
    {"id": 6, "name": "Legendary"}
]

GROUP_SIZE = 20

@app.post("/add-new-user")
async def add_new_user(request:AddNewUserRequest):
    db_client = initialize_firebase()
    """Assign new user to Copper tier and allocate to appropriate group"""
    
    # Find current Copper groups and their sizes
    copper_users = db_client.collection('users').where('tierID', '==', 0).get()
    
    # Group users by groupID
    groups = {}
    for user in copper_users:
        user_data = user.to_dict()
        group_id = user_data.get('groupID', 0)
        if group_id not in groups:
            groups[group_id] = []
        groups[group_id].append(user_data)
    
    # Find a group with less than GROUP_SIZE members or create new one
    target_group_id = 0
    for group_id, members in groups.items():
        if len(members) < GROUP_SIZE:
            target_group_id = group_id
            break
    else:
        # All groups are full, create new group
        target_group_id = len(groups)
    
    # Add user to database
    user_data = {
        'userID': request.user_id,
        'username': request.username,
        'tierID': 0,  # Copper tier ID
        'groupID': target_group_id,
        'totalXP': 0,
        'currentStreak': 0,
        'timeSpentInSeconds': 0,
        'lastLoginDate': datetime.now(),
        'friends': []
    }
    try:
        db_client.collection('users').document(request.user_id).set(user_data)
        return {"status":"ok"}
    except Exception as e:
        return {"status":"nok","reason":e}


@app.post("/add-friend")
async def add_friend(request:AddFriendRequest):
    """Add a friend by username"""
    db_client = initialize_firebase()
    # Find friend by username
    friend_query = db_client.collection('users').where('username', '==', request.friend_username).limit(1).get()
    
    if not friend_query:
        return False, "User not found"
    
    friend_doc = friend_query[0]
    friend_id = friend_doc.to_dict()['userID']
    
    # Update current user's friends list
    user_ref = db_client.collection('users').document(request.user_id)
    user_ref.update({
        'friends': firestore.ArrayUnion([friend_id])
    })
    
    # Update friend's friends list (mutual)
    friend_ref = db_client.collection('users').document(friend_id)
    friend_ref.update({
        'friends': firestore.ArrayUnion([request.user_id])
    })
    
    return True, "Friend added successfully"




    
@app.post("/tiered-leaderboard")
async def tiered_leaderboard(request:TieredLeaderboardRequest):
    """Get leaderboard for user's current tier and group"""    
    leaderboard = tiered_leaderboard_desc(request,TIERS,GROUP_SIZE)
    
    return leaderboard


@app.post("/get-friend-leaderboard")
async def get_friend_leaderboard(request:FriendLeaderboardRequest):
    """Get leaderboard showing points among friends"""
    
    leaderboard = get_friend_leaderboard_desc(request,TIERS,GROUP_SIZE)
    
    return leaderboard


def delete_user_account(uid):
    auth.delete_user(uid)
    print(f"Deleted user account: {uid}")




def delete_user_data(uid):
    # Delete from /users/{uid}
    db_client = initialize_firebase()
    user_doc_ref = db_client.collection('users').document(uid)
    user_doc_ref.delete()

    # Delete subcollections (e.g., /userPosts/{uid}/posts)
    user_posts_ref = db_client.collection('userPosts').document(uid).collection('posts')
    docs = user_posts_ref.stream()
    for doc in docs:
        doc.reference.delete()

    # Optionally, delete the userPosts/{uid} document if it exists
    db_client.collection('userPosts').document(uid).delete()

    print(f"Deleted Firestore data for user {uid}")

@app.post("/delete-user-data")
async def delete_user_data(request):
    delete_user_data(request.uid)
    delete_user_account(request.uid)