from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_MODE: str = "demo"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_DATA_DIR: str = "runtime"

    MAX_UPLOAD_BYTES: int = 26214400

    MODEL_BASE_URL: str = ""
    MODEL_API_KEY: str = ""
    MODEL_NAME: str = ""
    MODEL_API_STYLE: str = "auto"  # "auto" | "openai" | "anthropic"

    CORS_ORIGINS: str = "http://localhost:5173"


@lru_cache()
def get_settings() -> Settings:
    return Settings()