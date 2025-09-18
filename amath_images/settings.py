# settings.py
from typing import Optional, Set
from pydantic import Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Required
    MATH_IMG_BUCKET: str = Field(..., env="MATH_IMG_BUCKET")

    # Tuning
    RENDER_SALT: str = Field("v5", env="RENDER_SALT")
    MAX_LATEX_BYTES: int = Field(16384, env="MAX_LATEX_BYTES")
    MAX_WIDTH_PT: float = Field(860, env="MAX_WIDTH_PT")
    RENDER_TIMEOUT_MS: int = Field(3000, env="RENDER_TIMEOUT_MS")

    # Auth / creds
    GCP_SERVICE_ACCOUNT_JSON: Optional[str] = Field(None, env="GCP_SERVICE_ACCOUNT_JSON")
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = Field(None, env="GOOGLE_APPLICATION_CREDENTIALS")

    # Allowed scales
    ALLOWED_SCALES: Set[int] = {2, 3}

    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
    }

settings = Settings()