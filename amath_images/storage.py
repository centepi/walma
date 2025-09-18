# storage.py
import json
from typing import Optional
from google.cloud import storage
from google.oauth2 import service_account

PNG_PATH = "math/v1/png/{key}.png"
META_PATH = "math/v1/meta/{key}.json"
ONE_YEAR = 31536000

class GCSStore:
    def __init__(self, bucket_name: str, sa_json: Optional[str] = None):
        if sa_json:
            info = json.loads(sa_json)
            creds = service_account.Credentials.from_service_account_info(info)
            self.client = storage.Client(credentials=creds, project=info.get("project_id"))
        else:
            # Falls back to GOOGLE_APPLICATION_CREDENTIALS or default ADC in Railway
            self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)

    # ---------- READ ----------
    def get_png(self, key: str) -> Optional[bytes]:
        blob = self.bucket.blob(PNG_PATH.format(key=key))
        if not blob.exists():
            return None
        return blob.download_as_bytes()  # small assets — OK to buffer

    def get_meta_text(self, key: str) -> Optional[str]:
        blob = self.bucket.blob(META_PATH.format(key=key))
        if not blob.exists():
            return None
        return blob.download_as_text()

    # ---------- WRITE ----------
    def put_png(self, key: str, data: bytes) -> None:
        """Upload PNG with long cache headers."""
        blob = self.bucket.blob(PNG_PATH.format(key=key))
        blob.cache_control = f"public, max-age={ONE_YEAR}, immutable"
        blob.upload_from_string(data, content_type="image/png")
        blob.patch()  # ensure cache_control is persisted

    def put_meta_json(self, key: str, meta: dict) -> None:
        """Upload sidecar meta JSON with long cache headers."""
        text = json.dumps(meta, separators=(",", ":"))
        blob = self.bucket.blob(META_PATH.format(key=key))
        blob.cache_control = f"public, max-age={ONE_YEAR}, immutable"
        blob.upload_from_string(text, content_type="application/json")
        blob.patch()

    def write_probe(self) -> str:
        """Write a tiny object to verify write perms; returns generation id."""
        blob = self.bucket.blob("health/write_probe.txt")
        blob.cache_control = "no-cache"
        blob.upload_from_string("ok", content_type="text/plain")
        blob.patch()
        return str(blob.generation)

CACHE_HEADERS = {
    "Cache-Control": f"public, max-age={ONE_YEAR}, immutable"
}