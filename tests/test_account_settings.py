from fastapi.testclient import TestClient

from app.models import AppUser
from app.services.auth_service import hash_password


def test_admin_sees_profile_and_security_in_settings(client, user):
    response = client.get("/settings")

    assert response.status_code == 200
    assert "Личные данные" in response.text
    assert "Безопасность" in response.text
    assert 'href="/change-password"' in response.text
    assert "Реквизиты БНТУ" not in response.text


def test_head_can_open_settings_and_sees_menu_link(session):
    from app.main import app

    head = AppUser(
        username="settings-head",
        password_hash=hash_password("Head-password-123"),
        full_name="Руководитель",
        role="HEAD",
        must_change_password=False,
    )
    session.add(head)
    session.commit()
    with TestClient(app, follow_redirects=False) as browser:
        assert browser.post("/login", data={
            "username": "settings-head", "password": "Head-password-123",
        }).status_code == 303
        response = browser.get("/settings")
        assert response.status_code == 200
        assert "Руководитель отдела" in response.text
        assert 'href="/settings"' in browser.get("/").text


def test_requisites_form_endpoint_is_removed(client):
    assert client.post("/settings", data={"unp": "100354447"}).status_code == 405
