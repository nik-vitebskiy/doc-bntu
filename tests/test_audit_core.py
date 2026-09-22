import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models import AppSetting, AppUser, AuditLog, Organization
from app.services.audit_service import AuditBatch, audited
from app.services.auth_service import change_password
from app.services.organization_service import create_organization, delete_organization, update_organization


def test_organization_create_update_delete_and_noop(session, actor):
    organization = create_organization(
        session,
        name="Альфа",
        full_name="Организация Альфа",
        address="Минск",
        department="Ведомство",
        phone="123",
        unp="999100001",
        audit_actor=actor,
    )
    created = session.scalars(select(AuditLog).where(AuditLog.entity_type == "organization")).all()
    assert len(created) == 1
    assert created[0].action == "CREATE"
    assert created[0].diff["new"]["short_name"] == "Альфа"

    update_organization(
        session,
        organization,
        name="Альфа плюс",
        full_name="Организация Альфа",
        address="Минск",
        department="Ведомство",
        phone="123",
        audit_actor=actor,
    )
    updated = session.scalars(select(AuditLog).where(AuditLog.action == "UPDATE")).all()
    assert len(updated) == 1
    assert updated[0].diff == {"old": {"short_name": "Альфа"}, "new": {"short_name": "Альфа плюс"}}

    count_before_noop = session.query(AuditLog).count()
    update_organization(
        session,
        organization,
        name="Альфа плюс",
        full_name="Организация Альфа",
        address="Минск",
        department="Ведомство",
        phone="123",
        audit_actor=actor,
    )
    assert session.query(AuditLog).count() == count_before_noop

    organization_id = organization.id
    delete_organization(session, organization, audit_actor=actor)
    deleted = session.scalars(select(AuditLog).where(AuditLog.action == "DELETE")).one()
    assert deleted.entity_id == organization_id
    assert deleted.diff["old"]["short_name"] == "Альфа плюс"
    assert session.get(Organization, organization_id) is None


def test_audit_rows_are_immutable_through_orm(session, organization):
    row = session.scalars(select(AuditLog).where(AuditLog.entity_type == "organization")).one()
    row.comment = "нельзя"
    with pytest.raises(ValueError, match="immutable"):
        session.commit()
    session.rollback()

    row = session.get(AuditLog, row.id)
    session.delete(row)
    with pytest.raises(ValueError, match="immutable"):
        session.commit()
    session.rollback()


@pytest.mark.parametrize("statement", [
    "UPDATE audit_log SET comment = 'нельзя' WHERE id = :id",
    "DELETE FROM audit_log WHERE id = :id",
])
def test_postgresql_trigger_rejects_direct_audit_mutation(session, organization, statement):
    row_id = session.scalar(select(AuditLog.id).where(AuditLog.entity_type == "organization"))
    with pytest.raises(DBAPIError, match="audit_log is immutable"):
        session.execute(text(statement), {"id": row_id})
    session.rollback()


def test_failed_operation_rolls_back_data_and_audit(session, actor):
    @audited
    def failing_create(current_session):
        current_session.add(Organization(
            unp="999100009", short_name="Не сохранится", full_name="Не сохранится"
        ))
        current_session.flush()
        raise RuntimeError("planned failure")

    with pytest.raises(RuntimeError, match="planned failure"):
        failing_create(session, audit_actor=actor)
    assert session.scalar(select(Organization).where(Organization.unp == "999100009")) is None
    assert session.query(AuditLog).count() == 0


def test_passwords_tokens_and_secrets_are_redacted(session, actor):
    with AuditBatch(session, actor):
        account = AppUser(
            username="secure-user",
            password_hash="super-secret-password-hash",
            full_name="Безопасный пользователь",
            role="ADMIN",
        )
        setting = AppSetting(
            key="external_service",
            value={"api_token": "live-token-value", "nested": {"client_secret": "secret-value"}},
        )
        session.add_all([account, setting])

    payload = " ".join(str(row.diff) for row in session.scalars(select(AuditLog)).all())
    assert "super-secret-password-hash" not in payload
    assert "live-token-value" not in payload
    assert "secret-value" not in payload
    assert "[СКРЫТО]" in payload

    change_password(session, account, "new-secret-password", audit_actor=actor)
    password_event = session.scalars(
        select(AuditLog).where(AuditLog.entity_type == "app_user", AuditLog.action == "UPDATE")
    ).one()
    assert password_event.diff == {"old": {}, "new": {}}
    assert password_event.comment == "Пароль изменён"
