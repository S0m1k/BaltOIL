"""Юниты приёма GPS: разбор сообщения, погрешность, трек (без БД и сети).

Запуск из папки delivery_service:  pytest tests/test_gps_protocol.py
"""
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.gps_protocol import (  # noqa: E402
    ERR_BADFMT,
    ERR_NOFIX,
    ProtocolError,
    RateLimiter,
    accuracy_for_sats,
    downsample,
    haversine_m,
    parse_line,
    parse_mapping,
    quality_for_sats,
    track_summary,
)

NOW = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)


# ── Разбор сообщения трекера ──────────────────────────────────────────────────

def test_basic_message_is_device_lat_lon_sats():
    # Именно этот вид шлёт собранный трекер: номер ноды, широта, долгота, спутники.
    p = parse_line("SZTK-01 59.938732 30.312345 9", now=NOW)
    assert p.device == "SZTK-01"
    assert p.lat == Decimal("59.938732")
    assert p.lon == Decimal("30.312345")
    assert p.sats == 9
    assert p.speed_kmh is None
    assert p.recorded_at is None  # время проставит сервер


@pytest.mark.parametrize("raw", [
    "SZTK-01,59.938732,30.312345,9",
    "SZTK-01;59.938732;30.312345;9",
    "SZTK-01\t59.938732\t30.312345\t9",
    "  SZTK-01   59.938732  30.312345  9  ",
    "BO1,SZTK-01,59.938732,30.312345,9",
])
def test_separators_and_optional_prefix(raw):
    # Разделитель и служебный префикс не должны решать судьбу точки.
    p = parse_line(raw, now=NOW)
    assert (p.device, p.lat, p.sats) == ("SZTK-01", Decimal("59.938732"), 9)


def test_six_decimals_are_kept_exactly():
    # Шесть знаков — это ~11 см; float их бы уже подпортил, поэтому Decimal.
    p = parse_line("1 59.000001 30.000009 7", now=NOW)
    assert str(p.lat) == "59.000001"
    assert str(p.lon) == "30.000009"


def test_comma_decimal_separator_is_accepted():
    p = parse_line("N1;59,938732;30,312345;8", now=NOW)
    assert p.lat == Decimal("59.938732")


def test_negative_and_speed_and_timestamp():
    ts = int((NOW - timedelta(minutes=5)).timestamp())
    p = parse_line(f"node7 -33.865143 151.209900 11 62.5 {ts}", now=NOW)
    assert p.lat == Decimal("-33.865143")
    assert p.speed_kmh == 62.5
    assert p.recorded_at == NOW - timedelta(minutes=5)


def test_absurd_device_clock_falls_back_to_server_time():
    # До фикса часы модуля показывают 1980 год — такому времени доверять нельзя.
    p = parse_line("node7 59.938732 30.312345 8 0 315532800", now=NOW)
    assert p.recorded_at is None


def test_millisecond_timestamp_is_normalized():
    ts_ms = int((NOW - timedelta(minutes=1)).timestamp()) * 1000
    p = parse_line(f"node7 59.938732 30.312345 8 0 {ts_ms}", now=NOW)
    assert p.recorded_at == NOW - timedelta(minutes=1)


def test_json_body():
    p = parse_mapping({"id": "SZTK-02", "lat": "59.9", "lng": "30.3", "sats": 6}, now=NOW)
    assert p.device == "SZTK-02" and p.sats == 6


def test_key_value_body():
    p = parse_line("node=SZTK-03&lat=59.9&lon=30.3&sats=5", now=NOW)
    assert p.device == "SZTK-03" and p.sats == 5


def test_json_string_body_is_detected_without_content_type():
    p = parse_line('{"device":"SZTK-04","lat":59.9,"lon":30.3,"satellites":12}', now=NOW)
    assert p.device == "SZTK-04" and p.sats == 12


def test_missing_sats_field_still_yields_point():
    # Терять координаты из-за отсутствующего поля нельзя — машина важнее поля.
    p = parse_line("SZTK-05 59.9 30.3", now=NOW)
    assert p.sats == 3


@pytest.mark.parametrize("raw,code", [
    ("", ERR_BADFMT),
    ("просто мусор", ERR_BADFMT),
    ("SZTK-01 59.9", ERR_BADFMT),
    ("SZTK-01 95.0 30.3 9", ERR_BADFMT),        # широта вне диапазона
    ("SZTK-01 59.9 190.0 9", ERR_BADFMT),       # долгота вне диапазона
    ("SZTK-01 0.000000 0.000000 9", ERR_NOFIX),  # нулевые координаты = нет фикса
    ("SZTK-01 59.9 30.3 2", ERR_NOFIX),          # спутников мало
    ("SZTK-01 59.9 30.3 99", ERR_BADFMT),
])
def test_rejected_messages(raw, code):
    with pytest.raises(ProtocolError) as e:
        parse_line(raw, now=NOW)
    assert e.value.code == code


def test_oversized_message_is_rejected():
    with pytest.raises(ProtocolError) as e:
        parse_line("SZTK-01 " + "9" * 4000, now=NOW)
    assert e.value.code == ERR_BADFMT


# ── Погрешность по спутникам ──────────────────────────────────────────────────

@pytest.mark.parametrize("sats,expected", [
    (0, None), (2, None), (3, 60), (5, 20), (7, 9), (10, 5), (11, 4), (20, 4),
])
def test_accuracy_table(sats, expected):
    assert accuracy_for_sats(sats) == expected


@pytest.mark.parametrize("sats,quality", [
    (1, "no_fix"), (3, "poor"), (4, "poor"), (5, "fair"), (6, "fair"), (7, "good"), (12, "good"),
])
def test_quality_buckets(sats, quality):
    assert quality_for_sats(sats) == quality


# ── Математика трека ──────────────────────────────────────────────────────────

def test_haversine_known_distance():
    # Дворцовая площадь → Московский вокзал, около 2.6 км.
    d = haversine_m(59.939095, 30.315868, 59.929377, 30.362472)
    assert 2600 < d < 3000


def _pt(minute, lat, lon, speed=None, acc=9):
    return {
        "recorded_at": NOW + timedelta(minutes=minute),
        "lat": lat, "lon": lon, "speed_kmh": speed, "accuracy_m": acc,
    }


def test_summary_of_empty_track():
    s = track_summary([])
    assert s["points"] == 0 and s["distance_km"] == 0.0


def test_summary_counts_distance_and_speed():
    points = [_pt(0, 59.9391, 30.3158, 0), _pt(1, 59.9435, 30.3158, 40), _pt(2, 59.9480, 30.3158, 55)]
    s = track_summary(points)
    assert s["points"] == 3
    assert 0.9 < s["distance_km"] < 1.1   # ~500 м на градусную сотку широты × 2
    assert s["max_speed_kmh"] == 55
    assert s["first_at"] == NOW and s["last_at"] == NOW + timedelta(minutes=2)


def test_parking_jitter_does_not_create_mileage():
    # Машина стоит, приёмник дрожит на метры — пробег обязан остаться нулевым.
    points = [_pt(i, 59.939100 + i * 0.00001, 30.315800, 0) for i in range(60)]
    assert track_summary(points)["distance_km"] == 0.0


def test_teleport_outlier_is_ignored():
    # Потеря фикса даёт «прыжок» на сотни километров за минуту — это не пробег.
    points = [_pt(0, 59.9391, 30.3158, 0), _pt(1, 55.7558, 37.6173, 0), _pt(2, 55.7600, 37.6173, 0)]
    s = track_summary(points)
    assert s["distance_km"] < 1


def test_avg_speed_ignores_standing_still():
    points = [_pt(0, 59.9391, 30.3158, 0), _pt(1, 59.9435, 30.3158, 60), _pt(2, 59.9480, 30.3158, 40)]
    assert track_summary(points)["avg_speed_kmh"] == 50.0


def test_downsample_keeps_ends_and_size():
    points = list(range(10000))
    thinned = downsample(points, 500)
    assert len(thinned) == 500
    assert thinned[0] == 0 and thinned[-1] == 9999


def test_downsample_noop_for_short_track():
    points = list(range(10))
    assert downsample(points, 500) == points


# ── Антифлуд ──────────────────────────────────────────────────────────────────

def test_rate_limiter_blocks_burst_and_releases_later():
    rl = RateLimiter(min_interval_sec=3.0)
    assert rl.allow("dev", 100.0) is True
    assert rl.allow("dev", 101.0) is False
    assert rl.allow("other", 101.0) is True   # соседнее устройство не страдает
    assert rl.allow("dev", 103.5) is True


def test_rate_limiter_does_not_grow_forever():
    rl = RateLimiter(min_interval_sec=1.0, max_entries=10)
    for i in range(50):
        rl.allow(f"dev{i}", float(i))
    assert len(rl._last) <= 10
