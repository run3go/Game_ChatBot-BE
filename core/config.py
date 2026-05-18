from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    OPENROUTER_API_KEY: str
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    RIOT_API_KEY: str = ""
    
    MODEL_ANALYZE: str = "openai/gpt-4o-mini"
    MODEL_ANSWER: str = "openai/gpt-4o-mini"
    MODEL_SQL: str = "openai/gpt-4o-mini"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()