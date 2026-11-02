"""Договор в Word: полное название ООО, имя файла «номер + название», единый шрифт.

Запуск из папки order_service:  pytest tests/test_contract_docx.py
"""
import io
import os
import sys
import zipfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("INTERNAL_API_SECRET", "test-internal-secret")

from app.services import document_export  # noqa: E402
from app.services.contract_service import (  # noqa: E402
    build_contract_export_ctx, contract_file_name, expand_legal_form,
)

FULL = "Общество с ограниченной ответственностью"


def _contract(buyer_name="ООО «Ромашка»"):
    return SimpleNamespace(
        contract_number="058/2026",
        signed_at=date(2026, 11, 2),
        effective_until=date(2031, 11, 2),
        seller_snapshot={"name": "ООО «СЗТК»", "inn": "7801", "director_name": "Борзяев Дмитрий Геннадьевич"},
        buyer_snapshot={"name": buyer_name, "inn": "7802"},
    )


@pytest.mark.parametrize("raw,expected", [
    ('ООО «Ромашка»', f'{FULL} «Ромашка»'),
    ('ООО "ТК" ВЕРТИКАЛЬ', f'{FULL} "ТК" ВЕРТИКАЛЬ'),
    ('ИП Иванов Иван', 'ИП Иванов Иван'),
    ('ПООО Тест', 'ПООО Тест'),
    (None, ''),
])
def test_expand_legal_form(raw, expected):
    assert expand_legal_form(raw) == expected


def test_file_name_has_number_and_buyer_name():
    assert contract_file_name(_contract(), "docx") == "Договор № 058-2026 ООО Ромашка.docx"


def test_file_name_strips_forbidden_characters():
    name = contract_file_name(_contract('ООО "A/B: <C>"'), "pdf")
    assert not any(ch in name for ch in '/\\:*?"<>|')
    assert name.endswith(".pdf")


def test_file_name_without_buyer_name():
    assert contract_file_name(_contract(""), "docx") == "Договор № 058-2026.docx"


def test_export_ctx_expands_llc_without_touching_snapshot():
    contract = _contract()
    ctx = build_contract_export_ctx(contract)
    assert ctx["buyer"]["name"].startswith(FULL)
    assert ctx["seller"]["name"].startswith(FULL)
    assert contract.buyer_snapshot["name"] == "ООО «Ромашка»"


def test_docx_is_uniform_font_without_heading_styles():
    docx_bytes = document_export.contract_docx(build_contract_export_ctx(_contract()))
    xml = zipfile.ZipFile(io.BytesIO(docx_bytes)).read("word/document.xml").decode()
    assert "Calibri" not in xml and "Heading" not in xml and "ListNumber" not in xml
    assert "ООО" not in xml
    assert FULL in xml


def test_docx_numbers_clauses_per_section():
    from docx import Document
    docx_bytes = document_export.contract_docx(build_contract_export_ctx(_contract()))
    texts = [p.text for p in Document(io.BytesIO(docx_bytes)).paragraphs]
    for prefix in ("1.1. ", "2.1. ", "3.1. ", "6.1. "):
        assert any(t.startswith(prefix) for t in texts), prefix
