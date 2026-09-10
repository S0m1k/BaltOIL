"""Тесты без БД: живой PostgreSQL не нужен, поэтому autouse-миграции из
tests/conftest.py здесь не подключаются (отдельный пакет — отдельный conftest).
"""
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))
