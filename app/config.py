from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    groq_concurrency: int = 4
    groq_batch_size: int = 6


settings = Settings()
