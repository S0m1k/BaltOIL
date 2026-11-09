"""Клиент без пароля: заводит сотрудник, пароль клиент задаёт сам (CRM-59).

Сотрудник создаёт клиента (чтобы привязать тариф) без пароля; когда человек
регистрируется по тому же телефону, он забирает этот аккаунт — с историей заявок —
вместо ошибки «номер занят». До регистрации войти в аккаунт нельзя.

Требуется живой PostgreSQL — см. tests/conftest.py.
"""
import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import AuthError, ConflictError
from app.core.security import verify_password
from app.models.client_profile import ClientType
from app.models.user import UserRole
from app.schemas.user import CreateUserRequest, RegisterIndividualRequest
from app.services import auth_service, user_service

PHONE = "+7 (999) 000-11-22"
PHONE_OTHER_FORMAT = "89990001122"


def _create_request(**kw) -> CreateUserRequest:
    base = dict(full_name="Клиент Тарифный", role=UserRole.CLIENT, phone=PHONE)
    base.update(kw)
    return CreateUserRequest(**base)


def _register_request(**kw) -> RegisterIndividualRequest:
    base = dict(phone=PHONE_OTHER_FORMAT, password="mypass1", full_name="Клиент Сам")
    base.update(kw)
    return RegisterIndividualRequest(**base)


# ── валидация запроса ────────────────────────────────────────────────────────

def test_client_without_password_and_email_is_allowed_with_phone():
    req = _create_request()
    assert req.password is None and req.email is None


def test_staff_without_password_is_rejected():
    with pytest.raises(PydanticValidationError):
        _create_request(role=UserRole.MANAGER)


def test_client_without_password_needs_phone():
    with pytest.raises(PydanticValidationError):
        CreateUserRequest(full_name="X", role=UserRole.CLIENT, email="x@example.com")


def test_given_password_is_still_validated():
    with pytest.raises(PydanticValidationError):
        _create_request(password="short")


# ── создание без пароля ──────────────────────────────────────────────────────

async def test_created_client_has_no_usable_password(db, admin_id):
    user = await user_service.create_user_by_admin(db, _create_request(), actor_id=admin_id)
    assert user.password_set is False
    assert user.client_profile.client_type == ClientType.INDIVIDUAL

    with pytest.raises(AuthError):
        await auth_service.login(db, identifier=PHONE, password="anything")


async def test_created_client_with_password_can_login(db, admin_id):
    await user_service.create_user_by_admin(
        db, _create_request(password="Passw0rdX"), actor_id=admin_id
    )
    tokens = await auth_service.login(db, identifier=PHONE, password="Passw0rdX")
    assert tokens.access_token


# ── регистрация по телефону забирает аккаунт ─────────────────────────────────

async def test_registration_claims_passwordless_account_keeping_id_and_name(db, admin_id):
    created = await user_service.create_user_by_admin(db, _create_request(), actor_id=admin_id)

    claimed = await user_service.register_individual(db, _register_request())

    assert claimed.id == created.id, "история заявок привязана к id — он не должен смениться"
    assert claimed.full_name == "Клиент Тарифный", "имя, заведённое сотрудником, не затирается"
    assert claimed.password_set is True
    assert verify_password("mypass1", claimed.hashed_password)


async def test_claimed_client_can_log_in_with_own_password(db, admin_id):
    await user_service.create_user_by_admin(db, _create_request(), actor_id=admin_id)
    await user_service.register_individual(db, _register_request())

    tokens = await auth_service.login(db, identifier=PHONE, password="mypass1")
    assert tokens.access_token


async def test_registration_fills_email_only_when_free_and_missing(db, admin_id):
    await user_service.create_user_by_admin(db, _create_request(), actor_id=admin_id)
    claimed = await user_service.register_individual(
        db, _register_request(email="Client@Example.com")
    )
    assert claimed.email == "client@example.com"


async def test_second_registration_on_same_phone_is_rejected(db, admin_id):
    """Аккаунт уже забран — повторная регистрация по номеру получает «занят»."""
    await user_service.create_user_by_admin(db, _create_request(), actor_id=admin_id)
    await user_service.register_individual(db, _register_request())

    with pytest.raises(ConflictError):
        await user_service.register_individual(db, _register_request(password="another1"))


async def test_account_with_password_is_not_claimable(db, admin_id):
    await user_service.create_user_by_admin(
        db, _create_request(password="Passw0rdX"), actor_id=admin_id
    )
    with pytest.raises(ConflictError):
        await user_service.register_individual(db, _register_request())


async def test_one_off_client_is_claimable_and_stops_being_one_off(db, admin_id):
    one_off = await user_service.get_or_create_one_off_client(
        db, full_name="Разовый Иван", phone=PHONE, actor_id=admin_id
    )
    assert one_off.password_set is False

    claimed = await user_service.register_individual(db, _register_request())

    assert claimed.id == one_off.id
    assert claimed.client_profile.is_one_off is False


async def test_staff_account_is_never_claimed(db, admin_id):
    await user_service.create_user_by_admin(
        db,
        CreateUserRequest(
            full_name="Менеджер", role=UserRole.MANAGER, phone=PHONE, password="Passw0rdX"
        ),
        actor_id=admin_id,
    )
    with pytest.raises(ConflictError):
        await user_service.register_individual(db, _register_request())


async def test_deactivated_passwordless_account_is_not_revived(db, admin_id):
    created = await user_service.create_user_by_admin(db, _create_request(), actor_id=admin_id)
    created.is_active = False
    await db.flush()

    with pytest.raises(ConflictError):
        await user_service.register_individual(db, _register_request())


@pytest.fixture(autouse=True)
def _no_redis_throttle(monkeypatch):
    """Троттлинг входа живёт в Redis, которого в тестах нет — заглушка."""
    async def _false(*a, **kw):
        return False

    async def _noop(*a, **kw):
        return None

    monkeypatch.setattr(auth_service.login_throttle, "check_blocked", _false)
    monkeypatch.setattr(auth_service.login_throttle, "record_failure", _noop)
    monkeypatch.setattr(auth_service.login_throttle, "reset", _noop)


@pytest.fixture
async def admin_id(db):
    from app.core.security import hash_password
    from app.models.user import User

    admin = User(
        email="admin-test@example.com",
        hashed_password=hash_password("Admin1234!"),
        full_name="Админ",
        role=UserRole.ADMIN,
    )
    db.add(admin)
    await db.flush()
    return admin.id
