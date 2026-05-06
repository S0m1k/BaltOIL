from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30

    # App
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8001
    # Comma-separated origins. Production must set this explicitly.
    allowed_origins: str = "http://localhost:8080"

    # Bootstrap admin
    bootstrap_admin_email: str = "admin@baltoil.biz"
    bootstrap_admin_password: str

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
