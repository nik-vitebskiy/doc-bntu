from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    detail: str


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100, examples=["admin"])
    password: str = Field(min_length=1, examples=["my-test-password"])


class AuthenticatedUserResponse(BaseModel):
    id: int
    username: str
    full_name: str | None
    role: str
    need_password_change: bool


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, examples=["temporary-password"])
    new_password: str = Field(min_length=8, examples=["new-password-2026"])


class HealthResponse(BaseModel):
    status: str = "ok"

