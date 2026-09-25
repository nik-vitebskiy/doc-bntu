from fastapi import APIRouter, HTTPException, Request, Security, status
from fastapi.responses import Response
from fastapi.security import APIKeyCookie

from ..models import AppUser, SessionLocal
from ..services.audit_service import AuditActor
from ..services.auth_service import authenticate, change_password, verify_password
from .schemas import AuthenticatedUserResponse, ChangePasswordRequest, ErrorResponse, LoginRequest


router = APIRouter(prefix="/auth", tags=["auth"])

cookie_auth = APIKeyCookie(
    name="session",
    scheme_name="cookieAuth",
    description=(
        "Сессионная cookie FastAPI. В Swagger сначала выполните POST /api/auth/login: "
        "браузер сохранит HttpOnly cookie и отправит её в следующих запросах автоматически."
    ),
    auto_error=False,
)


def _user_response(user: AppUser) -> AuthenticatedUserResponse:
    return AuthenticatedUserResponse(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        need_password_change=user.must_change_password,
    )


def require_api_user(request: Request, _cookie: str | None = Security(cookie_auth)) -> AppUser:
    user = getattr(request.state, "user", None)
    if _cookie is None or user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется авторизация.")
    return user


@router.post(
    "/login",
    response_model=AuthenticatedUserResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Неверный логин или пароль"},
        422: {"description": "Ошибка проверки тела запроса"},
    },
    summary="Войти в систему",
    description=(
        "Проверяет логин и пароль, создаёт серверную сессию и устанавливает HttpOnly cookie "
        "`session`. После успешного ответа остальные запросы из Swagger используют эту cookie "
        "автоматически."
    ),
)
def login(payload: LoginRequest, request: Request):
    session = SessionLocal()
    try:
        client_ip = request.client.host if request.client else None
        user = authenticate(session, payload.username, payload.password, client_ip)
        if user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль.")
        request.session["user_id"] = user.id
        return _user_response(user)
    finally:
        session.close()


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={401: {"model": ErrorResponse, "description": "Сессия отсутствует"}},
    summary="Выйти из системы",
)
def logout(request: Request, _user: AppUser = Security(require_api_user)):
    request.session.clear()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me",
    tags=["settings"],
    response_model=AuthenticatedUserResponse,
    responses={401: {"model": ErrorResponse, "description": "Сессия отсутствует"}},
    summary="Получить личные данные текущего сотрудника",
    description=(
        "Возвращает ФИО, логин, роль и признак обязательной смены пароля. "
        "React использует ответ для вкладки «Профиль» раздела «Настройки». "
        "Поля профиля доступны только для чтения."
    ),
)
def current_user(user: AppUser = Security(require_api_user)):
    return _user_response(user)


@router.post(
    "/change-password",
    tags=["settings"],
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={
        400: {"model": ErrorResponse, "description": "Текущий пароль указан неверно"},
        401: {"model": ErrorResponse, "description": "Сессия отсутствует"},
        422: {"description": "Новый пароль короче 8 символов"},
    },
    summary="Сменить свой пароль",
    description=(
        "Меняет пароль текущего сотрудника. Доступно администратору и руководителю. "
        "Поле повторного пароля существует только в интерфейсе: React проверяет совпадение "
        "двух новых паролей и отправляет серверу только current_password и new_password. "
        "Пароли и их хеши не возвращаются и не попадают в журнал действий."
    ),
)
def save_password(
    payload: ChangePasswordRequest,
    request: Request,
    authenticated_user: AppUser = Security(require_api_user),
):
    session = SessionLocal()
    try:
        user = session.get(AppUser, authenticated_user.id)
        if user is None:
            request.session.clear()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется авторизация.")
        if not verify_password(payload.current_password, user.password_hash):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Текущий пароль указан неверно.")
        client_ip = request.client.host if request.client else None
        change_password(
            session,
            user,
            payload.new_password,
            audit_actor=AuditActor(user.id, client_ip),
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    finally:
        session.close()

