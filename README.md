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

## Как запустить тесты

Тесты используют отдельную временную PostgreSQL `app_test`; рабочая база не затрагивается.

```bash
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from test
docker compose -f docker-compose.test.yml down --volumes
```
