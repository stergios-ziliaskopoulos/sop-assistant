from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "SOP Assistant"
    API_V1_STR: str = "/api/v1"
    
    # Google Gemini
    GEMINI_API_KEY: str
    
    # Groq
    GROQ_API_KEY: str
    
    # Supabase
    SUPABASE_URL: str
    SUPABASE_KEY: str
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Resend (for handoff notifications)
    RESEND_API_KEY: str | None = None

    # Slack
    SLACK_WEBHOOK_URL: str | None = None

    # Admin
    ADMIN_KEY: str = "changeme"

    # Ragas/Evaluation (optional)
    RAGAS_API_KEY: str | None = None
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=True)

settings = Settings()
