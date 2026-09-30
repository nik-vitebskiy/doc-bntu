from sqlalchemy import select

from app.models import Organization


def test_create_organization_form_does_not_offer_unp(client):
    response = client.get("/organizations/new")
    assert response.status_code == 200
    assert 'name="unp"' not in response.text


def test_create_organization_with_phone(session, client):
    response = client.post(
        "/organizations/new",
        data={"name": "Организация с телефоном", "phone": "+375 17 000-00-00"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    organization = session.scalar(select(Organization).where(Organization.short_name == "Организация с телефоном"))
    assert organization.phone == "+375 17 000-00-00"
    card = client.get(f"/organizations/{organization.id}")
    assert "+375 17 000-00-00" in card.text


def test_create_organization_without_phone(session, client):
    response = client.post(
        "/organizations/new",
        data={"name": "Организация без телефона"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    organization = session.scalar(select(Organization).where(Organization.short_name == "Организация без телефона"))
    assert organization.phone is None
