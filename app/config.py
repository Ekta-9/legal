from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    groq_concurrency: int = 4
    groq_batch_size: int = 6
    # Hindi/Marathi translation: "groq" (the model above) or "local" (NLLB on this machine, needs
    # requirements-translation.txt and ~3 GB of RAM); TRANSLATION_ENABLED=false switches it off
    translation_backend: str = "groq"
    translation_enabled: bool = True


settings = Settings()
