import base64
import hashlib
import hmac
import os
from datetime import datetime, timezone

from ..models import AppUser, AuditLog

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


def ensure_admin(session) -> AppUser:
    user = session.query(AppUser).filter_by(username="admin").first()
    if not user:
        user = AppUser(username="admin", password_hash=hash_password("admin"), full_name="Администратор", role="ADMIN")
        session.add(user)
        session.commit()
    return user


def ensure_head(session) -> AppUser:
    user = session.query(AppUser).filter_by(username="head").first()
    if not user:
        user = AppUser(username="head", password_hash=hash_password("admin"), full_name="Руководитель отдела", role="HEAD")
        session.add(user)
        session.commit()
    return user


def authenticate(session, username: str, password: str) -> AppUser | None:
    user = session.query(AppUser).filter_by(username=username.strip()).first()
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        return None
    user.last_login_at = datetime.now(timezone.utc)
    session.commit()
    return user


def write_audit(session, user_id: int | None, action: str, entity_type: str, entity_id: int | None = None, details: str | None = None):
    session.add(AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=f"{entity_type}/{entity_id}" if entity_id is not None else entity_type,
        diff={"old": {}, "new": {}},
        comment=details,
        sequence=1,
    ))
    session.commit()
