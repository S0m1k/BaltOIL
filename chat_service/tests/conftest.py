"""Тестовое окружение chat_service.

Тесты прав на управление участниками групп (CRM-47) не требуют живой БД:
проверяются чистые функции доступа и загрузчик диалога с подставным
AsyncSession-стабом. Настройки читаются на import-time (app.config), поэтому
env выставляем ДО импортов из app.*:

    cd chat_service && python -m pytest
"""
import os
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://testuser:testpass@localhost:55432/chattest")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6399")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("INTERNAL_API_SECRET", "test-internal-secret")
os.environ.setdefault("APP_ENV", "test")

if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))
