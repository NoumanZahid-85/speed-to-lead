from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@localhost:5432/speed_to_lead"
    log_level: str = "INFO"
    openai_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    slack_webhook_url: Optional[str] = None
    resend_api_key: Optional[str] = None

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

