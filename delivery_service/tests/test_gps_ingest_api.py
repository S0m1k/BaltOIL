"""Ручка приёма точек: что бы ни прислал трекер, ответ короткий и понятный.

БД здесь не нужна — сохранение подменяется заглушкой, проверяется именно
HTTP-контракт: метод, тип тела, ответ OK/ERR и то, что до сохранения доходит
правильно разобранная точка.

Запуск из папки delivery_service:  pytest tests/test_gps_ingest_api.py
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Настройки читаются на импорте приложения — подставляем безопасные заглушки.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
os.environ.setdefault("JWT_SECRET_KEY", "x" * 48)
os.environ.setdefault("INTERNAL_API_SECRET", "test-internal-secret")

from fastapi.testclient import TestClient  # noqa: E402

from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import gps as gps_router  # noqa: E402
from app.services import gps_protocol as proto  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    saved: list = []
    seen: list = []

    async def fake_ingest(db, point, *, source):
        saved.append(point)
        return point

    async def fake_mark_seen(db, device_number):
        seen.append(device_number)

    async def fake_db():
        yield None

    monkeypatch.setattr(gps_router.gps_service, "ingest_point", fake_ingest)
    monkeypatch.setattr(gps_router.gps_service, "mark_seen", fake_mark_seen)
    app.dependency_overrides[get_db] = fake_db
    # Без контекстного менеджера: он поднял бы lifespan, а тот лезет в БД
    # (create_all и фоновые задачи), которая юнит-тесту не нужна.
    c = TestClient(app)
    c.saved = saved
    c.seen = seen
    yield c
    app.dependency_overrides.clear()


def test_plain_text_body_is_accepted(client):
    r = client.post("/api/v1/gps/ingest", content="SZTK-01 59.938732 30.312345 9")
    assert r.status_code == 200
    assert r.text.strip() == "OK"
    point = client.saved[0]
    assert point.device == "SZTK-01" and point.sats == 9
    assert str(point.lat) == "59.938732" and str(point.lon) == "30.312345"


def test_json_body_is_accepted(client):
    r = client.post("/api/v1/gps/ingest", json={"id": "SZTK-02", "lat": 59.9, "lon": 30.3, "sats": 7})
    assert r.text.strip() == "OK"
    assert client.saved[0].device == "SZTK-02"


def test_form_body_is_accepted(client):
    r = client.post("/api/v1/gps/ingest", data={"node": "SZTK-03", "lat": "59.9", "lon": "30.3", "sats": "6"})
    assert r.text.strip() == "OK"
    assert client.saved[0].device == "SZTK-03"


def test_get_with_query_params_is_accepted(client):
    # Часть модемов умеет только GET с параметрами в адресе.
    r = client.get("/api/v1/gps/ingest", params={"id": "SZTK-04", "lat": "59.9", "lon": "30.3", "sats": "8"})
    assert r.text.strip() == "OK"
    assert client.saved[0].device == "SZTK-04"


def test_garbage_gets_short_error_and_is_not_saved(client):
    r = client.post("/api/v1/gps/ingest", content="привет сервер")
    # 200, а не 4xx: трекер на ошибку ничего умного не сделает, а ретраи
    # по кругу сожгут трафик SIM-карты.
    assert r.status_code == 200
    assert r.text.strip() == f"ERR:{proto.ERR_BADFMT}"
    assert client.saved == []


def test_no_fix_marks_device_alive_without_saving_point(client):
    r = client.post("/api/v1/gps/ingest", content="SZTK-05 0.000000 0.000000 0")
    assert r.text.strip() == f"ERR:{proto.ERR_NOFIX}"
    assert client.saved == []
    assert client.seen == ["SZTK-05"]   # «трекер жив, спутников не видит»


def test_empty_request_is_rejected(client):
    r = client.post("/api/v1/gps/ingest", content="")
    assert r.text.strip() == f"ERR:{proto.ERR_BADFMT}"


def test_ingest_needs_no_authorization(client):
    # Ключевое свойство ручки: модем не умеет ни JWT, ни TLS.
    r = client.post("/api/v1/gps/ingest", content="SZTK-06 59.9 30.3 9")
    assert r.status_code == 200 and r.text.strip() == "OK"


def test_admin_endpoints_are_closed_without_token(client):
    for path in ("/api/v1/gps/devices", "/api/v1/gps/live", "/api/v1/gps/raw"):
        assert client.get(path).status_code == 401, path


# ── Защита открытого в интернет приёмника ────────────────────────────────────

def test_oversized_body_is_cut_off_before_it_is_read(client):
    # Порт открыт наружу: тело обязано резаться до того, как попадёт в память.
    r = client.post("/api/v1/gps/ingest", content="A" * 9000)
    assert r.status_code == 413
    assert client.saved == []


def test_disabled_ingest_answers_without_touching_db(client, monkeypatch):
    monkeypatch.setattr(gps_router.settings, "gps_enabled", False)
    r = client.post("/api/v1/gps/ingest", content="SZTK-09 59.9 30.3 9")
    assert r.text.strip() == f"ERR:{proto.ERR_INACTIVE}"
    assert client.saved == []


def test_no_fix_flood_hits_the_rate_limiter(client):
    # Ветка «нет фикса» не сохраняет точку, но ходит в БД — без антифлуда её
    # можно было бы долбить бесконечно.
    for _ in range(5):
        client.post("/api/v1/gps/ingest", content="FLOOD-01 0.000000 0.000000 0")
    assert client.seen == ["FLOOD-01"]


def test_client_ip_is_taken_from_the_end_of_forwarded_chain(client):
    # nginx дописывает реальный адрес в конец, левую часть подделывает клиент.
    from app.routers.gps import _client_ip

    class _Req:
        headers = {"x-forwarded-for": "1.2.3.4, 10.0.0.9"}
        client = None

    assert _client_ip(_Req()) == "10.0.0.9"


@pytest.mark.parametrize("payload,hidden", [
    ("token=deadbeefdeadbeef12", "deadbeefdeadbeef12"),
    ("BO1,SZTK-01,0123456789abcdef0123456789abcdef,59.9,30.3,9", "0123456789abcdef0123456789abcdef"),
])
def test_raw_log_does_not_keep_token_values(payload, hidden):
    from app.services.gps_service import mask_secrets

    assert hidden not in mask_secrets(payload)
