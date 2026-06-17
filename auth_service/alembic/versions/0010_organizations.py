"""Organizations + organization members (m2m), backfill company profiles.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # gen_random_uuid() для backfill (PG13+ имеет в ядре, extension — подстраховка)
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE SEQUENCE IF NOT EXISTS org_number_seq START 1")

    # create_type=False: тип создаём явно ниже, иначе create_table эмитит
    # повторный CREATE TYPE и падает с DuplicateObject.
    member_role = postgresql.ENUM("owner", "member", name="memberrole", create_type=False)
    member_status = postgresql.ENUM("active", "pending", name="memberstatus", create_type=False)
    member_role.create(op.get_bind(), checkfirst=True)
    member_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_number", sa.Integer, nullable=False,
                  server_default=sa.text("nextval('org_number_seq')")),
        sa.Column("company_name", sa.String(500), nullable=False),
        sa.Column("inn", sa.String(12), nullable=True),
        sa.Column("kpp", sa.String(9), nullable=True),
        sa.Column("ogrn", sa.String(15), nullable=True),
        sa.Column("legal_address", sa.Text, nullable=True),
        sa.Column("delivery_address", sa.Text, nullable=True),
        sa.Column("bank_name", sa.String(255), nullable=True),
        sa.Column("bik", sa.String(9), nullable=True),
        sa.Column("bank_account", sa.String(20), nullable=True),
        sa.Column("correspondent_account", sa.String(20), nullable=True),
        sa.Column("swift", sa.String(11), nullable=True),
        sa.Column("contract_number", sa.String(100), nullable=True),
        sa.Column("billing_email", sa.String(255), nullable=True),
        sa.Column("okved", sa.String(20), nullable=True),
        sa.Column("okpo", sa.String(10), nullable=True),
        sa.Column("okato", sa.String(11), nullable=True),
        sa.Column("fns_status", sa.String(30), nullable=True),
        sa.Column("director_name", sa.String(255), nullable=True),
        sa.Column("fns_last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tariff_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("credit_allowed", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("credit_limit", sa.Numeric(12, 2), nullable=True),
        sa.Column("fuel_coefficient", sa.Numeric(5, 3), nullable=False, server_default=sa.text("1.0")),
        sa.Column("delivery_coefficient", sa.Numeric(5, 3), nullable=False, server_default=sa.text("1.0")),
        sa.Column("is_archived", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_organizations_org_number", "organizations", ["org_number"])
    op.create_index("ix_organizations_org_number", "organizations", ["org_number"])
    op.create_index("ix_organizations_inn", "organizations", ["inn"])

    op.create_table(
        "organization_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("invite_phone", sa.String(20), nullable=True),
        sa.Column("member_role", member_role, nullable=False, server_default="member"),
        sa.Column("status", member_status, nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_organization_members_organization_id", "organization_members", ["organization_id"])
    op.create_index("ix_organization_members_user_id", "organization_members", ["user_id"])
    op.create_index("ix_organization_members_invite_phone", "organization_members", ["invite_phone"])

    # ── Backfill: company-профиль → одна организация + owner-membership ──────────
    op.execute("""
        DO $$
        DECLARE
            r RECORD;
            new_org_id uuid;
        BEGIN
            FOR r IN SELECT * FROM client_profiles WHERE client_type = 'company' LOOP
                INSERT INTO organizations (
                    id, org_number, company_name, inn, kpp, ogrn, legal_address, delivery_address,
                    bank_name, bik, bank_account, correspondent_account, swift,
                    contract_number, billing_email,
                    okved, okpo, okato, fns_status, director_name, fns_last_sync_at,
                    tariff_id, credit_allowed, credit_limit, fuel_coefficient, delivery_coefficient,
                    created_at, updated_at
                ) VALUES (
                    gen_random_uuid(), nextval('org_number_seq'),
                    COALESCE(r.company_name, 'Без названия'), r.inn, r.kpp, r.ogrn,
                    r.legal_address, r.delivery_address,
                    r.bank_name, r.bik, r.bank_account, r.correspondent_account, r.swift,
                    r.contract_number, r.billing_email,
                    r.okved, r.okpo, r.okato, r.fns_status, r.director_name, r.fns_last_sync_at,
                    r.tariff_id, r.credit_allowed, r.credit_limit,
                    r.fuel_coefficient, r.delivery_coefficient,
                    now(), now()
                ) RETURNING id INTO new_org_id;

                INSERT INTO organization_members (
                    id, organization_id, user_id, member_role, status, created_at
                ) VALUES (
                    gen_random_uuid(), new_org_id, r.user_id, 'owner', 'active', now()
                );
            END LOOP;
        END $$;
    """)

    op.execute(
        "SELECT setval('org_number_seq', "
        "COALESCE((SELECT MAX(org_number) FROM organizations), 0) + 1)"
    )


def downgrade() -> None:
    op.drop_table("organization_members")
    op.drop_table("organizations")
    op.execute("DROP TYPE IF EXISTS memberstatus")
    op.execute("DROP TYPE IF EXISTS memberrole")
    op.execute("DROP SEQUENCE IF EXISTS org_number_seq")
