from fastapi import APIRouter

from .auth import router as auth_router
from .resources import router as resources_router
from .schemas import HealthResponse


OPENAPI_TAGS = [
    {"name": "auth", "description": "Вход, выход, текущая сессия, email и смена пароля."},
    {"name": "organizations", "description": "Организации-заказчики и факультетские представления реестра."},
    {"name": "contracts", "description": "Договоры и дополнительные соглашения."},
    {"name": "applications", "description": "Заявки организаций-заказчиков."},
    {"name": "orders", "description": "Редакции кадрового заказа и потребность по годам."},
    {"name": "audit", "description": "Неизменяемый журнал действий."},
    {"name": "users", "description": "Управление пользователями; только для администратора."},
    {
        "name": "settings",
        "description": "Личный профиль, email и смена собственного пароля; доступно обеим ролям.",
    },
    {"name": "import-export", "description": "Импорт, сверка с АИС и построчный экспорт в Excel."},
    {"name": "specialties", "description": "Справочники факультетов и специальностей."},
]


router = APIRouter(prefix="/api")
router.include_router(auth_router)
router.include_router(resources_router)


@router.get(
    "/health",
    response_model=HealthResponse,
    include_in_schema=False,
)
def health():
    return HealthResponse()

