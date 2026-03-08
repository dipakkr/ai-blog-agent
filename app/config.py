from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # SERP
    serpapi_key: str = ""

    # Database
    database_url: str = "sqlite:///./jobs.db"
    langgraph_db_path: str = "./checkpoints.db"

    # Model selection
    primary_llm: str = "claude-sonnet-4-6"
    fallback_llm: str = "gpt-4o-mini"

    # Redis / job queue
    redis_url: str = "redis://localhost:6379/0"

    # Pipeline
    seo_score_threshold: float = 75.0
    max_revision_count: int = 3

    # Logging
    log_level: str = "INFO"


settings = Settings()
