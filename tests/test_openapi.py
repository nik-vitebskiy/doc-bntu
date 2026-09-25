from fastapi.testclient import TestClient

from app.main import app
from app.models import AppUser
from app.services.auth_service import hash_password


EXPECTED_TAGS = {
    "auth",
    "organizations",
    "contracts",
    "applications",
    "orders",
    "audit",
    "users",
    "settings",
    "import-export",
}


def test_openapi_contains_only_documented_json_routes_and_cookie_security():
    with TestClient(app) as browser:
        response = browser.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert {tag["name"] for tag in schema["tags"]} == EXPECTED_TAGS
    assert set(schema["paths"]) == {
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/me",
        "/api/auth/change-password",
    }
    assert schema["components"]["securitySchemes"]["cookieAuth"] == {
        "type": "apiKey",
        "description": (
            "Сессионная cookie FastAPI. В Swagger сначала выполните POST /api/auth/login: "
            "браузер сохранит HttpOnly cookie и отправит её в следующих запросах автоматически."
        ),
        "in": "cookie",
        "name": "session",
    }
    assert schema["paths"]["/api/auth/me"]["get"]["security"] == [{"cookieAuth": []}]
    assert schema["paths"]["/api/auth/me"]["get"]["tags"] == ["auth", "settings"]
    assert schema["paths"]["/api/auth/change-password"]["post"]["tags"] == ["auth", "settings"]
    assert "вкладки «Профиль»" in schema["paths"]["/api/auth/me"]["get"]["description"]
    assert "Поле повторного пароля" in schema["paths"]["/api/auth/change-password"]["post"]["description"]
    user_schema = schema["components"]["schemas"]["AuthenticatedUserResponse"]
    assert user_schema["properties"]["role"]["enum"] == ["ADMIN", "HEAD"]
    password_schema = schema["components"]["schemas"]["ChangePasswordRequest"]
    assert password_schema["properties"]["current_password"]["writeOnly"] is True
    assert password_schema["properties"]["new_password"]["minLength"] == 8
    assert "/api/health" not in schema["paths"]
    assert "/login" not in schema["paths"]


def test_swagger_is_enabled_by_default_and_can_be_disabled(monkeypatch):
    monkeypatch.delenv("SHOW_DOCS", raising=False)
    with TestClient(app) as browser:
        assert browser.get("/docs").status_code == 200
        assert browser.get("/openapi.json").status_code == 200

        monkeypatch.setenv("SHOW_DOCS", "false")
        assert browser.get("/docs").status_code == 404
        assert browser.get("/openapi.json").status_code == 200


def test_api_returns_json_401_instead_of_legacy_redirect():
    with TestClient(app, follow_redirects=False) as browser:
        response = browser.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Требуется авторизация."}
    assert "location" not in response.headers


def test_login_cookie_authorizes_following_api_request(session):
    user = AppUser(
        username="swagger-user",
        password_hash=hash_password("Swagger-password-123"),
        full_name="Пользователь Swagger",
        role="HEAD",
        must_change_password=False,
    )
    session.add(user)
    session.commit()

    with TestClient(app) as browser:
        login = browser.post("/api/auth/login", json={
            "username": "swagger-user",
            "password": "Swagger-password-123",
        })
        assert login.status_code == 200
        assert login.json() == {
            "id": user.id,
            "username": "swagger-user",
            "full_name": "Пользователь Swagger",
            "role": "HEAD",
            "need_password_change": False,
        }
        assert browser.cookies.get("session")

        current = browser.get("/api/auth/me")
        assert current.status_code == 200
        assert current.json() == login.json()

        logout = browser.post("/api/auth/logout")
        assert logout.status_code == 204
        assert browser.get("/api/auth/me").status_code == 401


def test_forced_password_change_is_available_through_api(session):
    user = AppUser(
        username="new-user",
        password_hash=hash_password("Temporary-password-123"),
        full_name="Новый пользователь",
        role="HEAD",
        must_change_password=True,
    )
    session.add(user)
    session.commit()

    with TestClient(app) as browser:
        login = browser.post("/api/auth/login", json={
            "username": "new-user",
            "password": "Temporary-password-123",
        })
        assert login.status_code == 200
        assert login.json()["need_password_change"] is True
        assert browser.get("/api/auth/me").status_code == 200

        changed = browser.post("/api/auth/change-password", json={
            "current_password": "Temporary-password-123",
            "new_password": "Permanent-password-456",
        })
        assert changed.status_code == 204
        assert browser.get("/api/auth/me").json()["need_password_change"] is False

