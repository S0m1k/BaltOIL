"""GPS-мониторинг транспорта (спринт 2026-09-12).

Revision ID: 007
Revises: 006

gps_devices — трекеры (номер устройства из прошивки, привязка к машине,
последняя точка для карты) и gps_positions — история точек на месяц.

Идемпотентно.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS gps_devices (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            device_number   VARCHAR(32)  NOT NULL UNIQUE,
            token_hash      VARCHAR(64)  NULL,
            auto_registered BOOLEAN      NOT NULL DEFAULT FALSE,
            label           VARCHAR(120) NULL,
            sim_phone       VARCHAR(20)  NULL,
            vehicle_id      UUID         NULL REFERENCES vehicles(id) ON DELETE SET NULL,
            is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
            notes           TEXT         NULL,
            last_seen_at    TIMESTAMPTZ  NULL,
            last_fix_at     TIMESTAMPTZ  NULL,
            last_lat        NUMERIC(9,6) NULL,
            last_lon        NUMERIC(9,6) NULL,
            last_sats       SMALLINT     NULL,
            last_speed_kmh  NUMERIC(6,1) NULL,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_gps_devices_device_number ON gps_devices (device_number)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_gps_devices_vehicle_id ON gps_devices (vehicle_id)")

    # BIGSERIAL, а не UUID: машина на 30-секундном интервале даёт ~90 тыс.
    # строк в месяц, и ищут их только по времени, а не по идентификатору.
    op.execute("""
        CREATE TABLE IF NOT EXISTS gps_positions (
            id          BIGSERIAL PRIMARY KEY,
            device_id   UUID         NOT NULL REFERENCES gps_devices(id) ON DELETE CASCADE,
            vehicle_id  UUID         NULL REFERENCES vehicles(id) ON DELETE SET NULL,
            recorded_at TIMESTAMPTZ  NOT NULL,
            received_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
            lat         NUMERIC(9,6) NOT NULL,
            lon         NUMERIC(9,6) NOT NULL,
            sats        SMALLINT     NOT NULL,
            accuracy_m  SMALLINT     NULL,
            speed_kmh   NUMERIC(6,1) NULL
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_gps_positions_device_time
            ON gps_positions (device_id, recorded_at)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_gps_positions_vehicle_time
            ON gps_positions (vehicle_id, recorded_at)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS gps_positions")
    op.execute("DROP TABLE IF EXISTS gps_devices")
