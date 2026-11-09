"""Сквозная проверка маршрутов организации через ASGI (CRM-62, CRM-63).

В отличие от сервисных тестов идёт через настоящие эндпоинты: multipart-загрузка,
заголовки скачивания, права по роли и скрытие заметки сотрудников от клиента.

Требуется живой PostgreSQL — см. tests/conftest.py.
"""
import httpx
import pytest
from fastapi import FastAPI

from app.core.security import create_access_token, hash_password
from app.models.client_profile import ClientProfile, ClientType
from app.models.organization import MemberRole, MemberStatus, Organization, OrganizationMember
from app.models.user import User, UserRole

PDF = b"%PDF-1.4\n" + b"x" * 200


def _build_app() -> FastAPI:
    """Только роутер организаций: app.main тянет лишние зависимости (slowapi, lifespan)."""
    from app.routers import organizations

    app = FastAPI()
    app.include_router(organizations.router, prefix="/api/v1")
    return app


app = _build_app()


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    """Отзыв токенов и троттлинг живут в Redis; в тестах его нет."""
    from app.core import token_revocation

    async def _false(*a, **kw):
        return False

    for name in ("is_user_revoked", "is_revoked", "is_token_revoked"):
        if hasattr(token_revocation, name):
            monkeypatch.setattr(token_revocation, name, _false)


async def _seed(db):
    manager = User(email=None, phone="+79990000001", hashed_password=hash_password("Password123"),
                   full_name="Менеджер", role=UserRole.MANAGER)
    client = User(email=None, phone="+79990000002", hashed_password=hash_password("Password123"),
                  full_name="Клиент", role=UserRole.CLIENT)
    outsider = User(email=None, phone="+79990000003", hashed_password=hash_password("Password123"),
                    full_name="Чужой", role=UserRole.CLIENT)
    org = Organization(company_name="ООО «Ветро»", inn="7801234567")
    db.add_all([manager, client, outsider, org])
    await db.flush()
    db.add_all([
        ClientProfile(user_id=client.id, client_type=ClientType.INDIVIDUAL),
        ClientProfile(user_id=outsider.id, client_type=ClientType.INDIVIDUAL),
        OrganizationMember(organization_id=org.id, user_id=client.id,
                           member_role=MemberRole.OWNER, status=MemberStatus.ACTIVE),
    ])
    await db.commit()
    return manager, client, outsider, org


def _auth(user):
    token = create_access_token(str(user.id), user.role.value, user.full_name)
    return {"Authorization": f"Bearer {token}"}


async def test_file_roundtrip_and_permissions(db):
    manager, client, outsider, org = await _seed(db)
    base = f"/api/v1/organizations/{org.id}"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        # менеджер прикрепляет файл с кириллицей в имени
        up = await http.post(
            f"{base}/files", headers=_auth(manager),
            files={"file": ("Карточка Ветро.pdf", PDF, "application/octet-stream")},
        )
        assert up.status_code == 201, up.text
        meta = up.json()
        assert meta["filename"] == "Карточка Ветро.pdf"
        assert meta["content_type"] == "application/pdf", "тип берём свой, а не присланный клиентом"

        # участник организации видит и скачивает
        listing = await http.get(f"{base}/files", headers=_auth(client))
        assert [f["id"] for f in listing.json()] == [meta["id"]]

        dl = await http.get(f"{base}/files/{meta['id']}/download", headers=_auth(client))
        assert dl.status_code == 200
        assert dl.content == PDF
        assert dl.headers["content-type"] == "application/pdf"
        assert dl.headers["content-disposition"].startswith("attachment;")
        assert "UTF-8''" in dl.headers["content-disposition"]
        assert dl.headers["x-content-type-options"] == "nosniff"

        # посторонний клиент — нет; клиент-участник загружать/удалять не может
        assert (await http.get(f"{base}/files", headers=_auth(outsider))).status_code == 403
        denied = await http.post(
            f"{base}/files", headers=_auth(client), files={"file": ("a.pdf", PDF, "application/pdf")}
        )
        assert denied.status_code == 403
        assert (await http.delete(f"{base}/files/{meta['id']}", headers=_auth(client))).status_code == 403

        # подделка: html под видом pdf
        fake = await http.post(
            f"{base}/files", headers=_auth(manager),
            files={"file": ("x.pdf", b"<html><script>alert(1)</script>", "application/pdf")},
        )
        assert fake.status_code == 422

        # менеджер удаляет
        assert (await http.delete(f"{base}/files/{meta['id']}", headers=_auth(manager))).status_code == 204
        assert (await http.get(f"{base}/files", headers=_auth(manager))).json() == []


async def test_manager_comment_visible_to_staff_hidden_from_client(db):
    manager, client, _, org = await _seed(db)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        put = await http.put(
            f"/api/v1/organizations/{org.id}/manager-comment",
            headers=_auth(manager), json={"comment": "платит по пятницам"},
        )
        assert put.status_code == 200 and put.json()["manager_comment"] == "платит по пятницам"

        staff_view = await http.get("/api/v1/organizations", headers=_auth(manager))
        assert staff_view.json()[0]["manager_comment"] == "платит по пятницам"

        for url in ("/api/v1/organizations", f"/api/v1/organizations/{org.id}"):
            r = await http.get(url, headers=_auth(client))
            assert r.status_code == 200
            body = r.json()
            body = body[0] if isinstance(body, list) else body
            assert body["manager_comment"] is None, url

        # клиент не может записать заметку ни PUT-ом, ни через PATCH реквизитов
        assert (await http.put(
            f"/api/v1/organizations/{org.id}/manager-comment",
            headers=_auth(client), json={"comment": "хак"},
        )).status_code == 403
        patch = await http.patch(
            f"/api/v1/organizations/{org.id}", headers=_auth(client),
            json={"manager_comment": "хак", "kpp": "780101001"},
        )
        assert patch.status_code == 200
        assert patch.json()["manager_comment"] is None
        assert (await http.get(f"/api/v1/organizations/{org.id}", headers=_auth(manager))
                ).json()["manager_comment"] == "платит по пятницам", "PATCH клиента не должен менять заметку"
