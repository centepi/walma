# ATutor/utils.py
# Unified Firebase initialization. Prefer FirebaseManager(); initialize_firebase() is kept
# as a compatibility shim that delegates to the manager.

import os
import logging
import threading
from typing import Optional

import firebase_admin
from firebase_admin import credentials, firestore


class FirebaseManager:
    _instance: Optional["FirebaseManager"] = None
    _lock = threading.Lock()
    _db_client: Optional[firestore.Client] = None  # type: ignore
    _app: Optional[firebase_admin.App] = None

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def initialize(self) -> None:
        """Initialize Firebase Admin exactly once per process."""
        if self._app is not None and self._db_client is not None:
            return

        with self._lock:
            if self._app is not None and self._db_client is not None:
                return

            # If another part of the app already initialized firebase_admin, reuse it.
            try:
                existing_app = firebase_admin.get_app()
                self._app = existing_app
                self._db_client = firestore.client()
                logging.info("FirebaseManager: reusing existing firebase_admin app.")
                return
            except ValueError:
                # No existing app; proceed to initialize from env.
                pass

            project_id = os.getenv("project_id")
            client_email = os.getenv("client_email")
            private_key = os.getenv("private_key")

            if not project_id or not client_email or not private_key:
                msg = "[ERROR] Missing Firebase service account env vars: project_id/client_email/private_key"
                logging.error(msg)
                raise RuntimeError(msg)

            # Handle \n-escaped private keys commonly used in env vars
            private_key = private_key.replace("\\n", "\n")

            cred_dict = {
                "type": "service_account",
                "project_id": project_id,
                # The following fields are included to match the typical service account structure.
                # If you have real values, you can set them as env vars too; otherwise placeholders are fine.
                "private_key_id": os.getenv("private_key_id", "<private-key-id>"),
                "private_key": private_key,
                "client_email": client_email,
                "client_id": os.getenv("client_id", "<client-id>"),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": os.getenv("client_x509_cert_url", "<client-cert-url>"),
            }

            try:
                cred = credentials.Certificate(cred_dict)
                self._app = firebase_admin.initialize_app(cred)
                self._db_client = firestore.client()
                logging.info("FirebaseManager: initialized firebase_admin and Firestore client.")
            except Exception as e:
                logging.error(f"FirebaseManager: initialization failed: {e}")
                raise

    def get_db_client(self):
        """Get the singleton Firestore client, initializing if needed."""
        if self._db_client is None:
            self.initialize()
        return self._db_client


# ---- Deprecated helper (compatibility) ---------------------------------------
def initialize_firebase():
    """
    DEPRECATED: Use FirebaseManager().get_db_client() instead.
    Kept for backward compatibility; now delegates to FirebaseManager.
    """
    logging.warning("initialize_firebase() is deprecated. Using FirebaseManager instead.")
    return FirebaseManager().get_db_client()
