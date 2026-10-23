from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    environment: str = "development"
    debug: bool = True

    database_url: str
    db_pool_size: int = 10
    db_max_overflow: int = 5

    clerk_jwks_url: str
    clerk_issuer: str

    arcjet_key: str

    sentry_dsn: str = ""
    posthog_api_key: str = ""
    posthog_host: str = "https://us.i.posthog.com"

    storage_dir: str = "./storage"
    max_upload_size_mb: int = 20
    
    daily_user_token_limit: int = 20_000
    daily_global_token_limit: int = 160_000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()