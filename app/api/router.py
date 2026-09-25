from fastapi import APIRouter

from .auth import router as auth_router
from .schemas import HealthResponse


OPENAPI_TAGS = [
    {"name": "auth", "description": "Вход, выход, текущая сессия и смена пароля."},
    {"name": "organizations", "description": "Организации-заказчики и факультетские представления реестра."},
    {"name": "contracts", "description": "Договоры и дополнительные соглашения."},
    {"name": "applications", "description": "Заявки организаций-заказчиков."},
    {"name": "orders", "description": "Редакции кадрового заказа и потребность по годам."},
    {"name": "audit", "description": "Неизменяемый журнал действий."},
    {"name": "users", "description": "Управление пользователями; только для администратора."},
    {
        "name": "settings",
        "description": "Личный профиль и смена собственного пароля; доступно обеим ролям.",
    },
    {"name": "import-export", "description": "Импорт данных из Excel и будущий экспорт."},
]


router = APIRouter(prefix="/api")
router.include_router(auth_router)


@router.get(
    "/health",
    response_model=HealthResponse,
    include_in_schema=False,
)
def health():
    return HealthResponse()

