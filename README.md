# Кадровый заказ — demo

Веб-прототип для учёта договоров БНТУ с организациями-заказчиками кадров.

## Быстрый запуск

```bash
git clone https://github.com/nik-vitebskiy/doc-bntu.git
cd doc-bntu
docker-compose up --build -d
# Откройте http://localhost:8000
docker-compose logs -f app
```

В demo нет логина и пароля: реестр открывается сразу. Через кнопку «Импорт Excel» загрузите файл `МТЗ-из базы.xlsx`. Рабочий DOCX-шаблон генерируется при первом старте в `templates/dop_soglashenie.docx`; исходный образец лежит в той же папке. Сканы и созданные документы хранятся в `uploads/`, база PostgreSQL — в Docker-томе `postgres_data`.
