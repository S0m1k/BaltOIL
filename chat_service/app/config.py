from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str
    redis_url: str
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    app_env: str = "development"
    app_port: int = 8004
    allowed_origins: str = "http://localhost:8080"

    # Inter-service: needed to ask auth_service which user IDs are clients
    auth_service_url: str = "http://auth_service:8001/api/v1"
    internal_api_secret: str = "baltoil-internal-secret-2026"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
