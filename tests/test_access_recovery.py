import re

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import AppUser, AuditLog
from app.services.access_recovery_service import NEUTRAL_RECOVERY_MESSAGE
from app.services.auth_service import hash_password


SMTP_ENV = {
    "SMTP_HOST": "smtp.bntu.by",
    "SMTP_PORT": "587",
    "SMTP_USER": "service@bntu.by",
    "SMTP_PASSWORD": "smtp-secret",
    "SMTP_FROM": "service@bntu.by",
}


class FakeSmtp:
    messages = []

    def __init__(self, host, port, timeout):
        assert (host, port, timeout) == ("smtp.bntu.by", 587, 15)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def starttls(self):
        return None

    def login(self, username, password):
        assert (username, password) == ("service@bntu.by", "smtp-secret")

    def send_message(self, message):
        self.messages.append(message)


def configure_smtp(monkeypatch):
    for name, value in SMTP_ENV.items():
        monkeypatch.setenv(name, value)
    FakeSmtp.messages = []
    monkeypatch.setattr("app.services.access_recovery_service.smtplib.SMTP", FakeSmtp)


def create_recovery_user(session):
    user = AppUser(
        username="recovery-user",
        email="employee@bntu.by",
        password_hash=hash_password("Old-password-123"),
        full_name="Сотрудник БНТУ",
        role="HEAD",
        must_change_password=False,
        is_active=True,
    )
    session.add(user)
    session.commit()
    return user


def test_existing_email_receives_temporary_password_and_requires_change(session, monkeypatch):
    configure_smtp(monkeypatch)
    user = create_recovery_user(session)

    with TestClient(app, follow_redirects=False) as browser:
        response = browser.post("/api/auth/forgot", json={"email": "employee@bntu.by"})
        assert response.status_code == 200
        assert response.json() == {"message": NEUTRAL_RECOVERY_MESSAGE}
        assert len(FakeSmtp.messages) == 1
        message = FakeSmtp.messages[0]
        assert message["From"] == "Кадровый заказ — БНТУ <service@bntu.by>"
        assert message["Subject"] == "Восстановление доступа — Кадровый заказ"
        body = message.get_content()
        temporary_password = re.search(r"Временный пароль: (\S+)", body).group(1)
        assert len(temporary_password) >= 10
        assert "Логин: recovery-user" in body
        assert "http://testserver/login" in body

        login = browser.post("/api/auth/login", json={
            "username": "recovery-user", "password": temporary_password,
        })
        assert login.status_code == 200
        assert login.json()["need_password_change"] is True

    session.expire_all()
    assert session.get(AppUser, user.id).must_change_password is True
    event = session.scalar(select(AuditLog).where(AuditLog.action == "RECOVERY_REQUEST"))
    assert event.diff["new"]["recovery_result"] == "sent"
    assert "employee@bntu.by" not in str(event.diff)
    assert temporary_password not in str(event.diff)


def test_unknown_email_has_same_response_without_sending(session, monkeypatch):
    configure_smtp(monkeypatch)
    with TestClient(app) as browser:
        response = browser.post("/api/auth/forgot", json={"email": "unknown@bntu.by"})
    assert response.status_code == 200
    assert response.json() == {"message": NEUTRAL_RECOVERY_MESSAGE}
    assert FakeSmtp.messages == []
    event = session.scalar(select(AuditLog).where(AuditLog.action == "RECOVERY_REQUEST"))
    assert event.diff["new"]["recovery_result"] == "not_sent"


def test_recovery_returns_503_when_smtp_is_not_configured(session, monkeypatch):
    for name in SMTP_ENV:
        monkeypatch.delenv(name, raising=False)
    with TestClient(app) as browser:
        response = browser.post("/api/auth/forgot", json={"email": "employee@bntu.by"})
    assert response.status_code == 503
    assert response.json() == {
        "detail": "Восстановление по почте недоступно, обратитесь к администратору"
    }
    event = session.scalar(select(AuditLog).where(AuditLog.action == "RECOVERY_REQUEST"))
    assert event.diff["new"]["recovery_result"] == "not_sent"


def test_recovery_rate_limit_sends_only_first_three_messages(session, monkeypatch):
    configure_smtp(monkeypatch)
    create_recovery_user(session)
    with TestClient(app) as browser:
        responses = [
            browser.post("/api/auth/forgot", json={"email": "employee@bntu.by"})
            for _ in range(4)
        ]
    assert [response.status_code for response in responses] == [200, 200, 200, 200]
    assert len(FakeSmtp.messages) == 3
    events = session.scalars(select(AuditLog).where(
        AuditLog.action == "RECOVERY_REQUEST",
    ).order_by(AuditLog.id)).all()
    assert [event.diff["new"]["recovery_result"] for event in events] == [
        "sent", "sent", "sent", "rate_limited",
    ]


def test_login_page_links_to_recovery_form(monkeypatch, session):
    create_recovery_user(session)
    for name in SMTP_ENV:
        monkeypatch.delenv(name, raising=False)
    with TestClient(app) as browser:
        login = browser.get("/login")
        form = browser.get("/forgot")
    assert 'href="/forgot"' in login.text
    assert 'action="/forgot"' in form.text
