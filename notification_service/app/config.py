from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str
    redis_url: str
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    # Required (no default): refuse to boot without an explicit inter-service secret.
    internal_api_secret: str
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
    smtp_use_tls: bool = True       # implicit TLS (port 465)
    smtp_use_starttls: bool = False  # STARTTLS (port 587). Взаимоисключимо с smtp_use_tls.
    smtp_force_ipv6: bool = False    # форс AF_INET6, нужно когда провайдер режет egress IPv4 (RU VPS + Yandex SMTP)
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
