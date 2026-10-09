# Go — бэкенд

Уточняет `общее.md` для Go. Формат правила: заголовок — суть; нельзя → надо;
источник; проверка; тяжесть по умолчанию. Линтер — golangci-lint v2
(`version: "2"` в `.golangci.yml`).

## Структура и границы

### Модули под internal/, точки входа под cmd/
- нельзя: `бизнес-код в корне или в pkg/ без нужды отдавать его наружу`
- надо: `cmd/<бинарь>/main.go тонкий; internal/modules/<модуль>/...; internal/platform/... общее`
- источник: [Go — Organizing a Go module](https://go.dev/doc/modules/layout)
- проверка: агент
- тяжесть: важно

### Capability устроена одинаково: домен, хранилище, API
- нельзя: `логика в обработчике и в SQL-слое; одна структура на БД, домен и JSON`
- надо: `<capability>/{model.go, service.go, errors.go, postgres/{commands.go, queries.go, rows.go}, api/{routes.go, handlers.go, dto.go}}`; путь: routes → handlers → service → commands/queries
- источник: [Alistair Cockburn — Hexagonal Architecture](https://alistair.cockburn.us/hexagonal-architecture/); [Martin Fowler — CQRS (чтение отдельно от записи)](https://martinfowler.com/bliki/CQRS.html)
- проверка: агент (сравнение дерева с эталонным модулем) + depguard
- тяжесть: важно

### HTTP-обработчики живут в модуле, а не в общем пакете
- нельзя: `internal/api/ со всеми обработчиками проекта и одним роутером на всех`
- надо: `modules/<m>/<capability>/api/routes.go; общий роутер только подключает Routes() модулей`
- источник: `общее.md` — модуль-вертикаль
- проверка: агент
- тяжесть: важно

### Границы модулей держит depguard
- нельзя: `internal/modules/payroll импортирует internal/modules/personnel/adapters/postgres`
- надо: `правило depguard: модуль импортирует из чужого только его корневой пакет (публичный API)`
- источник: [golangci-lint — depguard](https://golangci-lint.run/docs/linters/configuration/#depguard)
- проверка: `golangci-lint run`
- тяжесть: критично

### Домен не импортирует транспорт и драйверы
- нельзя: `domain/*.go импортирует net/http, pgx, encoding/json-теги для API`
- надо: `домен — чистые типы и правила; pgx только в adapters/postgres, http только в api/`
- источник: [Alistair Cockburn — Hexagonal Architecture](https://alistair.cockburn.us/hexagonal-architecture/)
- проверка: `golangci-lint run` (depguard по файлам domain/)
- тяжесть: критично

### Интерфейс объявляет потребитель, маленький
- нельзя: `пакет repo экспортирует интерфейс Repository на 20 методов рядом с реализацией`
- надо: `сервис объявляет type invoiceStore interface { Get(ctx, id) (Invoice, error) }`
- источник: [Go Code Review Comments — Interfaces](https://go.dev/wiki/CodeReviewComments#interfaces)
- проверка: агент (линтер iface / interfacebloat)
- тяжесть: важно

### Зависимости передаются явно через конструктор
- нельзя: `глобальная var db *pgxpool.Pool, init() с подключениями`
- надо: `func NewService(store invoiceStore, clock Clock) *Service; сборка в composition root (cmd/)`
- источник: [Google Go Style — Global state](https://google.github.io/styleguide/go/best-practices#global-state)
- проверка: `golangci-lint run` (gochecknoglobals, gochecknoinits)
- тяжесть: важно

## Именование

### Имена пакетов короткие, в нижнем регистре, без util/common
- нельзя: `package invoiceUtils; package common`
- надо: `package invoice; package money`
- источник: [Go Blog — Package names](https://go.dev/blog/package-names)
- проверка: `golangci-lint run` (revive: var-naming, package-comments)
- тяжесть: мелочь

### Имя не повторяет пакет
- нельзя: `invoice.InvoiceService, money.MoneyFormat`
- надо: `invoice.Service, money.Format`
- источник: [Effective Go — Names](https://go.dev/doc/effective_go#names)
- проверка: `golangci-lint run` (revive: exported)
- тяжесть: мелочь

## Ошибки

### Ошибка оборачивается с контекстом через %w
- нельзя: `return err`
- надо: `return fmt.Errorf("load invoice %d: %w", id, err)`
- источник: [Go Blog — Working with Errors in Go 1.13](https://go.dev/blog/go1.13-errors)
- проверка: `golangci-lint run` (wrapcheck, errorlint)
- тяжесть: важно

### Ошибка не игнорируется
- нельзя: `rows.Close(); _ = tx.Rollback(ctx) без причины`
- надо: `проверить; осознанный пропуск — с комментарием почему`
- источник: [Go Code Review Comments — Handle Errors](https://go.dev/wiki/CodeReviewComments#handle-errors)
- проверка: `golangci-lint run` (errcheck)
- тяжесть: важно

### Сравнение ошибок через errors.Is / errors.As
- нельзя: `if err == sql.ErrNoRows; if err.Error() == "not found"`
- надо: `if errors.Is(err, pgx.ErrNoRows)`
- источник: [pkg.go.dev — errors](https://pkg.go.dev/errors)
- проверка: `golangci-lint run` (errorlint)
- тяжесть: важно

### Доменные ошибки — значения модуля, а не HTTP-коды
- нельзя: `сервис возвращает http.StatusConflict`
- надо: `var ErrDocumentLocked = errors.New(...); слой api переводит в HTTP-код`
- источник: [Google Go Style — Errors](https://google.github.io/styleguide/go/best-practices#error-handling)
- проверка: агент
- тяжесть: важно

### panic только для невозможного, не для бизнес-ошибок
- нельзя: `panic("invoice not found")`
- надо: `return ErrNotFound; panic — нарушение инварианта программы при старте`
- источник: [Effective Go — Panic](https://go.dev/doc/effective_go#panic)
- проверка: агент
- тяжесть: важно

## Context и конкурентность

### context.Context — первый параметр, не хранится в структуре
- нельзя: `type Service struct { ctx context.Context }; func Get(id int64, ctx context.Context)`
- надо: `func (s *Service) Get(ctx context.Context, id int64)`
- источник: [pkg.go.dev — context](https://pkg.go.dev/context)
- проверка: `golangci-lint run` (revive: context-as-argument, containedctx)
- тяжесть: важно

### Каждая горутина знает, как она закончится
- нельзя: `go worker() без отмены и ожидания`
- надо: `errgroup.WithContext; горутина выходит по ctx.Done()`
- источник: [Go Blog — Pipelines and cancellation](https://go.dev/blog/pipelines)
- проверка: агент + тесты с `-race`
- тяжесть: критично

### Тесты гоняются с детектором гонок
- нельзя: `go test ./...`
- надо: `go test -race ./...`
- источник: [Go — Data Race Detector](https://go.dev/doc/articles/race_detector)
- проверка: команда проверки содержит `-race`
- тяжесть: важно

## Данные и деньги

### Деньги — не float
- нельзя: `Amount float64`
- надо: `целые копейки int64 или decimal-тип; в БД numeric`
- источник: [PostgreSQL wiki — Don't Do This: money/float](https://wiki.postgresql.org/wiki/Don%27t_Do_This)
- проверка: агент (grep float по доменным типам сумм)
- тяжесть: критично

### SQL только с параметрами
- нельзя: `fmt.Sprintf("SELECT ... WHERE id = %s", id)`
- надо: `pool.Query(ctx, "SELECT ... WHERE id = $1", id)`
- источник: [OWASP — SQL Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html)
- проверка: `golangci-lint run` (gosec G201/G202)
- тяжесть: критично

### Транзакция открывается и закрывается в одном месте
- нельзя: `tx передаётся через полпроекта, Commit в другом пакете`
- надо: `сервис вызывает store.WithTx(ctx, func(tx) error {...}); defer Rollback`
- источник: [pgx — Transactions](https://pkg.go.dev/github.com/jackc/pgx/v5#hdr-Transactions)
- проверка: агент
- тяжесть: важно

## Тесты

### Табличные тесты для вариантов одной функции
- нельзя: `TestCalc1, TestCalc2, TestCalc3 с копипастой`
- надо: `tests := []struct{name string; in X; want Y}{...}; t.Run(tt.name, ...)`
- источник: [Go Wiki — TableDrivenTests](https://go.dev/wiki/TableDrivenTests)
- проверка: агент
- тяжесть: мелочь

### Адаптер БД тестируется на настоящем PostgreSQL
- нельзя: `мок pgx в тесте репозитория`
- надо: `интеграционный тест на временной базе (testcontainers / отдельная БД), пропуск в CI запрещён`
- источник: [Testcontainers for Go](https://golang.testcontainers.org/)
- проверка: агент + команда проверки
- тяжесть: важно

### Сообщение теста говорит, что получили и что ждали
- нельзя: `t.Error("wrong")`
- надо: `t.Errorf("Total() = %v, want %v", got, want)`
- источник: [Go Code Review Comments — Useful Test Failures](https://go.dev/wiki/CodeReviewComments#useful-test-failures)
- проверка: агент
- тяжесть: мелочь

## Логи и профилирование

### Структурные логи через log/slog
- нельзя: `log.Printf("user %s failed", u)`
- надо: `logger.ErrorContext(ctx, "invoice post failed", "invoice_id", id, "err", err)`
- источник: [Go Blog — Structured Logging with slog](https://go.dev/blog/slog)
- проверка: `golangci-lint run` (sloglint, forbidigo на log.Print*)
- тяжесть: важно

### Профилировщик подключён, но закрыт
- нельзя: `import _ "net/http/pprof" на публичном порту`
- надо: `pprof на отдельном localhost-порту за флагом; бенчмарки go test -bench для горячих путей`
- источник: [Go — Diagnostics](https://go.dev/doc/diagnostics)
- проверка: агент + `gosec` (G108)
- тяжесть: важно

## Линтер и инструменты

### Базовый набор golangci-lint включён и обязателен
- нельзя: `только go vet`
- надо: `govet, staticcheck, errcheck, errorlint, wrapcheck, gosec, revive, depguard, bodyclose, sqlclosecheck, gocritic, sloglint; gofumpt / goimports как форматтеры`
- источник: [golangci-lint — Linters](https://golangci-lint.run/docs/linters/)
- проверка: `golangci-lint run`
- тяжесть: важно

### Уязвимости зависимостей проверяются govulncheck
- нельзя: `зависимости без проверки`
- надо: `govulncheck ./... в команде проверки`
- источник: [Go — Vulnerability Management](https://go.dev/doc/security/vuln/)
- проверка: `govulncheck ./...`
- тяжесть: важно
