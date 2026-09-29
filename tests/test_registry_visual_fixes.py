from app.models import Specialty
from app.services.organization_service import canonical_faculty_name


def test_specialty_label_omits_blank_or_repeated_name():
    repeated = Specialty(code="1-25 01 07", name=" 1-25 01 07 ")
    repeated_case = Specialty(code="ABC-01", name=" abc-01 ")
    blank = Specialty(code="2-40 01 01", name="   ")
    descriptive = Specialty(code="3-33 01 01", name="Инженерное дело")

    assert repeated.display_label == "1-25 01 07"
    assert repeated_case.display_label == "ABC-01"
    assert blank.display_label == "2-40 01 01"
    assert descriptive.display_label == "3-33 01 01 — Инженерное дело"


def test_registry_renders_compact_specialty_labels_and_persistent_import_checkbox(
    session, contract, client
):
    session.add_all([
        Specialty(code="SAME-01", name="SAME-01"),
        Specialty(code="BLANK-01", name=""),
        Specialty(code="NAMED-01", name="Название"),
    ])
    session.commit()

    page = client.get(f"/organizations/{contract.organization_id}")

    assert page.status_code == 200
    assert 'data-label="SAME-01"' in page.text
    assert 'data-label="BLANK-01"' in page.text
    assert 'data-label="NAMED-01 — Название"' in page.text
    assert "SAME-01 — SAME-01" not in page.text

    registry_page = client.get("/")
    assert 'data-persist-checkbox="registry:create-organizations:user:' in registry_page.text
    assert "Создавать новые организации из файла" in registry_page.text
    assert "В файле из АИС — все организации республики" in registry_page.text

    persistence_script = client.get("/static/persistent-checkbox.js")
    assert persistence_script.status_code == 200
    assert 'localStorage.getItem(key) === "true"' in persistence_script.text
    assert "localStorage.setItem(key, String(checkbox.checked))" in persistence_script.text


def test_concatenated_mining_faculty_name_is_canonicalized():
    correct = "Горного дела и инженерной экологии"
    assert canonical_faculty_name(correct + correct) == correct
