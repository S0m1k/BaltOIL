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
"""

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    # 1.0 — Truncate all test orders and related data, reset sequences
    op.execute("""
        TRUNCATE TABLE
            payments,
            documents,
            order_status_logs,
            orders,
            order_counters
        RESTART IDENTITY CASCADE;
    """)

    # 1.1 — Add deliverywindow enum and column
    op.execute("""
        CREATE TYPE deliverywindow AS ENUM ('07-13', '13-16', '16-20', '20-24');
    """)
    op.execute("""
        ALTER TABLE orders ADD COLUMN delivery_window deliverywindow NOT NULL;
    """)

    # 1.2 — Drop priority column and enum
    op.execute("""
        ALTER TABLE orders DROP COLUMN priority;
    """)
    op.execute("""
        DROP TYPE orderpriority;
    """)

    # 1.3 — Recreate orderstatus enum without ASSIGNED
    # (no existing rows due to TRUNCATE above, so USING cast is trivial)
    # order_status_logs has from_status + to_status (no plain `status` column)
    op.execute("""
        ALTER TYPE orderstatus RENAME TO orderstatus_old;
    """)
    op.execute("""
        CREATE TYPE orderstatus AS ENUM (
            'new', 'in_progress', 'in_transit',
            'delivered', 'partially_delivered',
            'closed', 'rejected'
        );
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
    op.execute("""
        DROP TYPE orderstatus_old;
    """)


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
