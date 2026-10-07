# PostgreSQL — схема и миграции

Уточняет `общее.md` для базы. Формат правила: заголовок — суть;
нельзя → надо; источник; проверка; тяжесть по умолчанию. Линтер миграций —
squawk.

## Миграции

### Любое изменение схемы — миграция в git
- нельзя: `ALTER TABLE руками на стенде`
- надо: `файл миграции с номером; применяется одним инструментом везде`
- источник: [Martin Fowler — Evolutionary Database Design](https://martinfowler.com/articles/evodb.html)
- проверка: агент
- тяжесть: критично

### Применённая миграция не меняется
- нельзя: `правка 0042_*.sql после выката`
- надо: `новая миграция 0057_fix_*.sql`
- источник: [Martin Fowler — Evolutionary Database Design](https://martinfowler.com/articles/evodb.html)
- проверка: агент (git log по старым миграциям)
- тяжесть: критично

### Миграция не блокирует таблицу надолго
- нельзя: `CREATE INDEX на большой таблице; ADD COLUMN ... NOT NULL без default на старых версиях`
- надо: `CREATE INDEX CONCURRENTLY; NOT NULL через CHECK NOT VALID → VALIDATE`
- источник: [squawk — Rules](https://squawkhq.com/docs/rules)
- проверка: `squawk migrations/*.sql`
- тяжесть: важно

### Миграция владеет своими таблицами
- нельзя: `миграция модуля A меняет таблицу модуля B`
- надо: `в пути / имени миграции — модуль-владелец; реестр владения сходится с миграциями`
- источник: `общее.md` — у таблицы один владелец
- проверка: агент
- тяжесть: критично

### Демо-данные отделены от схемы
- нельзя: `INSERT тестовых записей в цепочке миграций`
- надо: `отдельный seed для разработки, не применяется на рабочих базах`
- источник: [Prisma — Seeding (разделение схемы и данных)](https://www.prisma.io/docs/orm/prisma-migrate/workflows/seeding)
- проверка: агент
- тяжесть: важно

## Типы

### Деньги — numeric, не float и не money
- нельзя: `amount double precision; amount money`
- надо: `amount numeric(18,2)`
- источник: [PostgreSQL wiki — Don't Do This](https://wiki.postgresql.org/wiki/Don%27t_Do_This#Don.27t_use_money)
- проверка: агент (grep типов в миграциях)
- тяжесть: критично

### Время — timestamptz
- нельзя: `created_at timestamp`
- надо: `created_at timestamptz NOT NULL DEFAULT now()`
- источник: [squawk — prefer-timestamptz](https://squawkhq.com/docs/prefer-timestamptz)
- проверка: `squawk`
- тяжесть: важно

### Строки — text, ключи — bigint identity
- нельзя: `char(n), varchar(255) по привычке; serial; int для ключей`
- надо: `text + CHECK на длину, если нужна; bigint GENERATED ... AS IDENTITY`
- источник: [squawk — ban-char-field, prefer-bigint-over-int, prefer-identity](https://squawkhq.com/docs/rules)
- проверка: `squawk`
- тяжесть: важно

## Целостность

### Инварианты держит база: NOT NULL, CHECK, FK, UNIQUE
- нельзя: `проверка «сумма > 0» только в коде`
- надо: `CHECK (amount > 0); FK на справочник; UNIQUE на естественный ключ`
- источник: [PostgreSQL — Constraints](https://www.postgresql.org/docs/current/ddl-constraints.html)
- проверка: агент
- тяжесть: важно

### У каждой таблицы есть первичный ключ
- нельзя: `таблица без PRIMARY KEY`
- надо: `id bigint PRIMARY KEY или составной ключ`
- источник: [PostgreSQL wiki — Don't Do This](https://wiki.postgresql.org/wiki/Don%27t_Do_This)
- проверка: агент (запрос к information_schema)
- тяжесть: критично

### Внешний ключ проиндексирован
- нельзя: `FK без индекса на ссылающемся столбце`
- надо: `CREATE INDEX ... ON child(parent_id)` — PostgreSQL сам его не создаёт
- источник: [PostgreSQL — Foreign Keys](https://www.postgresql.org/docs/current/ddl-constraints.html#DDL-CONSTRAINTS-FK)
- проверка: агент (запрос: FK без индекса)
- тяжесть: важно

### Бизнес-логика не в триггерах и процедурах
- нельзя: `проводка документа в PL/pgSQL-триггере`
- надо: `логика в коде сервиса; триггер — только техника (outbox, updated_at), с ADR`
- источник: [Martin Fowler — Database as integration point (anti-pattern)](https://martinfowler.com/bliki/IntegrationDatabase.html)
- проверка: агент (список функций и триггеров)
- тяжесть: важно

## Именование

### Имена в snake_case, во множественном или единственном — единообразно
- нельзя: `"InvoiceItems", tblInvoice, invoice и documents вперемешку`
- надо: `snake_case без кавычек; одно правило числа на весь проект`
- источник: [PostgreSQL — Identifiers and Key Words](https://www.postgresql.org/docs/current/sql-syntax-lexical.html#SQL-SYNTAX-IDENTIFIERS)
- проверка: агент
- тяжесть: мелочь

### Ограничения и индексы названы явно
- нельзя: `автоимена invoice_check1`
- надо: `ck_invoice_amount_positive, ix_invoice_org_id, fk_invoice_org`
- источник: [PostgreSQL — Constraints](https://www.postgresql.org/docs/current/ddl-constraints.html)
- проверка: агент
- тяжесть: мелочь

## Производительность

### Горячие запросы проверены EXPLAIN ANALYZE
- нельзя: `запрос в цикле по строкам (N+1); Seq Scan по большой таблице на каждом запросе`
- надо: `один запрос на выборку; план с индексом зафиксирован в тесте или заметке`
- источник: [PostgreSQL — Using EXPLAIN](https://www.postgresql.org/docs/current/using-explain.html)
- проверка: агент + pg_stat_statements на стенде
- тяжесть: важно

### Медленные запросы видны
- нельзя: `нет статистики запросов`
- надо: `pg_stat_statements включён; log_min_duration_statement на стенде`
- источник: [PostgreSQL — pg_stat_statements](https://www.postgresql.org/docs/current/pgstatstatements.html)
- проверка: агент (конфиг БД)
- тяжесть: мелочь

## Доступ

### Приложение работает не под суперпользователем
- нельзя: `приложение подключается как postgres`
- надо: `отдельная роль с правами только на свою схему; миграции — отдельной ролью`
- источник: [PostgreSQL — Database Roles / Privileges](https://www.postgresql.org/docs/current/ddl-priv.html)
- проверка: агент (строки подключения, конфиг)
- тяжесть: критично
