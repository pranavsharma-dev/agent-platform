from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@localhost:5432/agent_platform"
    redis_url: str = "redis://localhost:6379/0"
    openai_api_key: str = ""
    model_name: str = "gpt-4o-mini"
    max_orchestrator_steps: int = 10

    model_config = {"env_file": ".env"}


settings = Settings()
