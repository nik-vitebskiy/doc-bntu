from __future__ import annotations

import hashlib
import os
import secrets
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import AppUser, AuditLog
from .audit_service import AuditAction, AuditActor, AuditBatch
from .auth_service import hash_password, normalize_email


NEUTRAL_RECOVERY_MESSAGE = "Если такая почта зарегистрирована, письмо отправлено"
RECOVERY_UNAVAILABLE_MESSAGE = "Восстановление по почте недоступно, обратитесь к администратору"
RECOVERY_LIMIT = 3
TEMPORARY_PASSWORD_LENGTH = 14
TEMPORARY_PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


class RecoveryUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    username: str
    password: str
    from_address: str


def smtp_settings() -> SmtpSettings:
    values = {
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": os.getenv("SMTP_PORT", "").strip(),
        "username": os.getenv("SMTP_USER", "").strip(),
        "password": os.getenv("SMTP_PASSWORD", "").strip(),
        "from_address": os.getenv("SMTP_FROM", "").strip(),
    }
    if not all(values.values()):
        raise RecoveryUnavailableError(RECOVERY_UNAVAILABLE_MESSAGE)
    try:
        port = int(values["port"])
    except ValueError as error:
        raise RecoveryUnavailableError(RECOVERY_UNAVAILABLE_MESSAGE) from error
    return SmtpSettings(
        host=values["host"], port=port, username=values["username"],
        password=values["password"], from_address=values["from_address"],
    )


def generate_temporary_password() -> str:
    return "".join(secrets.choice(TEMPORARY_PASSWORD_ALPHABET) for _ in range(TEMPORARY_PASSWORD_LENGTH))


def application_login_url() -> str:
    app_url = os.getenv("APP_URL", "http://localhost:8000").strip() or "http://localhost:8000"
    return f"{app_url.rstrip('/')}/login"


def send_recovery_email(
    settings: SmtpSettings,
    *,
    recipient: str,
    username: str,
    temporary_password: str,
) -> None:
    message = EmailMessage()
    message["From"] = formataddr(("Кадровый заказ — БНТУ", settings.from_address))
    message["To"] = recipient
    message["Subject"] = "Восстановление доступа — Кадровый заказ"
    message.set_content(
        "Здравствуйте!\n\n"
        "Вы запросили восстановление доступа к системе «Кадровый заказ».\n\n"
        f"Ваш логин: {username}\n"
        f"Временный пароль: {temporary_password}\n"
        f"\nВойти: {application_login_url()}\n\n"
        "При входе система предложит задать собственный пароль — временный\n"
        "будет действовать только для этого входа.\n\n"
        "Если запрос отправили не вы — просто проигнорируйте письмо, пароль\n"
        "не изменится."
    )

    smtp_class = smtplib.SMTP_SSL if settings.port == 465 else smtplib.SMTP
    with smtp_class(settings.host, settings.port, timeout=15) as server:
        if settings.port != 465:
            server.starttls()
        server.login(settings.username, settings.password)
        server.send_message(message)


def _email_fingerprint(email: str) -> str:
    return hashlib.sha256(email.encode("utf-8")).hexdigest()


def _recent_request_count(session: Session, fingerprint: str) -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    return session.query(func.count(AuditLog.id)).filter(
        AuditLog.action == AuditAction.RECOVERY_REQUEST.value,
        AuditLog.timestamp >= since,
        AuditLog.diff["new"]["email_fingerprint"].as_string() == fingerprint,
        AuditLog.diff["new"]["recovery_result"].as_string() != "rate_limited",
    ).scalar() or 0


def _record_request(
    session: Session,
    actor: AuditActor,
    *,
    fingerprint: str,
    result: str,
    user_id: int | None,
) -> None:
    with AuditBatch(session, actor) as audit:
        audit.record_values(
            AuditAction.RECOVERY_REQUEST,
            "app_user",
            user_id,
            "Запрос восстановления доступа",
            new={"email_fingerprint": fingerprint, "recovery_result": result},
        )


def request_access_recovery(
    session: Session,
    email: str,
    *,
    ip_address: str | None = None,
) -> None:
    normalized_email = normalize_email(email)
    fingerprint = _email_fingerprint(normalized_email)
    actor = AuditActor(ip_address=ip_address)
    try:
        settings = smtp_settings()
    except RecoveryUnavailableError:
        _record_request(session, actor, fingerprint=fingerprint, result="not_sent", user_id=None)
        raise

    if _recent_request_count(session, fingerprint) >= RECOVERY_LIMIT:
        _record_request(session, actor, fingerprint=fingerprint, result="rate_limited", user_id=None)
        return

    user = session.query(AppUser).filter(
        func.lower(AppUser.email) == normalized_email,
        AppUser.is_active.is_(True),
    ).one_or_none()
    if user is None:
        _record_request(session, actor, fingerprint=fingerprint, result="not_sent", user_id=None)
        return

    temporary_password = generate_temporary_password()
    try:
        with AuditBatch(session, actor) as audit:
            user.password_hash = hash_password(temporary_password)
            user.must_change_password = True
            audit.suppress(user)
            send_recovery_email(
                settings,
                recipient=normalized_email,
                username=user.username,
                temporary_password=temporary_password,
            )
            audit.record_values(
                AuditAction.RECOVERY_REQUEST,
                "app_user",
                user.id,
                "Запрос восстановления доступа",
                new={"email_fingerprint": fingerprint, "recovery_result": "sent"},
            )
    except (OSError, smtplib.SMTPException) as error:
        _record_request(session, actor, fingerprint=fingerprint, result="not_sent", user_id=user.id)
        raise RecoveryUnavailableError(RECOVERY_UNAVAILABLE_MESSAGE) from error
