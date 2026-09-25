# Кадровый заказ

Веб-система для учёта договоров БНТУ с организациями-заказчиками кадров.

## Быстрый запуск

```bash
git clone https://github.com/nik-vitebskiy/doc-bntu.git
cd doc-bntu
docker-compose up --build -d
# Откройте http://localhost:8000
docker-compose logs -f app
```

При первом запуске откроется одноразовая страница создания администратора. Готовых логинов и паролей в новой базе нет. После входа Excel загружается через страницу реестра. Рабочий DOCX-шаблон генерируется при первом старте в `templates/dop_soglashenie.docx`; исходный образец лежит в той же папке. Сканы и созданные документы хранятся непосредственно в PostgreSQL вместе с остальными данными; каталог `uploads/` используется только миграцией старых установок.

## Swagger / OpenAPI

Интерактивная документация JSON API доступна по адресу
[http://localhost:8000/docs](http://localhost:8000/docs), актуальная схема —
[http://localhost:8000/openapi.json](http://localhost:8000/openapi.json).

Для проверки защищённых запросов сначала раскройте группу `auth` и выполните
`POST /api/auth/login`. Swagger работает с того же origin, поэтому браузер
сохранит HttpOnly cookie `session` и автоматически отправит её в последующих
запросах. Кнопка **Authorize** показывает используемую cookie-схему, но вручную
копировать значение cookie не требуется.

Документация включена по умолчанию. Для production-сервера БНТУ её можно
отключить переменной окружения:

```env
SHOW_DOCS=false
```

После перезапуска `/docs` будет отвечать `404`. Альтернатива для внутреннего
стенда — закрыть `/docs` средствами обратного прокси с basic-auth.

## Как запустить тесты

Тесты используют отдельную временную PostgreSQL `app_test`; рабочая база не затрагивается.

```bash
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from test
docker compose -f docker-compose.test.yml down --volumes
```
