from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed application settings."""

    app_name: str = "OpenPay AI"
    environment: str = "simulation"
    database_url: str = "sqlite:///./openpay.db"
    log_level: str = "INFO"
    api_version: str = "0.1.0"
    sim_seed: int = 42
    max_attempts: int = 2
    # AI copilot. llm_provider: "auto" picks gemini when a key is set, else ollama; "none" disables.
    llm_provider: str = "auto"
    llm_timeout_s: float = 30.0
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    gemini_url: str = "https://generativelanguage.googleapis.com/v1beta"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "glm-5.3:cloud"

    model_config = SettingsConfigDict(
        env_prefix="OPENPAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

