"""Имя скачиваемого файла счёта: «<номер> <организация>.pdf» (CRM-28).

Кириллица в HTTP-заголовке живёт только через RFC 5987 — проверяем, что
Content-Disposition несёт настоящее имя в filename* и безопасный ascii-фолбэк
в filename.

Запуск из папки order_service:  pytest tests/test_document_filename.py
"""
import sys
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.media import content_disposition_attachment  # noqa: E402
from app.services.document_service import document_display_name  # noqa: E402
from app.models.document import DocumentType  # noqa: E402


def _filename_star(header: str) -> str:
    marker = "filename*=UTF-8''"
    return unquote(header.split(marker, 1)[1])


def test_invoice_display_name_is_number_and_org():
    name = document_display_name(
        DocumentType.INVOICE, "0189", {"name": 'ООО "НВК"'}
    )
    assert name == "189 НВК"


def test_invoice_filename_header_carries_cyrillic():
    name = document_display_name(
        DocumentType.INVOICE, "0189", {"name": 'ООО "НВК"'}
    )
    header = content_disposition_attachment(f"{name}.pdf")
    assert _filename_star(header) == "189 НВК.pdf"
    # Заголовки передаются в latin-1: сборка не должна падать на кириллице.
    header.encode("latin-1")
    # Ascii-фолбэк остаётся валидным именем файла (без кавычек и не-ascii).
    assert 'filename="189 ___.pdf"' in header


def test_manual_display_name_wins():
    name = document_display_name(
        DocumentType.INVOICE, "0189", {"name": 'ООО "НВК"'}, override="Счёт для НВК"
    )
    assert name == "Счёт для НВК"


def test_non_invoice_document_keeps_number():
    name = document_display_name(DocumentType.TTN, "ТТН-2026-Ю12", {"name": 'ООО "НВК"'})
    assert name == "ТТН-2026-Ю12"
