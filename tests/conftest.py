import os

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url


database_url = os.environ.get("DATABASE_URL", "")
if not database_url or not (make_url(database_url).database or "").endswith("_test"):
    raise RuntimeError("Audit tests refuse to run outside a database whose name ends with '_test'.")

from app.models import AppUser, SessionLocal, engine  # noqa: E402
from app.services.audit_service import AuditActor  # noqa: E402
from app.services.organization_service import create_contract, create_organization  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrated_schema_is_complete():
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        faculty_count = connection.execute(text("SELECT count(*) FROM faculty")).scalar_one()
        bntu_name = connection.execute(text(
            "SELECT value #>> '{}' FROM app_setting WHERE key = 'bntu.full_name'"
        )).scalar_one()
    assert revision == "20260923_13"
    assert faculty_count == 17
    assert bntu_name == "Белорусский национальный технический университет"


@pytest.fixture(autouse=True)
def clean_database():
    table_names = [
        "audit_log", "document_attachment", "document", "annual_demand", "order_item", "orders",
        "application_faculty", "application", "additional_agreement",
        "contract_faculty", "contract_redirect", "order_redirect", "contract", "specialty", "organization",
        "faculty", "app_setting", "app_user",
    ]
    tables = ", ".join(f'"{name}"' for name in table_names)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
    yield
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def session():
    value = SessionLocal()
    try:
        yield value
    finally:
        value.rollback()
        value.close()


@pytest.fixture
def user(session):
    value = AppUser(
        username="auditor",
        password_hash="test-only-hash",
        full_name="Тестовый сотрудник",
        role="ADMIN",
    )
    session.add(value)
    session.commit()
    session.refresh(value)
    return value


@pytest.fixture
def actor(user):
    return AuditActor(user.id, "127.0.0.1")


@pytest.fixture
def organization(session, actor):
    return create_organization(
        session,
        name="Тестовая организация",
        full_name="Полное тестовое наименование",
        address="Минск",
        department="Тестовое ведомство",
        phone="+375 00 000-00-00",
        unp="999000001",
        audit_actor=actor,
    )


@pytest.fixture
def contract(session, organization, actor):
    return create_contract(
        session,
        organization.id,
        ["Тестовый факультет"],
        "TEST-2026/01",
        "2030-12-31",
        audit_actor=actor,
    )


@pytest.fixture
def client(session):
    from app.services.auth_service import hash_password
    from app.main import app

    admin = AppUser(
        username="test-admin",
        password_hash=hash_password("Test-password-123"),
        full_name="Администратор тестов",
        role="ADMIN",
        must_change_password=False,
    )
    session.add(admin)
    session.commit()

    with TestClient(app, follow_redirects=False) as value:
        response = value.post("/login", data={"username": "test-admin", "password": "Test-password-123"})
        assert response.status_code == 303
        yield value
