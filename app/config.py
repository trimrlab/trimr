from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False

    # ── Database Configuration ────────────────────────
    DATABASE_URL: str = "sqlite:///./trimr.db"

    # ── Cloud API ─────────────────────────────────────
    CLOUD_API_URL: str = ""
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "allow"

settings = Settings()