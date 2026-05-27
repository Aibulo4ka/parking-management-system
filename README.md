# Parking Management System

Система управления парковкой: бронирование мест, парковочные сессии (въезд/выезд), оплата с предоплатного баланса, OCR номерных знаков, админ-панель с аналитикой и **Telegram-уведомления о событиях** (отдельная интеграция, см. [TELEGRAM_INTEGRATION.md](TELEGRAM_INTEGRATION.md)).

## Стек

- **Backend:** FastAPI (Python 3.11), SQLAlchemy 2.0 (async), Alembic, JWT-аутентификация
- **Frontend:** React 18, Material-UI v5, Axios
- **DB:** PostgreSQL 15
- **Infra:** Docker Compose

## Быстрый старт

```bash
docker compose up -d
```

Сервисы:
- Frontend: <http://localhost:3000>
- Backend API: <http://localhost:8000>
- API Docs (Swagger): <http://localhost:8000/docs>
- PostgreSQL: `localhost:5432` (`parking_user` / `parking_pass_2024`)

`.env` уже создан с дефолтными значениями. Для Telegram-бота нужны свои `TELEGRAM_BOT_TOKEN` и `TELEGRAM_BOT_USERNAME` (получаются у [@BotFather](https://t.me/BotFather)).

## Заполнение тестовыми данными

Есть **два способа**, выбирай по ситуации.

### А) Восстановить готовый дамп (быстро, фиксированные даты)

```bash
docker compose up -d db
# дождаться 'healthy'
docker exec -i parking_db pg_restore -U parking_user -d parking_db --clean --if-exists < parking_seeded.dump
docker compose up -d backend frontend
```

Файл `parking_seeded.dump` (~320 KB) лежит в корне репозитория. Содержит снимок на момент 2026-05-25 (30 юзеров, ~2000 броней, окно -7..+7 дней от этой даты).

### Б) Прогнать seed-скрипт заново (свежие даты от текущего дня)

```bash
docker compose up -d
docker exec parking_backend python -m app.db.seed_realistic
```

По умолчанию создаст: **30 юзеров, окно -7..+7 дней** от сегодняшней даты, ~2000 бронирований, ~1000 сессий, ~1600 платежей.

Параметры через env:

```bash
docker exec -e SEED_USERS=40 -e SEED_DAYS_PAST=14 -e SEED_DAYS_FUTURE=14 \
  parking_backend python -m app.db.seed_realistic
```

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `SEED_USERS` | 30 | Сколько обычных юзеров создавать (админ и Амира поверх) |
| `SEED_DAYS_PAST` | 7 | На сколько дней назад делать брони (история) |
| `SEED_DAYS_FUTURE` | 7 | На сколько дней вперёд делать брони |

**Рекомендуется вариант Б**, если демонстрация будет позже сегодняшнего дня — он переводит «сейчас» в момент прогона, и данные не «протухают».

**Внимание:** seed удаляет всех существующих не-админских пользователей, их машины, брони, сессии и платежи. Зоны/места/тарифы не трогаются.

## Тестовые креды

| Email | Пароль | Роль | Баланс |
|---|---|---|---|
| `admin@parking.com` | `admin123` | админ | 10 000 ₽ |
| `amira@test.com` | `amira123` | обычный юзер | 5 000 ₽ |
| `*.test.com` (29 шт.) | `password123` | обычные юзеры | 0–3 000 ₽ |

## Тесты

```bash
docker exec parking_backend python -m pytest -q
```

Должно быть **134 passed**. Тестовая БД (`parking_test`) создаётся в том же Postgres-контейнере, схема накатывается через `Base.metadata.create_all`.

## Структура проекта

```
backend/
├── app/
│   ├── api/endpoints/      # REST API (auth, bookings, sessions, payments, telegram, ...)
│   ├── core/               # config, security, exceptions, dependencies
│   ├── db/                 # database, seed, seed_realistic
│   ├── models/             # SQLAlchemy-модели
│   ├── schemas/            # Pydantic-схемы
│   └── services/           # бизнес-логика (notification_service, telegram_*, reminder_worker, ...)
├── alembic/                # миграции БД
├── tests/                  # pytest (134 теста)
└── scripts/                # утилиты (замер метрик Telegram и т.п.)
frontend/
└── src/                    # React + MUI
```

## Документация

- [TELEGRAM_INTEGRATION.md](TELEGRAM_INTEGRATION.md) — архитектура Telegram-интеграции, сценарии, карта файлов для защиты курсовой

## Полезные команды

```bash
# логи backend
docker logs -f parking_backend

# подключиться к БД
docker exec -it parking_db psql -U parking_user -d parking_db

# создать миграцию из изменений в моделях
docker exec parking_backend alembic revision --autogenerate -m "описание"

# накатить миграции
docker exec parking_backend alembic upgrade head
```
