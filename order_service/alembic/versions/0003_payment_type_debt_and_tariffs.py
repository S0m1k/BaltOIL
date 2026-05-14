"""Add debt payment type and tariff tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-14

Note on enum ADD VALUE:
    PostgreSQL requires ALTER TYPE ADD VALUE to run outside an explicit transaction
    (or at least not use the new value in the same txn).
    Alembic's autocommit_block() commits the current transaction, executes the statement
    in autocommit mode, then starts a new transaction — safe on PG 10+.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. Add 'debt' to paymenttype enum (autocommit — PG restriction)     #
    # ------------------------------------------------------------------ #
    with op.get_context().autocommit_block():
        op.execute(
            sa.text("ALTER TYPE paymenttype ADD VALUE IF NOT EXISTS 'debt'")
        )

    # ------------------------------------------------------------------ #
    # 1b. Add invoice_preliminary / invoice_final to documenttype enum    #
    # ------------------------------------------------------------------ #
    with op.get_context().autocommit_block():
        op.execute(
            sa.text("ALTER TYPE documenttype ADD VALUE IF NOT EXISTS 'invoice_preliminary'")
        )
    with op.get_context().autocommit_block():
        op.execute(
            sa.text("ALTER TYPE documenttype ADD VALUE IF NOT EXISTS 'invoice_final'")
        )

    # ------------------------------------------------------------------ #
    # 2. tariffs                                                           #
    # ------------------------------------------------------------------ #
    op.create_table(
        "tariffs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("name", name="uq_tariffs_name"),
    )
    op.create_index("ix_tariffs_is_default", "tariffs", ["is_default"])

    # ------------------------------------------------------------------ #
    # 3. tariff_fuel_prices                                                #
    # ------------------------------------------------------------------ #
    op.create_table(
        "tariff_fuel_prices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tariff_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tariffs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Store fuel_type as varchar — avoids coupling this table to fueltype enum
        # (enum values are 'DIESEL_SUMMER' etc. as stored in DB; VARCHAR is simpler)
        sa.Column("fuel_type", sa.String(30), nullable=False),
        sa.Column("price_per_liter", sa.Numeric(10, 4), nullable=False),
        sa.UniqueConstraint("tariff_id", "fuel_type", name="uq_tariff_fuel_prices"),
    )
    op.create_index("ix_tariff_fuel_prices_tariff_id", "tariff_fuel_prices", ["tariff_id"])

    # ------------------------------------------------------------------ #
    # 4. tariff_volume_tiers                                               #
    # ------------------------------------------------------------------ #
    op.create_table(
        "tariff_volume_tiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tariff_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tariffs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # min_volume: inclusive lower bound in litres for this discount tier
        sa.Column("min_volume", sa.Numeric(10, 2), nullable=False),
        # discount_pct: percentage off base price, e.g. 10.00 means 10%
        sa.Column("discount_pct", sa.Numeric(5, 2), nullable=False),
        sa.UniqueConstraint("tariff_id", "min_volume", name="uq_tariff_volume_tiers"),
    )
    op.create_index("ix_tariff_volume_tiers_tariff_id", "tariff_volume_tiers", ["tariff_id"])

    # ------------------------------------------------------------------ #
    # 5. Seed default tariff with placeholder prices                       #
    # NOTE: Update these prices before going live — they reflect          #
    # approximate spring-2026 wholesale prices and MUST be reviewed       #
    # by the manager on the day of deployment.                            #
    # ------------------------------------------------------------------ #
    import uuid as _uuid

    default_tariff_id = str(_uuid.uuid4())
    op.execute(
        sa.text(
            "INSERT INTO tariffs (id, name, is_default, description, created_at, updated_at) "
            "VALUES (:id, :name, true, :desc, now(), now())"
        ).bindparams(
            id=default_tariff_id,
            name="Базовый",
            desc="Базовый тариф. Цены обновляются менеджером ежедневно по данным закупки.",
        )
    )
    placeholder_prices = [
        ("DIESEL_SUMMER", "62.0000"),
        ("DIESEL_WINTER", "65.0000"),
        ("PETROL_92",     "54.0000"),
        ("PETROL_95",     "58.0000"),
        ("FUEL_OIL",      "40.0000"),
    ]
    for fuel_type, price in placeholder_prices:
        op.execute(
            sa.text(
                "INSERT INTO tariff_fuel_prices (id, tariff_id, fuel_type, price_per_liter) "
                "VALUES (gen_random_uuid(), :tid, :ft, :price)"
            ).bindparams(tid=default_tariff_id, ft=fuel_type, price=price)
        )


def downgrade() -> None:
    # Remove tariff tables (reverse order of FKs)
    op.drop_table("tariff_volume_tiers")
    op.drop_table("tariff_fuel_prices")
    op.drop_table("tariffs")

    # Removing an enum value requires a full type-swap in PostgreSQL.
    # We rename the current type, recreate without 'debt', migrate the column,
    # then drop the old type.
    op.execute(sa.text("ALTER TYPE paymenttype RENAME TO paymenttype_old"))
    op.execute(
        sa.text(
            "CREATE TYPE paymenttype AS ENUM "
            "('prepaid', 'on_delivery', 'trade_credit', 'postpaid')"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE orders ALTER COLUMN payment_type DROP DEFAULT"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE orders ALTER COLUMN payment_type TYPE paymenttype "
            "USING (CASE payment_type::text "
            "  WHEN 'debt' THEN 'trade_credit' "  # map debt → trade_credit on rollback
            "  ELSE payment_type::text "
            "END)::paymenttype"
        )
    )
    op.execute(
        sa.text("ALTER TABLE orders ALTER COLUMN payment_type SET DEFAULT 'on_delivery'")
    )
    op.execute(sa.text("DROP TYPE paymenttype_old"))
