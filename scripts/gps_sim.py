#!/usr/bin/env python3
"""Эмулятор GPS-трекера: шлёт точки на порт приёма как настоящее устройство.

Нужен, чтобы проверить карту и приём без железа и без выезда машины.
Только стандартная библиотека — запускается где угодно, включая сервер.

Примеры:
    # одна точка на локальный сервис
    python scripts/gps_sim.py --host localhost --port 8010 --device SZTK-01 --count 1

    # машина «едет» по кругу вокруг Дворцовой, точка раз в 5 секунд
    python scripts/gps_sim.py --host 5.42.118.110 --port 8010 --device SZTK-01

    # сутки истории за один заход (для проверки маршрута за дату)
    python scripts/gps_sim.py --host localhost --port 8010 --device SZTK-01 \
        --backfill-hours 8 --interval 30

То же одной строкой без скрипта:
    curl -s --data "SZTK-01 59.938732 30.312345 9" http://<host>:8010/
"""
from __future__ import annotations

import argparse
import math
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

# Старт — Дворцовая площадь; круг радиусом ~1.5 км имитирует движение по городу.
START_LAT = 59.938732
START_LON = 30.312345
CIRCLE_RADIUS_DEG = 0.013


def point_on_circle(step: int, total: int = 120) -> tuple[float, float]:
    angle = 2 * math.pi * (step % total) / total
    lat = START_LAT + CIRCLE_RADIUS_DEG * math.sin(angle)
    # Долготу сжимаем по широте, иначе «круг» выйдет овалом.
    lon = START_LON + CIRCLE_RADIUS_DEG * math.cos(angle) / math.cos(math.radians(START_LAT))
    return lat, lon


def send(url: str, line: str, timeout: float = 10.0) -> str:
    request = urllib.request.Request(
        url, data=line.encode("ascii"), headers={"Content-Type": "text/plain"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace").strip()
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}: {e.read().decode('utf-8', 'replace').strip()}"
    except Exception as e:  # сеть, таймаут, отказ — трекер тоже это переживает
        return f"ОШИБКА: {type(e).__name__}: {e}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Эмулятор GPS-трекера BaltOIL")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--path", default="/", help="Путь запроса (приёмник принимает любой)")
    parser.add_argument("--scheme", default="http", choices=["http", "https"])
    parser.add_argument("--device", default="SIM-01", help="Номер устройства")
    parser.add_argument("--token", default="", help="Токен, если он выдан трекеру")
    parser.add_argument("--interval", type=float, default=5.0, help="Секунд между точками")
    parser.add_argument("--count", type=int, default=0, help="Сколько точек (0 — бесконечно)")
    parser.add_argument("--sats", type=int, default=0, help="Спутников (0 — случайно 6..11)")
    parser.add_argument(
        "--backfill-hours", type=float, default=0,
        help="Прислать историю за N часов назад одним заходом, без пауз",
    )
    args = parser.parse_args()

    url = f"{args.scheme}://{args.host}:{args.port}{args.path}"
    print(f"Отправка на {url}, устройство {args.device}. Ctrl+C — остановить.")

    if args.backfill_hours:
        total = int(args.backfill_hours * 3600 / args.interval)
        start = datetime.now(timezone.utc) - timedelta(hours=args.backfill_hours)
        for step in range(total):
            lat, lon = point_on_circle(step)
            ts = int((start + timedelta(seconds=step * args.interval)).timestamp())
            sats = args.sats or random.randint(6, 11)
            line = _line(args, lat, lon, sats, speed=random.randint(0, 80), ts=ts)
            answer = send(url, line)
            if step % 20 == 0 or answer != "OK":
                print(f"[{step + 1}/{total}] {line} → {answer}")
        print("История отправлена.")
        return 0

    step = 0
    try:
        while args.count == 0 or step < args.count:
            lat, lon = point_on_circle(step)
            sats = args.sats or random.randint(6, 11)
            line = _line(args, lat, lon, sats, speed=random.randint(0, 80), ts=int(time.time()))
            print(f"→ {line}")
            print(f"← {send(url, line)}")
            step += 1
            if args.count == 0 or step < args.count:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nОстановлено.")
    return 0


def _line(args, lat: float, lon: float, sats: int, speed: int, ts: int) -> str:
    """Строка ровно того вида, что шлёт трекер: номер, широта, долгота, спутники."""
    head = f"{args.device} {lat:.6f} {lon:.6f} {sats} {speed} {ts}"
    return f"BO1,{args.device},{args.token},{lat:.6f},{lon:.6f},{sats},{speed},{ts}" if args.token else head


if __name__ == "__main__":
    sys.exit(main())
