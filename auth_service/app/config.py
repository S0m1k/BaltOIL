from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    # Redis (for login throttle and rate-limit storage)
    redis_url: str = "redis://redis:6379"

    # App
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8001
    # Comma-separated origins. Production must set this explicitly.
    allowed_origins: str = "http://localhost:8080"

    # Bootstrap admin
    bootstrap_admin_email: str = "admin@baltoil.biz"
    bootstrap_admin_password: str

    # Inter-service
    internal_api_secret: str = "baltoil-internal-secret-2026"

    # DaData (INN lookup). Optional — if not set, lookup endpoint returns found=False.
    dadata_api_key: str | None = None

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
