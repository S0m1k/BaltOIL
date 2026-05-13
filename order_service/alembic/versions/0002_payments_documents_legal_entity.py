"""payments, documents, legal_entity — Etap 1.1

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-13

Changes:
- PaymentType enum: replace INVOICE→POSTPAID, add PREPAID, TRADE_CREDIT
- orders: add expected_amount, final_amount, trade_credit_contract_signed
- payments: add FK constraint orders.id → CASCADE
- new table: legal_entities
- new table: documents
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── PaymentType enum ──────────────────────────────────────────────────────
    # Old DB enum: INVOICE, ON_DELIVERY (uppercase labels, legacy)
    # New DB enum: prepaid, on_delivery, trade_credit, postpaid (lowercase)
    #
    # PG restriction: newly ADD VALUE-d labels cannot be used in DML within
    # the same transaction ("unsafe use of new value").  To avoid this we skip
    # ADD VALUE entirely and do a single type-swap with a CASE expression that
    # maps INVOICE → postpaid and normalises all labels to lowercase in one shot.
    # Drop column default before type swap — PG cannot auto-cast the old
    # 'INVOICE'::paymenttype_old default to the new type.
    op.execute("ALTER TABLE orders ALTER COLUMN payment_type DROP DEFAULT")
    op.execute("ALTER TYPE paymenttype RENAME TO paymenttype_old")
    op.execute("CREATE TYPE paymenttype AS ENUM ('prepaid', 'on_delivery', 'trade_credit', 'postpaid')")
    op.execute(
        "ALTER TABLE orders ALTER COLUMN payment_type TYPE paymenttype "
        "USING (CASE lower(payment_type::text) "
        "  WHEN 'invoice' THEN 'postpaid' "
        "  ELSE lower(payment_type::text) "
        "END)::paymenttype"
    )
    op.execute("DROP TYPE paymenttype_old")
    # Restore default using new enum value
    op.execute("ALTER TABLE orders ALTER COLUMN payment_type SET DEFAULT 'on_delivery'")

    # ── orders: new columns ───────────────────────────────────────────────────
    op.add_column("orders", sa.Column("expected_amount", sa.Numeric(12, 2), nullable=True))
    op.add_column("orders", sa.Column("final_amount", sa.Numeric(12, 2), nullable=True))
    op.add_column("orders", sa.Column(
        "trade_credit_contract_signed", sa.Boolean(), nullable=False,
        server_default=sa.text("false")
    ))

    # ── payments: add FK ──────────────────────────────────────────────────────
    op.create_foreign_key(
        "fk_payments_order_id",
        "payments", "orders",
        ["order_id"], ["id"],
        ondelete="CASCADE",
    )

    # ── legal_entities ────────────────────────────────────────────────────────
    op.create_table(
        "legal_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("short_name", sa.String(100), nullable=True),
        sa.Column("inn", sa.String(12), nullable=False),
        sa.Column("kpp", sa.String(9), nullable=True),
        sa.Column("ogrn", sa.String(15), nullable=True),
        sa.Column("bank_name", sa.String(255), nullable=True),
        sa.Column("bik", sa.String(9), nullable=True),
        sa.Column("checking_account", sa.String(20), nullable=True),
        sa.Column("correspondent_account", sa.String(20), nullable=True),
        sa.Column("legal_address", sa.Text, nullable=True),
        sa.Column("actual_address", sa.Text, nullable=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("director_name", sa.String(255), nullable=True),
        sa.Column("director_title", sa.String(100), nullable=True, server_default="Директор"),
        sa.Column("effective_from", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── DocumentType / DocumentStatus enums & documents table ────────────────
    documenttype = postgresql.ENUM("invoice", "upd", "ttn", name="documenttype")
    documenttype.create(op.get_bind(), checkfirst=True)

    documentstatus = postgresql.ENUM("draft", "ready", "sent", "cancelled", name="documentstatus")
    documentstatus.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "order_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("doc_type", sa.Enum("invoice", "upd", "ttn", name="documenttype"), nullable=False),
        sa.Column("doc_number", sa.String(50), nullable=False, unique=True),
        sa.Column(
            "status",
            sa.Enum("draft", "ready", "sent", "cancelled", name="documentstatus"),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("seller_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("buyer_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("volume", sa.Numeric(10, 2), nullable=True),
        sa.Column("file_path", sa.Text, nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_documents_order_id", "documents", ["order_id"])


def downgrade() -> None:
    # ── documents ─────────────────────────────────────────────────────────────
    op.drop_table("documents")
    op.execute("DROP TYPE IF EXISTS documentstatus")
    op.execute("DROP TYPE IF EXISTS documenttype")

    # ── legal_entities ────────────────────────────────────────────────────────
    op.drop_table("legal_entities")

    # ── payments FK ───────────────────────────────────────────────────────────
    op.drop_constraint("fk_payments_order_id", "payments", type_="foreignkey")

    # ── orders: drop columns ──────────────────────────────────────────────────
    op.drop_column("orders", "trade_credit_contract_signed")
    op.drop_column("orders", "final_amount")
    op.drop_column("orders", "expected_amount")

    # ── PaymentType: restore INVOICE, remove new values ───────────────────────
    op.execute("UPDATE orders SET payment_type = 'invoice' WHERE payment_type = 'postpaid'")
    op.execute("""
        ALTER TYPE paymenttype RENAME TO paymenttype_old;
        CREATE TYPE paymenttype AS ENUM ('invoice', 'on_delivery');
        ALTER TABLE orders
            ALTER COLUMN payment_type TYPE paymenttype
            USING payment_type::text::paymenttype;
        DROP TYPE paymenttype_old;
    """)
