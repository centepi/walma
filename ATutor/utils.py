import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import os

def initialize_firebase():
    """
    Initializes the Firebase Admin SDK using the service account key.
    Returns a Firestore client object if successful, otherwise None.
    """
    # This check prevents initializing the app more than once
    try:
        if not firebase_admin._apps:        
            firebase_project_id = os.getenv('project_id')
            firebase_client_email = os.getenv('client_email')
            firebase_private_key = os.getenv('private_key').replace('\\n', '\n')
            if not all([firebase_project_id, firebase_client_email, firebase_private_key]):
                print("[ERROR] Missing one or more required Firebase environment variables.")
                return None
            
            firebase_private_key = firebase_private_key.replace('\\n', '\n')

            cred = credentials.Certificate({
                "type": "service_account",
                "project_id": firebase_project_id,
                "private_key_id": "<your-private-key-id>",
                "private_key": firebase_private_key,
                "client_email": firebase_client_email,
                "client_id": "<your-client-id>",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": "<your-client-cert-url>"
            })
            firebase_admin.initialize_app(cred)
            print("Firebase: Admin SDK initialized.")
            # Return Firestore client
            client = firestore.client()
            if client:
                print("[INFO] Firestore client initialized successfully.")
                return client
            else:
                print("[ERROR] Firestore client is None.")
                return None
    except Exception as e:
        print("Firebase: init failed — %s", e)
        print("Firebase: check key at '%s'", "./firebase_service_account.json")
        return None