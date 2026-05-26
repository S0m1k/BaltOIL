"""Sprint 2026-07 Deploy 1: add created_by_id to legal_entities + seed Лидер Диз

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-26

Изменения:
1. ADD COLUMN IF NOT EXISTS created_by_id UUID NULL — кто создал версию.
2. INSERT реквизитов ООО «Лидер Диз» если нет ни одной активной записи (idempotent).

Данные из PDF «Реквизиты ООО ЛИДЕР ДИЗ.pdf», подтверждены заказчиком 2026-05-26.
"""

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    # 1. Добавить поле created_by_id (идемпотентно)
    op.execute(
        "ALTER TABLE legal_entities "
        "ADD COLUMN IF NOT EXISTS created_by_id UUID NULL"
    )

    # 2. Seed: вставить реквизиты ООО «Лидер Диз» только если нет активной записи
    op.execute("""
        INSERT INTO legal_entities (
            id,
            name,
            short_name,
            inn,
            kpp,
            ogrn,
            okpo,
            legal_address,
            actual_address,
            phone,
            email,
            bank_name,
            bik,
            checking_account,
            correspondent_account,
            director_name,
            director_title,
            is_active,
            effective_from,
            effective_to,
            created_at,
            updated_at,
            created_by_id
        )
        SELECT
            gen_random_uuid(),
            'Общество с ограниченной ответственностью «Лидер Диз»',
            'ООО «Лидер Диз»',
            '7806623211',
            '780601001',
            '1247800095663',
            '80315893',
            '195030, г. Санкт-Петербург, ш. Революции, д. 114, лит. А, помещ. 2-Н офис 227',
            NULL,
            '+7 (921) 917-15-17',
            '9171517@mail.ru',
            'Санкт-Петербургский РФ АО «Россельхозбанк»',
            '044030910',
            '40702810435210000841',
            '30101810900000000910',
            'Борзяев Дмитрий Геннадьевич',
            'Генеральный директор',
            TRUE,
            NOW(),
            NULL,
            NOW(),
            NOW(),
            NULL
        WHERE NOT EXISTS (
            SELECT 1 FROM legal_entities WHERE is_active = TRUE AND effective_to IS NULL
        )
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE legal_entities DROP COLUMN IF EXISTS created_by_id")
    # Seed-данные не удаляем при downgrade — они могут использоваться в документах.
