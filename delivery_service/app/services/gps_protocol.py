"""Разбор сообщений GPS-трекера и чистая математика трека (без БД и без сети).

Трекеры самодельные и уже прошиты, менять прошивку нельзя, поэтому разбор
намеренно всеядный: сообщение приходит HTTP-запросом и может быть строкой
«номер широта долгота спутники» с любым разделителем, той же строкой через
запятую, JSON-объектом или парами ключ=значение в форме/в query. Всё это
сводится к одной точке. Незнакомые строки не выбрасываются молча — они падают
в журнал сырых сообщений (см. gps_service.RAW_LOG), чтобы по факту первых
пакетов дописать разбор, а не гадать.

Базовый позиционный вид:

    <номер> <широта> <долгота> <спутники> [скорость] [unix-время]
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

# Необязательный префикс версии: свои отправители (эмулятор, будущая прошивка
# с подписью) могут слать «BO1,...». Для трекера он не нужен.
MAGIC_PREFIXES = ("BO1",)

# Ограничение на размер сообщения: мусорный поток не должен заставлять сервер
# копить килобайты в памяти.
MAX_MESSAGE_BYTES = 2048

# Коды ошибок в ответе трекеру (`ERR:<код>`), они же — причины в журнале.
ERR_BADFMT   = "BADFMT"
ERR_AUTH     = "AUTH"
ERR_NOFIX    = "NOFIX"
ERR_RATE     = "RATE"
ERR_INACTIVE = "INACTIVE"

# Минимум спутников для координатного фикса (3 = 2D-решение).
MIN_SATS_FOR_FIX = 3

# Условная погрешность по числу спутников — заказчик просил считать именно так.
# Числа — практический ориентир для NEO-6M в городе, а не паспортная точность.
ACCURACY_BY_SATS: dict[int, int] = {3: 60, 4: 35, 5: 20, 6: 12, 7: 9, 8: 7, 9: 6, 10: 5}
ACCURACY_MANY_SATS = 4  # 11 и больше

_DEVICE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,32}$")
_COORD_RE  = re.compile(r"^[+-]?\d{1,3}([.,]\d{1,9})?$")
_INT_RE    = re.compile(r"^\d{1,3}$")

# Синонимы полей в JSON / форме / query — у разных прошивок они называются
# по-разному, а переписывать трекер мы не можем.
_KEYS_DEVICE = ("device", "device_id", "deviceid", "id", "node", "node_id", "imei", "dev", "n")
_KEYS_LAT    = ("lat", "latitude", "la", "y")
_KEYS_LON    = ("lon", "lng", "long", "longitude", "lo", "x")
_KEYS_SATS   = ("sats", "sat", "satellites", "nsat", "sv", "s")
_KEYS_SPEED  = ("speed", "spd", "v", "kmh", "velocity")
_KEYS_TS     = ("ts", "time", "timestamp", "utc", "t")
_KEYS_TOKEN  = ("token", "key", "secret", "auth")
_KEYS_CODE   = ("code", "otp", "totp", "pin")

# Код TOTP в позиционной строке стоит сразу после номера устройства:
# «SZTK-01 48291376 59.938732 30.312345 9». Цифр 6–10 — с координатой не
# спутать (у той максимум 3 цифры до точки), с hex-токеном тоже (тот от 16).
_CODE_RE = re.compile(r"^\d{6,10}$")
_TOKEN_HEX_RE = re.compile(r"^[0-9a-fA-F]{16,64}$")

# Ниже этой скорости считаем, что машина стоит (шум GPS на стоянке иначе даёт
# «пробег» в сотни метров за ночь).
IDLE_SPEED_KMH = 3.0
# Сегмент короче — дрожание приёмника, в пробег не идёт.
MIN_SEGMENT_M = 20.0
# Сегмент с такой мгновенной скоростью — выброс (потеря фикса, «прыжок»).
MAX_SEGMENT_KMH = 200.0

# Время устройства принимаем только в разумном окне вокруг серверного: часы
# трекера до фикса показывают 1980 год.
MAX_CLOCK_SKEW_SEC = 7 * 24 * 3600


class ProtocolError(Exception):
    """Сообщение не разобрано. `code` уходит трекеру как `ERR:<code>`."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ParsedPoint:
    device: str
    lat: Decimal
    lon: Decimal
    sats: int
    speed_kmh: float | None = None
    recorded_at: datetime | None = None  # None → подставится время приёма
    token: str | None = None
    code: str | None = None  # TOTP, если прошивка его шлёт


def is_valid_device_number(value: str) -> bool:
    """Номер устройства: латиница, цифры и «-_.:» до 32 символов."""
    return bool(_DEVICE_RE.match((value or "").strip()))


def accuracy_for_sats(sats: int) -> int | None:
    """Условная погрешность в метрах; None — фикса нет."""
    if sats < MIN_SATS_FOR_FIX:
        return None
    if sats >= 11:
        return ACCURACY_MANY_SATS
    return ACCURACY_BY_SATS[sats]


def quality_for_sats(sats: int) -> str:
    if sats < MIN_SATS_FOR_FIX:
        return "no_fix"
    if sats >= 7:
        return "good"
    if sats >= 5:
        return "fair"
    return "poor"


def _to_decimal(value: str) -> Decimal:
    """Координата: допускаем запятую как десятичный разделитель."""
    if not _COORD_RE.match(value):
        raise ProtocolError(ERR_BADFMT, f"координата «{value[:24]}»")
    try:
        return Decimal(value.replace(",", "."))
    except InvalidOperation:
        raise ProtocolError(ERR_BADFMT, f"координата «{value[:24]}»")


def _build_point(
    device: str, lat_s: str, lon_s: str, sats_s: str,
    speed_s: str = "", ts_s: str = "", token: str | None = None,
    code: str | None = None,
    *, now: datetime,
) -> ParsedPoint:
    device = device.strip()
    if not _DEVICE_RE.match(device):
        raise ProtocolError(ERR_BADFMT, f"номер устройства «{device[:24]}»")

    lat = _to_decimal(lat_s.strip())
    lon = _to_decimal(lon_s.strip())
    if not (Decimal("-90") <= lat <= Decimal("90")) or not (Decimal("-180") <= lon <= Decimal("180")):
        raise ProtocolError(ERR_BADFMT, "координаты вне диапазона")

    sats_s = sats_s.strip()
    if not _INT_RE.match(sats_s):
        raise ProtocolError(ERR_BADFMT, f"спутники «{sats_s[:12]}»")
    sats = int(sats_s)
    if sats > 64:
        raise ProtocolError(ERR_BADFMT, "спутники")

    # Ровно нулевые координаты приходят от приёмника без фикса — это не точка
    # в Гвинейском заливе, а «данных нет».
    if lat == 0 and lon == 0:
        raise ProtocolError(ERR_NOFIX, "нулевые координаты")
    if sats < MIN_SATS_FOR_FIX:
        raise ProtocolError(ERR_NOFIX, "мало спутников")

    speed: float | None = None
    speed_s = (speed_s or "").strip()
    if speed_s:
        try:
            speed = float(speed_s.replace(",", "."))
        except ValueError:
            raise ProtocolError(ERR_BADFMT, "скорость")
        if speed < 0 or speed > 300:
            speed = None  # явный мусор со счётчика — лучше пусто, чем ложь

    recorded_at: datetime | None = None
    ts_s = (ts_s or "").strip()
    if ts_s.isdigit():
        raw = int(ts_s)
        if raw > 10_000_000_000:   # прошивки шлют миллисекунды
            raw //= 1000
        candidate = datetime.fromtimestamp(raw, tz=timezone.utc)
        # Часы трекера до фикса врут на десятилетия — тогда молча берём
        # серверное время, сама точка при этом валидна.
        if abs((candidate - now).total_seconds()) <= MAX_CLOCK_SKEW_SEC:
            recorded_at = candidate

    return ParsedPoint(
        device=device,
        lat=lat.quantize(Decimal("0.000001")),
        lon=lon.quantize(Decimal("0.000001")),
        sats=sats,
        speed_kmh=speed,
        recorded_at=recorded_at,
        token=(token or None),
        code=(code or None),
    )


def _first(mapping: dict, keys: tuple[str, ...]) -> str | None:
    for k in keys:
        if k in mapping and mapping[k] is not None and str(mapping[k]).strip() != "":
            return str(mapping[k]).strip()
    return None


def parse_mapping(data: dict, *, now: datetime | None = None) -> ParsedPoint:
    """Точка из словаря: JSON-тело, форма или query-параметры."""
    now = now or datetime.now(timezone.utc)
    flat = {str(k).strip().lower(): v for k, v in data.items()}

    device = _first(flat, _KEYS_DEVICE)
    lat    = _first(flat, _KEYS_LAT)
    lon    = _first(flat, _KEYS_LON)
    sats   = _first(flat, _KEYS_SATS)
    if device is None or lat is None or lon is None:
        raise ProtocolError(ERR_BADFMT, "нет полей номера/координат")
    # Спутники трекер шлёт всегда, но если поле отсутствует — не теряем точку,
    # а отмечаем её как фикс неизвестного качества с минимальным доверием.
    if sats is None:
        sats = str(MIN_SATS_FOR_FIX)

    return _build_point(
        device, lat, lon, sats,
        _first(flat, _KEYS_SPEED) or "",
        _first(flat, _KEYS_TS) or "",
        _first(flat, _KEYS_TOKEN),
        _first(flat, _KEYS_CODE),
        now=now,
    )


def _split_positional(raw: str) -> tuple[list[str], str | None, str | None]:
    """Делит строку на поля, сам выбирая разделитель.

    Запятая двусмысленна: она и разделитель полей («id,59.9,30.3,9»), и
    десятичный знак в русской локали («id;59,9;30,3;9»). Поэтому пробуем
    разделители по очереди и берём первый, после которого на местах широты и
    долготы действительно оказались координаты.
    """
    candidates: list[list[str]] = []
    if ";" in raw:
        candidates.append(re.split(r"\s*;\s*", raw))
    if "\t" in raw:
        candidates.append(re.split(r"\t+", raw))
    candidates.append(re.split(r"\s+", raw))
    candidates.append(re.split(r"\s*,\s*", raw))
    # Последний шанс — всё сразу: формат «через запятую и пробел вперемешку».
    candidates.append(re.split(r"[\s,;]+", raw))

    best: list[str] = []
    for parts in candidates:
        parts = [p for p in (x.strip() for x in parts) if p != ""]
        token = code = None
        # На втором месте может стоять не координата, а удостоверение
        # устройства: код TOTP (цифры) или статический hex-токен («BO1,dev,
        # token,…»). Убираем его и проверяем раскладку дальше.
        if len(parts) >= 5 and not _COORD_RE.match(parts[1]):
            if _CODE_RE.match(parts[1]):
                code = parts[1]
                parts = parts[:1] + parts[2:]
            elif _TOKEN_HEX_RE.match(parts[1]):
                token = parts[1]
                parts = parts[:1] + parts[2:]
        if len(parts) >= 3 and _COORD_RE.match(parts[1]) and _COORD_RE.match(parts[2]):
            return parts, token, code
        if len(parts) > len(best):
            best = parts
    return best, None, None


def parse_line(line: str, *, now: datetime | None = None) -> ParsedPoint:
    """Точка из одной текстовой строки (или из JSON-строки).

    Порядок полей позиционный: номер, широта, долгота, спутники, дальше
    необязательные скорость и время. Разделитель — пробел, запятая, точка с
    запятой или табуляция; ведущий «BO1,» допускается и отбрасывается.
    """
    now = now or datetime.now(timezone.utc)
    raw = (line or "").strip().lstrip("﻿")
    if not raw:
        raise ProtocolError(ERR_BADFMT, "пустое сообщение")
    if len(raw.encode("utf-8", "ignore")) > MAX_MESSAGE_BYTES:
        raise ProtocolError(ERR_BADFMT, "сообщение слишком длинное")

    # JSON-тело, пришедшее как текст (модемы часто не ставят Content-Type).
    if raw[0] in "{[":
        try:
            data = json.loads(raw)
        except ValueError:
            raise ProtocolError(ERR_BADFMT, "битый JSON")
        if isinstance(data, list):
            raise ProtocolError(ERR_BADFMT, "ожидался объект, а не список")
        if not isinstance(data, dict):
            raise ProtocolError(ERR_BADFMT, "ожидался объект")
        return parse_mapping(data, now=now)

    # Пары ключ=значение: «id=SZTK-01&lat=59.93&lon=30.31&sats=9» или через ';'.
    if "=" in raw and re.search(r"[A-Za-z_]+\s*=", raw):
        pairs = re.split(r"[&;\s]+", raw)
        data = {}
        for pair in pairs:
            if "=" in pair:
                k, _, v = pair.partition("=")
                data[k] = v
        if data:
            return parse_mapping(data, now=now)

    for prefix in MAGIC_PREFIXES:
        if raw.upper().startswith(prefix + ","):
            raw = raw[len(prefix) + 1:]
            break

    parts, token, code = _split_positional(raw)

    if len(parts) < 3:
        raise ProtocolError(ERR_BADFMT, f"мало полей: «{raw[:60]}»")
    if len(parts) == 3:
        # Без спутников: номер, широта, долгота.
        return _build_point(parts[0], parts[1], parts[2], str(MIN_SATS_FOR_FIX),
                            token=token, code=code, now=now)

    return _build_point(
        parts[0], parts[1], parts[2], parts[3],
        parts[4] if len(parts) > 4 else "",
        parts[5] if len(parts) > 5 else "",
        token,
        code,
        now=now,
    )


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Расстояние по земной поверхности в метрах."""
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def track_summary(points: list[dict]) -> dict:
    """Сводка по треку: пробег, время в движении, скорости, погрешность.

    `points` — отсортированный по времени список словарей с ключами lat, lon,
    recorded_at, speed_kmh, accuracy_m. Выбросы (телепорты и дрожание на
    стоянке) в пробег не идут — иначе пробег растёт даже у запертой машины.
    """
    if not points:
        return {
            "points": 0, "distance_km": 0.0, "moving_minutes": 0,
            "max_speed_kmh": None, "avg_speed_kmh": None,
            "avg_accuracy_m": None, "first_at": None, "last_at": None,
        }

    distance_m = 0.0
    moving_sec = 0.0
    for prev, cur in zip(points, points[1:]):
        seg = haversine_m(float(prev["lat"]), float(prev["lon"]), float(cur["lat"]), float(cur["lon"]))
        dt = (cur["recorded_at"] - prev["recorded_at"]).total_seconds()
        if dt <= 0 or seg < MIN_SEGMENT_M or seg / dt * 3.6 > MAX_SEGMENT_KMH:
            continue
        distance_m += seg
        moving_sec += dt

    speeds = [float(p["speed_kmh"]) for p in points if p.get("speed_kmh") is not None]
    accuracies = [float(p["accuracy_m"]) for p in points if p.get("accuracy_m") is not None]
    moving_speeds = [s for s in speeds if s >= IDLE_SPEED_KMH]

    return {
        "points": len(points),
        "distance_km": round(distance_m / 1000, 2),
        "moving_minutes": int(moving_sec // 60),
        "max_speed_kmh": round(max(speeds), 1) if speeds else None,
        "avg_speed_kmh": round(sum(moving_speeds) / len(moving_speeds), 1) if moving_speeds else None,
        "avg_accuracy_m": round(sum(accuracies) / len(accuracies), 1) if accuracies else None,
        "first_at": points[0]["recorded_at"],
        "last_at": points[-1]["recorded_at"],
    }


def downsample(points: list, max_points: int) -> list:
    """Равномерное прореживание с сохранением первой и последней точки.

    Сутки на интервале 30 с — это ~2900 точек на машину; за неделю карта уже
    не отрисуется. Прореживаем на сервере, а не гоняем всё в браузер.
    """
    if max_points < 2 or len(points) <= max_points:
        return points
    step = (len(points) - 1) / (max_points - 1)
    picked = [points[round(i * step)] for i in range(max_points)]
    picked[-1] = points[-1]
    return picked


class RateLimiter:
    """Антифлуд по устройству: не чаще одной точки в `min_interval_sec`.

    Живёт в памяти процесса — приёмник однопроцессный (uvicorn без --workers),
    а пропустить лишнюю точку после рестарта не страшно.
    """

    def __init__(self, min_interval_sec: float, max_entries: int = 5000):
        self.min_interval = min_interval_sec
        self.max_entries = max_entries
        self._last: dict[str, float] = {}

    def allow(self, key: str, now: float) -> bool:
        last = self._last.get(key)
        if last is not None and now - last < self.min_interval:
            return False
        if len(self._last) >= self.max_entries and key not in self._last:
            # Вытесняем самые старые записи, а не чистим словарь целиком:
            # полная очистка разом снимала бы выдержку со ВСЕХ устройств.
            oldest = sorted(self._last.items(), key=lambda kv: kv[1])[: self.max_entries // 2]
            for stale_key, _ in oldest:
                del self._last[stale_key]
        self._last[key] = now
        return True


class FailureThrottle:
    """Ограничение неверных попыток на ключ (устройство) в скользящем окне.

    Защита кода TOTP от перебора: приёмник открыт в интернет, и без этого
    8-значный код со временем подбирается с множества адресов. После
    `max_failures` неверных кодов за `window_sec` устройство перестаёт
    проверяться до конца окна. Успешный код счётчик не сбрасывает — иначе
    атакующий получал бы новую порцию попыток после каждой точки трекера.

    Цена: перебором можно временно заглушить трекер, но не подделать его
    точки. Живёт в памяти процесса, как и антифлуд.
    """

    def __init__(self, max_failures: int, window_sec: float, max_entries: int = 5000):
        self.max_failures = max_failures
        self.window = window_sec
        self.max_entries = max_entries
        self._fails: dict[str, list[float]] = {}

    def _recent(self, key: str, now: float) -> list[float]:
        fresh = [t for t in self._fails.get(key, []) if now - t < self.window]
        if fresh:
            self._fails[key] = fresh
        else:
            self._fails.pop(key, None)
        return fresh

    def is_blocked(self, key: str, now: float) -> bool:
        return len(self._recent(key, now)) >= self.max_failures

    def record_failure(self, key: str, now: float) -> None:
        if len(self._fails) >= self.max_entries and key not in self._fails:
            # Сначала выкидываем протухшие записи, потом самые старые.
            for k in list(self._fails):
                self._recent(k, now)
            if len(self._fails) >= self.max_entries:
                oldest = sorted(self._fails, key=lambda k: self._fails[k][-1])
                for k in oldest[: self.max_entries // 2]:
                    del self._fails[k]
        self._recent(key, now)
        self._fails.setdefault(key, []).append(now)
