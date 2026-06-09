from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080
    google_places_api_key: str = ""
    google_places_enabled: bool = False
    cache_ttl_days: int = 30
    cloudflare_r2_access_key_id: str | None = None
    cloudflare_r2_secret_access_key: str | None = None
    cloudflare_r2_account_id: str | None = None
    cloudflare_r2_bucket_name: str | None = None
    cloudflare_r2_public_url: str | None = None
    resend_api_key: str | None = None
    from_email: str = "onboarding@resend.dev"
    anthropic_api_key: str = ""
    pipeline_llm_backend: str = "anthropic"
    pipeline_llm_model: str = "claude-haiku-4-5-20251001"
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = ConfigDict(env_file=".env")


settings = Settings()
