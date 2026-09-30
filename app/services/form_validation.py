from datetime import date

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator


class FormValidationError(ValueError):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__(next(iter(errors.values()), "Проверьте данные формы."))


def _required(value: str, message: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(message)
    return value


def _date(value: str, field: str, required: bool = False) -> date | None:
    value = str(value or "").strip()
    if not value:
        if required:
            raise ValueError(f"{field}: укажите дату.")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field}: укажите корректную дату.") from error


def _email(value: str) -> str:
    try:
        return validate_email(str(value or "").strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError as error:
        raise ValueError("Укажите корректный адрес электронной почты.") from error


class OrganizationForm(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str
    unp: str = ""

    @field_validator("name", mode="before")
    @classmethod
    def name_required(cls, value):
        return _required(value, "Краткое наименование обязательно.")

    @field_validator("unp", mode="before")
    @classmethod
    def valid_unp(cls, value):
        value = str(value or "").strip()
        if value and (len(value) != 9 or not value.isdigit()):
            raise ValueError("УНП должен состоять ровно из 9 цифр.")
        return value


class ContractForm(BaseModel):
    number: str
    start_date: str
    end_date: str = ""

    @model_validator(mode="after")
    def valid_contract(self):
        self.number = _required(self.number, "Номер договора обязателен.")
        start = _date(self.start_date, "Дата начала", required=True)
        end = _date(self.end_date, "Дата окончания")
        if end and end < start:
            raise ValueError("Дата окончания не может быть раньше даты начала.")
        return self


class ApplicationForm(BaseModel):
    number: str
    signed_date: str = ""
    date_end: str = ""

    @model_validator(mode="after")
    def valid_application(self):
        self.number = _required(self.number, "Номер заявки обязателен.")
        signed = _date(self.signed_date, "Дата подписания")
        end = _date(self.date_end, "Действует до")
        if signed and end and end < signed:
            raise ValueError("Дата «Действует до» не может быть раньше даты подписания.")
        return self


class AgreementForm(BaseModel):
    number: str
    agreement_date: str

    @model_validator(mode="after")
    def valid_agreement(self):
        self.number = _required(self.number, "Номер дополнительного соглашения обязателен.")
        _date(self.agreement_date, "Дата дополнительного соглашения", required=True)
        return self


class UserCreateForm(BaseModel):
    username: str
    email: str
    initial_password: str

    @field_validator("username", mode="before")
    @classmethod
    def valid_username(cls, value):
        value = _required(value, "Логин обязателен.")
        if len(value) < 3:
            raise ValueError("Логин должен содержать не менее 3 символов.")
        return value

    @field_validator("email", mode="before")
    @classmethod
    def valid_email(cls, value):
        return _email(value)

    @field_validator("initial_password", mode="before")
    @classmethod
    def valid_password(cls, value):
        value = str(value or "")
        if len(value) < 8:
            raise ValueError("Пароль должен содержать не менее 8 символов.")
        return value


class EmailForm(BaseModel):
    email: str

    @field_validator("email", mode="before")
    @classmethod
    def valid_email(cls, value):
        return _email(value)


class OrderItemForm(BaseModel):
    faculty_id: str
    specialty: str
    demands: dict[str, str]

    @model_validator(mode="after")
    def valid_item(self):
        faculty = str(self.faculty_id or "").strip()
        if not faculty.isdigit() or int(faculty) <= 0:
            raise ValueError("Факультет: выберите значение из списка.")
        self.specialty = _required(self.specialty, "Специальность: выберите значение из справочника.")
        for raw_year, raw_value in self.demands.items():
            if not raw_year.isdigit() or not 2026 <= int(raw_year) <= 2036:
                raise ValueError(f"Год {raw_year}: допустимый диапазон — 2026–2036.")
            try:
                value = int(str(raw_value).strip())
            except ValueError as error:
                raise ValueError(f"{raw_year}: укажите целое неотрицательное число.") from error
            if value < 0:
                raise ValueError(f"{raw_year}: значение не может быть отрицательным.")
        return self


def validate_form(schema: type[BaseModel], **values):
    try:
        return schema.model_validate(values)
    except ValidationError as error:
        errors = {}
        for item in error.errors():
            field = str(item["loc"][-1]) if item["loc"] else "form"
            message = item["msg"].removeprefix("Value error, ")
            errors.setdefault(field, message)
        raise FormValidationError(errors) from error


def validate_order_form(form, specialty: str) -> OrderItemForm:
    demands = {
        key.removeprefix("demand_"): str(value)
        for key, value in form.items()
        if key.startswith("demand_")
    }
    return validate_form(
        OrderItemForm,
        faculty_id=str(form.get("faculty_id", "")),
        specialty=specialty,
        demands=demands,
    )
