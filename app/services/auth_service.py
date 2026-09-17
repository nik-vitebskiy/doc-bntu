import base64
import hashlib
import hmac
import os
from datetime import datetime, timezone

from ..models import AppUser
from .audit_service import AuditAction, AuditActor, AuditBatch, audit_login_enabled, audited, current_audit_batch

PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(PBKDF2_ITERATIONS, base64.b64encode(salt).decode("ascii"), base64.b64encode(digest).decode("ascii"))


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, digest = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt), int(iterations))
        return hmac.compare_digest(expected, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


@audited
def ensure_admin(session) -> AppUser:
    user = session.query(AppUser).filter_by(username="admin").first()
    if not user:
        user = AppUser(username="admin", password_hash=hash_password("admin"), full_name="Администратор", role="ADMIN")
        session.add(user)
    return user


@audited
def ensure_head(session) -> AppUser:
    user = session.query(AppUser).filter_by(username="head").first()
    if not user:
        user = AppUser(username="head", password_hash=hash_password("admin"), full_name="Руководитель отдела", role="HEAD")
        session.add(user)
    return user


def authenticate(session, username: str, password: str, ip_address: str | None = None) -> AppUser | None:
    user = session.query(AppUser).filter_by(username=username.strip()).first()
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        return None
    login_at = datetime.now(timezone.utc)
    with AuditBatch(session, AuditActor(user.id, ip_address)) as audit:
        audit.suppress(user)
        user.last_login_at = login_at
        if audit_login_enabled(session):
            audit.record(
                user,
                AuditAction.LOGIN,
                old={},
                new={"last_login_at": login_at.isoformat()},
                label=f"Пользователь {user.full_name or user.username}",
            )
    return user


@audited
def deactivate_user(session, user: AppUser):
    user.is_active = False
    return user


@audited
def change_password(session, user: AppUser, new_password: str):
    batch = current_audit_batch(session)
    user.password_hash = hash_password(new_password)
    batch.record(
        user,
        AuditAction.UPDATE,
        old={"password": "<set>"},
        new={"password": "<changed>"},
        comment="Пароль изменён",
    )
    return user
