"""Создать ЕДИНСТВЕННУЮ тестовую заявку от юрлица и прогнать её до «доставлено»,
чтобы на ней сгенерировались документы (счёт+УПД+ТТН+доверенность+договор).

Запуск ВНУТРИ контейнера (ходит по внутренней docker-сети, без TLS/nginx):
    docker compose exec -T order_service python /app/scripts/prod_test_state.py

Параметры — через переменные окружения (см. ниже). Идемпотентно:
  - если юрлицо с BIZ_EMAIL уже есть — логинимся;
  - повторный прогон не плодит заявки только при пустом RESET (по умолчанию создаёт
    новую заявку каждый раз — для прода запускать ОДИН раз).

В конце печатает строки:
    TEST_ORDER_ID=<uuid>
    TEST_CLIENT_ID=<uuid>
— их подставить в prod_cleanup.sh.

ВАЖНО: до запуска должен быть выполнен seed_staff.py (нужны seed-админ и водитель).
"""
import json
import os
import sys
import time
import base64
import urllib.request
import urllib.error

AUTH = os.environ.get("AUTH_URL", "http://auth_service:8001/api/v1")
ORDER = os.environ.get("ORDER_URL", "http://order_service:8002/api/v1")
DELIVERY = os.environ.get("DELIVERY_URL", "http://delivery_service:8003/api/v1")

# Учётные данные — ТОЛЬКО из окружения (в репозитории секретов нет).
def _req(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.exit(f"FATAL: переменная окружения {name} не задана (см. runbook).")
    return v

ADMIN_LOGIN = _req("ADMIN_LOGIN")       # seed-админ (телефон или email)
ADMIN_PASSWORD = _req("ADMIN_PASSWORD")
DRIVER_LOGIN = _req("DRIVER_LOGIN")     # seed-водитель
DRIVER_PASSWORD = _req("DRIVER_PASSWORD")

BIZ_INN = os.environ.get("BIZ_INN", "7707083893")   # реальный ИНН (DaData подтянет реквизиты)
BIZ_EMAIL = os.environ.get("BIZ_EMAIL", "testfirma@baltoil.ru")
BIZ_PHONE = os.environ.get("BIZ_PHONE", "+7 812 000 00 01")
BIZ_PASSWORD = _req("BIZ_PASSWORD")     # пароль тест-юрлица
BIZ_NAME = os.environ.get("BIZ_NAME", "Тестовый Контакт")

FUEL = os.environ.get("FUEL", "diesel_summer")
ARRIVAL_VOLUME = float(os.environ.get("ARRIVAL_VOLUME", "10000"))
ORDER_VOLUME = float(os.environ.get("ORDER_VOLUME", "5000"))
DELIVERY_ADDRESS = os.environ.get("DELIVERY_ADDRESS", "г. Санкт-Петербург, Московский пр., д. 1 (ТЕСТ)")
ARRIVAL_MARK = "TESTSETUP"   # метка прихода — чтобы cleanup сохранил именно его


def call(method, url, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, (e.read().decode() or "")


def sub(token):
    p = token.split(".")[1]
    p += "=" * (-len(p) % 4)
    return json.loads(base64.urlsafe_b64decode(p))["sub"]


def login(ident, pw):
    s, r = call("POST", AUTH + "/auth/login", body={"login": ident, "password": pw})
    if s != 200:
        sys.exit(f"FATAL: login {ident!r} -> {s} {r}  (запущен ли seed_staff.py?)")
    return r["access_token"]


def main():
    print(f"== Авторизация admin / driver ==")
    admin = login(ADMIN_LOGIN, ADMIN_PASSWORD)
    driver = login(DRIVER_LOGIN, DRIVER_PASSWORD)

    print(f"== Тестовое юрлицо (ИНН {BIZ_INN}) ==")
    s, r = login_or_register_company()
    biz_token = r
    biz_id = sub(biz_token)
    print(f"   client_id={biz_id}")

    print(f"== Приход топлива {FUEL} +{ARRIVAL_VOLUME} (метка {ARRIVAL_MARK}) ==")
    s, r = call("POST", DELIVERY + "/inventory/arrivals", token=admin,
                body={"fuel_type": FUEL, "volume": ARRIVAL_VOLUME,
                      "supplier_name": ARRIVAL_MARK, "notes": ARRIVAL_MARK})
    print(f"   arrival -> {s}")
    if s not in (200, 201):
        sys.exit(f"FATAL: arrival failed {r}")

    print(f"== Создание prepaid-заявки {FUEL} {ORDER_VOLUME} л ==")
    s, order = call("POST", ORDER + "/orders", token=biz_token, body={
        "fuel_type": FUEL, "volume_requested": ORDER_VOLUME,
        "delivery_address": DELIVERY_ADDRESS, "delivery_window": "07-13",
        "payment_type": "prepaid"})
    if s != 201:
        sys.exit(f"FATAL: create order -> {s} {order}")
    oid = order["id"]
    print(f"   order {order['order_number']} id={oid}")

    print("== Проведение рейса (claim -> in_transit -> delivered) ==")
    for step in (
        ("POST", f"/orders/{oid}/claim", None),
        ("POST", f"/orders/{oid}/transition", {"to_status": "in_transit", "comment": "ТЕСТ: выезд"}),
        ("POST", f"/orders/{oid}/transition", {"to_status": "delivered", "volume_delivered": ORDER_VOLUME, "comment": "ТЕСТ: доставлено"}),
    ):
        m, path, b = step
        s, r = call(m, ORDER + path, token=driver, body=b)
        print(f"   {path.split('/')[-1]} -> {s}")
        if s != 200:
            sys.exit(f"FATAL: transition failed {r}")

    print("== Ожидание генерации документов ==")
    docs = []
    for _ in range(30):
        s, docs = call("GET", ORDER + f"/orders/{oid}/documents", token=admin)
        if s == 200 and docs and all(d["status"] in ("ready", "sent") for d in docs):
            break
        time.sleep(1)
    print(f"   документов: {len(docs)}")
    for d in docs:
        print(f"     {d['doc_type']:20s} {d['doc_number']} [{d['status']}]")
    if not docs:
        sys.exit("FATAL: документы не сгенерировались — не продолжайте очистку!")

    print("== Пометка заявки как тестовой ==")
    s, r = call("PATCH", ORDER + f"/orders/{oid}", token=admin,
                body={"manager_comment": "ТЕСТОВАЯ ЗАЯВКА — демонстрация документов, не удалять"})
    print(f"   mark -> {s}")

    print("\n================ РЕЗУЛЬТАТ (подставить в prod_cleanup.sh) ================")
    print(f"TEST_ORDER_ID={oid}")
    print(f"TEST_CLIENT_ID={biz_id}")
    print("=========================================================================")


def login_or_register_company():
    """Вернуть (status, token). Если юрлицо уже есть — логин; иначе регистрация по ИНН."""
    s, r = call("POST", AUTH + "/auth/login", body={"login": BIZ_EMAIL, "password": BIZ_PASSWORD})
    if s == 200:
        print(f"   юрлицо уже есть, вход по {BIZ_EMAIL}")
        return s, r["access_token"]
    s, r = call("POST", AUTH + "/auth/register/company", body={
        "email": BIZ_EMAIL, "phone": BIZ_PHONE, "password": BIZ_PASSWORD,
        "full_name": BIZ_NAME, "inn": BIZ_INN})
    if s != 201:
        sys.exit(f"FATAL: register company -> {s} {r}")
    print(f"   юрлицо зарегистрировано по ИНН {BIZ_INN} (реквизиты из DaData)")
    return s, r["access_token"]


if __name__ == "__main__":
    main()
