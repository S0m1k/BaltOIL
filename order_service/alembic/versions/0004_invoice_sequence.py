"""Replace per-year COUNT with PG SEQUENCE for invoice numbers

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-15

Using a dedicated sequence removes the COUNT(*) race condition where two
concurrent requests could both read the same count and produce duplicate
invoice numbers (e.g. INV-2026-000006 twice).
"""

from alembic import op


def upgrade() -> None:
    # Sequence resets each year via application logic (nextval is monotonic,
    # year prefix is added in Python). Start from current max to avoid gaps.
    op.execute("""
        CREATE SEQUENCE IF NOT EXISTS invoice_number_seq
            START 1
            INCREMENT 1
            NO MAXVALUE
            NO CYCLE;
    """)
    # Advance to max existing number so we don't re-use any already-issued numbers
    op.execute("""
        DO $$
        DECLARE
            max_num BIGINT;
        BEGIN
            SELECT COALESCE(MAX(
                CAST(SPLIT_PART(invoice_number, '-', 3) AS BIGINT)
            ), 0)
            INTO max_num
            FROM payments
            WHERE invoice_number LIKE 'INV-%';

            IF max_num > 0 THEN
                PERFORM setval('invoice_number_seq', max_num);
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS invoice_number_seq;")
