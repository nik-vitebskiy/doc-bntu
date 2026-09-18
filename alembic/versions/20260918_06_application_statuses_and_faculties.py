"""Keep two application statuses and seed the official BNTU faculties."""

from alembic import op


revision = "20260918_06"
down_revision = "20260917_05"
branch_labels = None
depends_on = None


FACULTIES = (
    ("АТФ", "Автотракторный"),
    ("ФГДИЭ", "Горного дела и инженерной экологии"),
    ("МСФ", "Машиностроительный"),
    ("МТФ", "Механико-технологический"),
    ("ФММП", "Маркетинга, менеджмента, предпринимательства"),
    ("ЭФ", "Энергетический"),
    ("ФИТР", "Информационных технологий и робототехники"),
    ("ФТУГ", "Технологий управления и гуманитаризации"),
    ("ИПФ", "Инженерно-педагогический"),
    ("ФЭС", "Энергетического строительства"),
    ("АФ", "Архитектурный"),
    ("СФ", "Строительный"),
    ("ПСФ", "Приборостроительный"),
    ("ФТК", "Транспортных коммуникаций"),
    ("ВТФ", "Военно-технический"),
    ("СТФ", "Спортивно-технический"),
    ("ФМС", "Международного сотрудничества"),
)


def upgrade():
    # This value was briefly reintroduced by mistake. Audit history remains
    # untouched; only the current application state is normalized.
    op.execute("UPDATE application SET status = 'Закрыт' WHERE status = 'Закрыта заявка'")

    # Normalize the one legacy spelling that differs from the official list.
    op.execute(
        "UPDATE faculty SET name = 'Маркетинга, менеджмента, предпринимательства' "
        "WHERE name = 'Маркетинга, менеджмента и предпринимательства'"
    )
    op.execute(
        "UPDATE specialty SET faculty = replace(faculty, "
        "'Маркетинга, менеджмента и предпринимательства', "
        "'Маркетинга, менеджмента, предпринимательства') "
        "WHERE faculty LIKE '%Маркетинга, менеджмента и предпринимательства%'"
    )

    for code, name in FACULTIES:
        safe_code = code.replace("'", "''")
        safe_name = name.replace("'", "''")
        op.execute(
            "INSERT INTO faculty(name, code) "
            f"VALUES ('{safe_name}', '{safe_code}') "
            "ON CONFLICT (name) DO UPDATE SET code = EXCLUDED.code"
        )

    # Earlier manual checks created three test-only faculty rows. Preserve
    # their linked test documents by moving the links to official faculties,
    # then remove the non-reference rows from the production directory.
    op.execute(
        """
        WITH mapping(source_name, target_name) AS (
            VALUES
                ('Тестовый факультет А', 'Автотракторный'),
                ('Тестовый факультет A', 'Автотракторный'),
                ('Тестовый факультет Б', 'Машиностроительный')
        )
        INSERT INTO contract_faculty(contract_id, faculty_id)
        SELECT cf.contract_id, target.id
        FROM contract_faculty cf
        JOIN faculty source ON source.id = cf.faculty_id
        JOIN mapping m ON m.source_name = source.name
        JOIN faculty target ON target.name = m.target_name
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        WITH mapping(source_name, target_name) AS (
            VALUES
                ('Тестовый факультет А', 'Автотракторный'),
                ('Тестовый факультет A', 'Автотракторный'),
                ('Тестовый факультет Б', 'Машиностроительный')
        )
        INSERT INTO application_faculty(application_id, faculty_id)
        SELECT af.application_id, target.id
        FROM application_faculty af
        JOIN faculty source ON source.id = af.faculty_id
        JOIN mapping m ON m.source_name = source.name
        JOIN faculty target ON target.name = m.target_name
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        "DELETE FROM contract_faculty WHERE faculty_id IN "
        "(SELECT id FROM faculty WHERE name IN "
        "('Тестовый факультет А', 'Тестовый факультет A', 'Тестовый факультет Б'))"
    )
    op.execute(
        "DELETE FROM application_faculty WHERE faculty_id IN "
        "(SELECT id FROM faculty WHERE name IN "
        "('Тестовый факультет А', 'Тестовый факультет A', 'Тестовый факультет Б'))"
    )
    op.execute(
        "UPDATE specialty SET faculty = replace(replace(replace(faculty, "
        "'Тестовый факультет А', 'Автотракторный'), "
        "'Тестовый факультет A', 'Автотракторный'), "
        "'Тестовый факультет Б', 'Машиностроительный') "
        "WHERE faculty LIKE '%Тестовый факультет%'"
    )
    op.execute(
        "DELETE FROM faculty WHERE name IN "
        "('Тестовый факультет А', 'Тестовый факультет A', 'Тестовый факультет Б')"
    )


def downgrade():
    raise NotImplementedError("Production migrations are intentionally forward-only.")
