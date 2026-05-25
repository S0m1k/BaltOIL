from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str
    redis_url: str
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    app_env: str = "development"
    app_port: int = 8006
    allowed_origins: str = "http://localhost:8080"

    # LiveKit
    livekit_url: str = "ws://livekit:7880"              # internal Docker network URL
    livekit_public_url: str = "ws://localhost:7880"     # URL the browser will connect to
    livekit_api_key: str
    livekit_api_secret: str

    # Inter-service
    chat_service_url: str = "http://chat_service:8004"
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
