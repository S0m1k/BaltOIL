"""Sprint 2026-05 Deploy 1: truncate test orders, add delivery_window, drop priority, drop ASSIGNED status

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-20

Consolidates all Deploy 1 DB changes into one migration:
1. TRUNCATE all order-related tables (test data cleanup)
2. Add delivery_window enum + column (NOT NULL, safe after TRUNCATE)
3. Drop priority column and orderpriority enum
4. Recreate orderstatus enum without ASSIGNED (rename old → create new → alter → drop old)
   Applied to: orders.status, order_status_logs.status, from_status, to_status

All DDL steps use IF EXISTS / DO $$ guards so re-runs after a partial failure are safe.
"""

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    # 1.0 — Truncate all test orders and related data, reset sequences
    op.execute("""
        TRUNCATE TABLE
            payments,
            documents,
            order_status_logs,
            orders,
            order_year_counters
        RESTART IDENTITY CASCADE;
    """)

    # 1.1 — Add deliverywindow enum and column (IF NOT EXISTS guards for idempotency)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'deliverywindow') THEN
                CREATE TYPE deliverywindow AS ENUM ('07-13', '13-16', '16-20', '20-24');
            END IF;
        END $$;
    """)
    op.execute("""
        ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_window deliverywindow NOT NULL DEFAULT '07-13';
    """)
    op.execute("""
        ALTER TABLE orders ALTER COLUMN delivery_window DROP DEFAULT;
    """)

    # 1.2 — Drop priority column and enum
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS priority;")
    op.execute("DROP TYPE IF EXISTS orderpriority;")

    # 1.3 — Recreate orderstatus enum without ASSIGNED
    # (no existing rows due to TRUNCATE above, so USING cast is trivial)
    # Guards handle re-runs where rename already happened or new type already exists.
    op.execute("""
        DO $$ BEGIN
            -- Only rename if orderstatus_old doesn't exist yet (i.e. rename not done yet)
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'orderstatus')
               AND NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'orderstatus_old')
            THEN
                ALTER TYPE orderstatus RENAME TO orderstatus_old;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'orderstatus') THEN
                CREATE TYPE orderstatus AS ENUM (
                    'new', 'in_progress', 'in_transit',
                    'delivered', 'partially_delivered',
                    'closed', 'rejected'
                );
            END IF;
        END $$;
    """)
    op.execute("""
        ALTER TABLE orders
            ALTER COLUMN status TYPE orderstatus
            USING status::text::orderstatus;
    """)
    op.execute("""
        ALTER TABLE order_status_logs
            ALTER COLUMN from_status TYPE orderstatus
            USING from_status::text::orderstatus;
    """)
    op.execute("""
        ALTER TABLE order_status_logs
            ALTER COLUMN to_status TYPE orderstatus
            USING to_status::text::orderstatus;
    """)
    op.execute("DROP TYPE IF EXISTS orderstatus_old;")


def downgrade() -> None:
    # Restore orderstatus with ASSIGNED
    op.execute("ALTER TYPE orderstatus RENAME TO orderstatus_old;")
    op.execute("""
        CREATE TYPE orderstatus AS ENUM (
            'new', 'in_progress', 'assigned', 'in_transit',
            'delivered', 'partially_delivered',
            'closed', 'rejected'
        );
    """)
    op.execute("ALTER TABLE orders ALTER COLUMN status TYPE orderstatus USING status::text::orderstatus;")
    op.execute("ALTER TABLE order_status_logs ALTER COLUMN from_status TYPE orderstatus USING from_status::text::orderstatus;")
    op.execute("ALTER TABLE order_status_logs ALTER COLUMN to_status TYPE orderstatus USING to_status::text::orderstatus;")
    op.execute("DROP TYPE orderstatus_old;")

    # Restore priority
    op.execute("CREATE TYPE orderpriority AS ENUM ('normal', 'urgent');")
    op.execute("ALTER TABLE orders ADD COLUMN priority orderpriority NOT NULL DEFAULT 'normal';")

    # Drop delivery_window
    op.execute("ALTER TABLE orders DROP COLUMN delivery_window;")
    op.execute("DROP TYPE deliverywindow;")
