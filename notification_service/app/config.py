from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str
    redis_url: str
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    internal_api_secret: str = "internal-shared-secret-change-me"
    auth_service_url: str = "http://auth_service:8001/api/v1"
    allowed_origins: str = "http://localhost:8080"
    app_env: str = "development"
    app_port: int = 8005

    # SMTP / email
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "noreply@baltoil.ru"
    smtp_use_tls: bool = True
    email_enabled: bool = False  # глобальный kill-switch

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
