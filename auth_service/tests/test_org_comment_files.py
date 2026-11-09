"""Комментарий менеджера и файлы организации (CRM-62, CRM-63).

* заметка сотрудников видна staff и НЕ отдаётся клиенту;
* файл реквизитов: PDF/Word/Excel, проверка по расширению и магическим байтам,
  загружает/удаляет только staff, скачивают staff и участники организации;
* /internal/orders/find-buyers отдаёт идентификаторы для поиска заявок по названию.

Требуется живой PostgreSQL — см. tests/conftest.py.
"""
import pytest
from fastapi import HTTPException

from app.core.security import hash_password
from app.models.client_profile import ClientProfile, ClientType
from app.models.organization import MemberRole, MemberStatus, Organization, OrganizationMember
from app.models.user import User, UserRole
from app.routers import internal, organizations
from app.schemas.organization import OrganizationResponse
from app.services import organization_file_service as files
from app.services import organization_service as org_svc

PDF = b"%PDF-1.4\n%test\n"
DOCX = b"PK\x03\x04" + b"\x00" * 30
XLS = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1" + b"\x00" * 30


@pytest.fixture(autouse=True)
def _keep_objects_after_commit(db):
    """Сервис файлов коммитит сам; без этого объекты теста «протухают» и их атрибуты
    пришлось бы перечитывать (в запросе на каждый вызов — своя сессия, там это не нужно)."""
    db.sync_session.expire_on_commit = False


async def _user(db, role, phone, name="Пользователь"):
    user = User(
        email=None, phone=phone, hashed_password=hash_password("Password123"),
        full_name=name, role=role,
    )
    db.add(user)
    await db.flush()
    if role == UserRole.CLIENT:
        db.add(ClientProfile(user_id=user.id, client_type=ClientType.INDIVIDUAL))
        await db.flush()
    return user


async def _org(db, name="ООО «Ветро»", inn="7801234567"):
    org = Organization(company_name=name, inn=inn)
    db.add(org)
    await db.flush()
    return org


async def _member(db, org, user):
    db.add(OrganizationMember(
        organization_id=org.id, user_id=user.id,
        member_role=MemberRole.MEMBER, status=MemberStatus.ACTIVE,
    ))
    await db.flush()


# ── комментарий менеджера ────────────────────────────────────────────────────

async def test_staff_sets_comment_and_it_is_visible_to_staff(db):
    manager = await _user(db, UserRole.MANAGER, "+79990000001")
    org = await _org(db)

    updated = await org_svc.set_manager_comment(db, org.id, manager, "  платит по пятницам  ")

    assert updated.manager_comment == "платит по пятницам"
    assert organizations._for_viewer(updated, manager).manager_comment == "платит по пятницам"


async def test_empty_comment_clears_it(db):
    manager = await _user(db, UserRole.MANAGER, "+79990000001")
    org = await _org(db)
    await org_svc.set_manager_comment(db, org.id, manager, "заметка")

    cleared = await org_svc.set_manager_comment(db, org.id, manager, "   ")

    assert cleared.manager_comment is None


async def test_client_cannot_set_comment(db):
    client = await _user(db, UserRole.CLIENT, "+79990000002")
    org = await _org(db)
    await _member(db, org, client)

    with pytest.raises(HTTPException) as exc:
        await org_svc.set_manager_comment(db, org.id, client, "я сам себе комментарий")
    assert exc.value.status_code == 403


async def test_comment_is_hidden_from_client_without_touching_the_row(db):
    manager = await _user(db, UserRole.MANAGER, "+79990000001")
    client = await _user(db, UserRole.CLIENT, "+79990000002")
    org = await _org(db)
    await org_svc.set_manager_comment(db, org.id, manager, "только для своих")

    seen = organizations._for_viewer(org, client)

    assert isinstance(seen, OrganizationResponse)
    assert seen.manager_comment is None
    assert org.manager_comment == "только для своих", "ORM-объект не должен измениться"
    assert organizations._for_viewer([org], client)[0].manager_comment is None


async def test_search_by_comment_finds_org_for_staff(db):
    manager = await _user(db, UserRole.MANAGER, "+79990000001")
    org = await _org(db)
    await org_svc.set_manager_comment(db, org.id, manager, "звонить после обеда")

    found = await org_svc.list_all_organizations(db, "после обеда")
    assert [o.id for o in found] == [org.id]


# ── файлы ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,data,ctype", [
    ("реквизиты.pdf", PDF, "application/pdf"),
    ("Карточка.docx", DOCX, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("old.XLS", XLS, "application/vnd.ms-excel"),
])
def test_valid_uploads_get_our_content_type(name, data, ctype):
    clean, got = files.validate_upload(name, data)
    assert got == ctype and clean == name


@pytest.mark.parametrize("name,data", [
    ("virus.exe", b"MZ\x90\x00"),
    ("page.html", b"<script>alert(1)</script>"),
    ("noext", PDF),
    ("fake.pdf", b"<html></html>"),          # расширение pdf, содержимое — нет
    ("fake.docx", PDF),                       # docx, а внутри pdf
    ("empty.pdf", b""),
])
def test_invalid_uploads_are_rejected(name, data):
    with pytest.raises(HTTPException) as exc:
        files.validate_upload(name, data)
    assert exc.value.status_code == 422


def test_oversized_upload_is_rejected():
    with pytest.raises(HTTPException) as exc:
        files.validate_upload("big.pdf", PDF + b"0" * files.MAX_FILE_BYTES)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("raw,expected", [
    ("../../etc/passwd.pdf", "passwd.pdf"),
    ("C:\\Users\\x\\карточка.pdf", "карточка.pdf"),
    ('a<b>:"c".pdf', "a_b_c_.pdf"),
    ("  .hidden.pdf ", "hidden.pdf"),
])
def test_filename_is_stripped_of_path_and_unsafe_chars(raw, expected):
    assert files.clean_filename(raw) == expected


async def test_staff_uploads_member_downloads_client_outsider_blocked(db):
    manager = await _user(db, UserRole.MANAGER, "+79990000001")
    member = await _user(db, UserRole.CLIENT, "+79990000002")
    outsider = await _user(db, UserRole.CLIENT, "+79990000003")
    org = await _org(db)
    await _member(db, org, member)

    row = await files.add_file(db, org.id, manager, "реквизиты.pdf", PDF)
    assert row.size == len(PDF) and row.content_type == "application/pdf"

    listed = await files.list_files(db, org.id, member)
    assert [f.id for f in listed] == [row.id]

    got = await files.get_file_for_download(db, org.id, row.id, member)
    assert got.content == PDF

    with pytest.raises(HTTPException) as exc:
        await files.get_file_for_download(db, org.id, row.id, outsider)
    assert exc.value.status_code == 403


async def test_client_cannot_upload_or_delete(db):
    manager = await _user(db, UserRole.MANAGER, "+79990000001")
    member = await _user(db, UserRole.CLIENT, "+79990000002")
    org = await _org(db)
    await _member(db, org, member)
    row = await files.add_file(db, org.id, manager, "a.pdf", PDF)

    with pytest.raises(HTTPException) as exc:
        await files.add_file(db, org.id, member, "b.pdf", PDF)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        await files.delete_file(db, org.id, row.id, member)
    assert exc.value.status_code == 403


async def test_file_of_another_org_is_not_reachable_by_id(db):
    manager = await _user(db, UserRole.MANAGER, "+79990000001")
    org_a, org_b = await _org(db, "A", "7801234501"), await _org(db, "B", "7801234502")
    row = await files.add_file(db, org_a.id, manager, "a.pdf", PDF)

    with pytest.raises(HTTPException) as exc:
        await files.get_file_for_download(db, org_b.id, row.id, manager)
    assert exc.value.status_code == 404


async def test_delete_removes_file_and_files_cap_is_enforced(db):
    manager = await _user(db, UserRole.MANAGER, "+79990000001")
    org = await _org(db)
    row = await files.add_file(db, org.id, manager, "a.pdf", PDF)
    await files.delete_file(db, org.id, row.id, manager)
    assert await files.list_files(db, org.id, manager) == []

    for i in range(files.MAX_FILES_PER_ORG):
        await files.add_file(db, org.id, manager, f"f{i}.pdf", PDF)
    with pytest.raises(HTTPException) as exc:
        await files.add_file(db, org.id, manager, "extra.pdf", PDF)
    assert exc.value.status_code == 422


# ── /internal/orders/find-buyers ─────────────────────────────────────────────

async def test_find_buyers_matches_org_name_person_name_inn_and_phone(db):
    org = await _org(db, "ООО «Технобридж»", "7801112223")
    person = await _user(db, UserRole.CLIENT, "+7 (981) 886-55-83", "Бурнаев Сергей")
    other = await _user(db, UserRole.CLIENT, "+79215550000", "Другой Человек")

    async def find(q):
        return await internal.find_buyers(internal.FindBuyersRequest(q=q), db)

    by_org = await find("технобридж")
    assert org.id in by_org.organization_ids and person.id not in by_org.client_ids

    by_inn = await find("78011122")
    assert org.id in by_inn.organization_ids

    by_name = await find("бурнаев")
    assert person.id in by_name.client_ids and other.id not in by_name.client_ids

    by_phone = await find("886 55 83")
    assert person.id in by_phone.client_ids

    assert (await find("   ")).client_ids == []

    # сотрудник с таким же именем «заказчиком» не считается
    manager = await _user(db, UserRole.MANAGER, "+79215551111", "Бурнаев Менеджер")
    assert manager.id not in (await find("бурнаев")).client_ids


async def test_find_buyers_treats_like_wildcards_as_text(db):
    await _user(db, UserRole.CLIENT, "+79990000009", "Иванов")

    res = await internal.find_buyers(internal.FindBuyersRequest(q="%"), db)

    assert res.client_ids == [], "«%» не должен совпадать со всеми подряд"
