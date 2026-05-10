from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    app_env: str = "development"
    app_port: int = 8003
    allowed_origins: str = "http://localhost:8080"
    notification_service_url: str = "http://notification_service:8005"
    internal_api_secret: str = "baltoil-internal-secret-2026"
    public_delivery_url: str = "http://localhost:8003"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
