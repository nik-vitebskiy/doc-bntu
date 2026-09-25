from typing import Literal

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    detail: str


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100, examples=["admin"])
    password: str = Field(min_length=1, examples=["my-test-password"])


class AuthenticatedUserResponse(BaseModel):
    id: int = Field(description="Идентификатор сотрудника")
    username: str = Field(description="Логин; в личном профиле доступен только для чтения")
    full_name: str | None = Field(description="ФИО сотрудника; в личном профиле доступно только для чтения")
    role: Literal["ADMIN", "HEAD"] = Field(
        description="Роль: ADMIN — администратор, HEAD — руководитель отдела"
    )
    need_password_change: bool = Field(
        description="Требуется обязательная смена временного пароля"
    )


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(
        min_length=1,
        examples=["temporary-password"],
        description="Текущий пароль сотрудника",
        json_schema_extra={"writeOnly": True},
    )
    new_password: str = Field(
        min_length=8,
        examples=["new-password-2026"],
        description="Новый пароль длиной не менее 8 символов",
        json_schema_extra={"writeOnly": True},
    )


class HealthResponse(BaseModel):
    status: str = "ok"

