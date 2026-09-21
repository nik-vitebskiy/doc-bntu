from sqlalchemy import select
from fastapi.testclient import TestClient

from app.models import AppUser, AuditLog
from app.services.auth_service import create_user, hash_password, verify_password


def test_empty_database_allows_one_time_admin_setup(session):
    from app.main import app

    with TestClient(app, follow_redirects=False) as browser:
        assert browser.get("/").headers["location"] == "/setup"
        response = browser.post("/setup", data={
            "full_name": "Первый администратор",
            "username": "first-admin",
            "password": "First-password-123",
            "password_repeat": "First-password-123",
        })

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    user = session.scalar(select(AppUser).where(AppUser.username == "first-admin"))
    assert user.role == "ADMIN"
    assert user.must_change_password is False
    assert verify_password("First-password-123", user.password_hash)
    audit = session.scalar(select(AuditLog).where(AuditLog.entity_type == "app_user"))
    assert audit.action == "CREATE"
    assert "First-password-123" not in str(audit.diff)
    assert user.password_hash not in str(audit.diff)


def test_admin_creates_user_and_first_login_requires_password_change(client, session):
    response = client.post("/users/new", data={
        "full_name": "Руководитель отдела",
        "username": "department-head",
        "role": "HEAD",
        "initial_password": "Initial-password-123",
        "password_repeat": "Initial-password-123",
    })
    assert response.status_code == 303
    user = session.scalar(select(AppUser).where(AppUser.username == "department-head"))
    assert user.must_change_password is True
    assert session.scalar(select(AuditLog).where(
        AuditLog.entity_type == "app_user", AuditLog.entity_id == user.id, AuditLog.action == "CREATE"
    )) is not None

    client.get("/logout")
    login = client.post("/login", data={"username": "department-head", "password": "Initial-password-123"})
    assert login.status_code == 303
    assert login.headers["location"] == "/change-password"
    assert client.get("/").headers["location"] == "/change-password"

    changed = client.post("/change-password", data={
        "current_password": "Initial-password-123",
        "new_password": "Permanent-password-456",
        "password_repeat": "Permanent-password-456",
    })
    assert changed.status_code == 303
    session.expire_all()
    user = session.get(AppUser, user.id)
    assert user.must_change_password is False
    assert not verify_password("Initial-password-123", user.password_hash)
    assert verify_password("Permanent-password-456", user.password_hash)
    event = session.scalars(select(AuditLog).where(
        AuditLog.entity_type == "app_user", AuditLog.entity_id == user.id,
        AuditLog.action == "UPDATE", AuditLog.comment == "Пароль изменён",
    )).one()
    assert event.diff == {"old": {}, "new": {}}


def test_head_cannot_manage_users(session):
    from app.main import app

    head = AppUser(
        username="head-user",
        password_hash=hash_password("Head-password-123"),
        full_name="Руководитель",
        role="HEAD",
        must_change_password=False,
    )
    session.add(head)
    session.commit()
    with TestClient(app, follow_redirects=False) as browser:
        assert browser.post("/login", data={
            "username": "head-user", "password": "Head-password-123",
        }).status_code == 303
        assert browser.get("/users").status_code == 403


def test_admin_can_edit_name_and_role_but_not_demote_last_admin(client, session):
    admin = session.scalar(select(AppUser).where(AppUser.username == "test-admin"))
    blocked = client.post(f"/users/{admin.id}/edit", data={
        "full_name": "Администратор тестов", "role": "HEAD",
    })
    assert blocked.status_code == 400
    session.expire_all()
    assert session.get(AppUser, admin.id).role == "ADMIN"

    second = create_user(
        session, "Второй администратор", "second-admin", "ADMIN", "Second-password-123",
    )
    changed = client.post(f"/users/{second.id}/edit", data={
        "full_name": "Обновлённое имя", "role": "HEAD",
    })
    assert changed.status_code == 303
    session.expire_all()
    second = session.get(AppUser, second.id)
    assert second.full_name == "Обновлённое имя"
    assert second.role == "HEAD"
