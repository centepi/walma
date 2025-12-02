import os
import google.generativeai as genai
from dotenv import load_dotenv

# Load your .env file
load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    print("❌ Error: GOOGLE_API_KEY not found in .env")
else:
    print(f"✅ Key found: {api_key[:5]}...*****")
    genai.configure(api_key=api_key)
    
    print("\nAttempting to list available models...")
    try:
        found_flash = False
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(f" - {m.name}")
                if "flash" in m.name:
                    found_flash = True
        
        print("\n--- RESULT ---")
        if found_flash:
            print("✅ SUCCESS: Your API Key CAN see Gemini Flash.")
        else:
            print("❌ FAILURE: Gemini Flash is NOT in the list. Check Google Cloud Console.")
            
    except Exception as e:
        print(f"❌ ERROR: Key failed completely. Reason: {e}")