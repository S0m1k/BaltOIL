"""Название топлива в документах: прежние коды — как раньше, новые — из каталога."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("INTERNAL_API_SECRET", "test-internal-secret")

from app.services import fuel_type_service as fts  # noqa: E402

LEGACY = {"diesel_summer": "Дизельное топливо летнее (ДТ-Л-К5)"}


def test_legacy_code_keeps_old_name(monkeypatch):
    monkeypatch.setattr(fts, "_catalog_labels", {"diesel_summer": "Переименовано"})
    assert fts.document_name("diesel_summer", LEGACY) == "Дизельное топливо летнее (ДТ-Л-К5)"


def test_new_diesel_code_uses_catalog_label(monkeypatch):
    monkeypatch.setattr(fts, "_catalog_labels", {"dt_e_x": "ДТ-Е-К5, сорт Е"})
    assert fts.document_name("dt_e_x", LEGACY) == "Дизельное топливо (ДТ-Е-К5, сорт Е)"


def test_new_non_diesel_code_uses_label_as_is(monkeypatch):
    monkeypatch.setattr(fts, "_catalog_labels", {"ai_98": "Бензин АИ-98"})
    assert fts.document_name("ai_98", LEGACY) == "Бензин АИ-98"


def test_unknown_code_falls_back_to_code(monkeypatch):
    monkeypatch.setattr(fts, "_catalog_labels", {})
    assert fts.document_name("mystery", LEGACY) == "mystery"
