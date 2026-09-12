from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str
    redis_url: str = "redis://redis:6379"  # для серверной ревокации токенов
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    app_env: str = "development"
    app_port: int = 8003
    allowed_origins: str = "http://localhost:8080"
    notification_service_url: str = "http://notification_service:8005"
    order_service_url: str = "http://order_service:8002"
    auth_service_url: str = "http://auth_service:8001"
    # Required (no default): refuse to boot without an explicit inter-service secret.
    internal_api_secret: str
    public_delivery_url: str = "http://localhost:8003"
    dadata_api_key: str | None = None

    # ── GPS-мониторинг (спринт 2026-09-12) ────────────────────────────────
    # Приём точек от самодельных трекеров. Канал открытый (модем без TLS),
    # поэтому защита — регистрация устройства, антифлуд и отсев мусора.
    gps_enabled: bool = True
    # Неизвестный номер устройства заводится сам при первой точке, чтобы не
    # терять данные только что собранного трекера. Админ потом привязывает
    # его к машине. Выключить, когда все трекеры заведены.
    gps_auto_register: bool = True
    gps_max_auto_devices: int = 50
    # Не чаще одной точки в N секунд с устройства.
    gps_min_interval_sec: float = 3.0
    # Глубина истории: хранить месяц, чистить раз в сутки.
    gps_retention_days: int = 31
    # На карте: до N минут — «на связи», до M — «давно не выходил».
    gps_online_minutes: int = 10
    gps_stale_minutes: int = 60
    # Потолок точек в ответе трека — дальше равномерное прореживание.
    gps_max_track_points: int = 5000

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
