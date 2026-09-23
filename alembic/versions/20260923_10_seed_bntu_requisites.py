"""Seed editable BNTU requisites used by generated documents."""

import json

import sqlalchemy as sa
from alembic import op


revision = "20260923_10"
down_revision = "20260922_09"
branch_labels = None
depends_on = None


REQUISITES = {
    "bntu.full_name": ("Белорусский национальный технический университет", "Полное наименование"),
    "bntu.signer_position": ("Проректор по учебной работе", "Должность подписанта"),
    "bntu.signer_name": ("Николайчик Юрий Александрович", "ФИО подписанта"),
    "bntu.power_of_attorney_number": ("01-19/1090", "Номер доверенности"),
    "bntu.power_of_attorney_date": ("2026-02-10", "Дата доверенности"),
    "bntu.legal_address": ("220013, г. Минск, пр-т Независимости, 65", "Юридический адрес"),
    "bntu.unp": ("100 354 447", "УНП"),
    "bntu.okpo": ("02 071 903", "ОКПО"),
    "bntu.bank_account": ("BY69 AKBB 3632 9016 3601 3550 0000", "Расчётный счёт"),
    "bntu.bank_name": ("ОАО «АСБ Беларусбанк»", "Банк"),
    "bntu.bic": ("AKBBBY2X", "БИК"),
}


def upgrade():
    statement = sa.text("""
        INSERT INTO app_setting(key, value, description)
        VALUES (:key, CAST(:value AS jsonb), :description)
        ON CONFLICT (key) DO NOTHING
    """)
    connection = op.get_bind()
    for key, (value, description) in REQUISITES.items():
        connection.execute(statement, {
            "key": key,
            "value": json.dumps(value, ensure_ascii=False),
            "description": description,
        })


def downgrade():
    raise NotImplementedError("Production migrations are intentionally forward-only.")
