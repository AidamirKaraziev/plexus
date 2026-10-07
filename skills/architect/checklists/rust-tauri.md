# Rust + Tauri 2 — десктопная оболочка

Уточняет `общее.md` для нативной стороны. Формат правила: заголовок — суть;
нельзя → надо; источник; проверка; тяжесть по умолчанию. Линтер — clippy,
форматтер — rustfmt.

## Роль и границы

### Rust — тонкая типизированная граница, бизнес-логики в нём нет
- нельзя: `расчёты и правила документов в #[tauri::command]`
- надо: `команда проверяет ввод, зовёт бэкенд, возвращает типизированный результат`
- источник: [Tauri — Calling Rust from the Frontend](https://v2.tauri.app/develop/calling-rust/)
- проверка: агент
- тяжесть: критично

### Команда — конкретный сценарий, не прокси
- нельзя: `#[tauri::command] fn http(method: String, url: String, body: String)`
- надо: `#[tauri::command] async fn post_invoice(id: i64) -> Result<PostResult, AppError>`
- источник: [Tauri — Security: Trust boundaries](https://v2.tauri.app/security/)
- проверка: агент
- тяжесть: критично

### Окна получают минимум прав через capabilities
- нельзя: `одна capability "main" с fs:default, shell:allow-execute для всех окон`
- надо: `файл на окно в src-tauri/capabilities/; только нужные permissions; scope путей`
- источник: [Tauri — Capabilities](https://v2.tauri.app/security/capabilities/)
- проверка: агент (разбор capabilities/*.json)
- тяжесть: критично

### Включена строгая CSP
- нельзя: `"csp": null; unsafe-eval; загрузка скриптов с внешних адресов`
- надо: `default-src 'self'; connect-src только нужные адреса`
- источник: [Tauri — Content Security Policy](https://v2.tauri.app/security/csp/)
- проверка: агент (tauri.conf.json)
- тяжесть: критично

### Токены не уходят в WebView
- нельзя: `команда возвращает access_token во фронт`
- надо: `токены хранит Rust (keyring / память), фронт получает только результат`
- источник: [OWASP ASVS — Session Management](https://owasp.org/www-project-application-security-verification-standard/)
- проверка: агент
- тяжесть: критично

## Ошибки

### Команды возвращают Result с сериализуемой ошибкой
- нельзя: `.unwrap() / .expect() в команде; Result<T, String>`
- надо: `enum AppError (thiserror) + impl Serialize; ? для проброса`
- источник: [Tauri — Error Handling in commands](https://v2.tauri.app/develop/calling-rust/#error-handling)
- проверка: `cargo clippy -- -D clippy::unwrap_used -D clippy::expect_used`
- тяжесть: важно

### Ошибка несёт контекст
- нельзя: `map_err(|_| AppError::Unknown)`
- надо: `map_err(|e| AppError::Backend { op: "post_invoice", source: e })`
- источник: [Rust API Guidelines — Error types are meaningful](https://rust-lang.github.io/api-guidelines/interoperability.html#error-types-are-meaningful-and-well-behaved-c-good-err)
- проверка: агент
- тяжесть: мелочь

### panic не используется для обычных ошибок
- нельзя: `panic!("no session")`
- надо: `Err(AppError::NoSession)`
- источник: [The Rust Book — To panic! or Not to panic!](https://doc.rust-lang.org/book/ch09-03-to-panic-or-not-to-panic.html)
- проверка: `cargo clippy` (clippy::panic)
- тяжесть: важно

## Код

### Именование по Rust API Guidelines
- нельзя: `fn GetInvoice(); struct invoice_dto`
- надо: `fn get_invoice(); struct InvoiceDto`
- источник: [Rust API Guidelines — Naming](https://rust-lang.github.io/api-guidelines/naming.html)
- проверка: `cargo clippy` (встроенные lint-ы именования)
- тяжесть: мелочь

### Типы ввода разобраны на границе
- нельзя: `команда принимает serde_json::Value и разбирает руками`
- надо: `#[derive(Deserialize)] struct PostInvoiceArgs { id: i64 }`
- источник: [Rust API Guidelines — Type safety](https://rust-lang.github.io/api-guidelines/type-safety.html)
- проверка: агент
- тяжесть: важно

### Долгие операции не блокируют главный поток
- нельзя: `синхронная команда делает сетевой запрос`
- надо: `async fn команда; тяжёлое — tokio::task::spawn_blocking`
- источник: [Tauri — Async commands](https://v2.tauri.app/develop/calling-rust/#async-commands)
- проверка: агент
- тяжесть: важно

### unsafe только с обоснованием
- нельзя: `unsafe { ... } без комментария`
- надо: `// SAFETY: почему инвариант соблюдён`
- источник: [Clippy — undocumented_unsafe_blocks](https://rust-lang.github.io/rust-clippy/master/#undocumented_unsafe_blocks)
- проверка: `cargo clippy -- -D clippy::undocumented_unsafe_blocks`
- тяжесть: важно

## Тесты и инструменты

### Команды тестируются без окна
- нельзя: `проверка только руками в запущенном приложении`
- надо: `логика команды в функции, тест через cargo test; IPC — tauri::test mock runtime`
- источник: [Tauri — Mock Tauri APIs / Tests](https://v2.tauri.app/develop/tests/)
- проверка: `cargo test`
- тяжесть: важно

### clippy без предупреждений, rustfmt обязателен
- нельзя: `предупреждения clippy копятся`
- надо: `cargo clippy --all-targets -- -D warnings; cargo fmt --check`
- источник: [Clippy — Usage](https://doc.rust-lang.org/clippy/usage.html)
- проверка: `cargo clippy --all-targets -- -D warnings && cargo fmt --check`
- тяжесть: важно

### Зависимости проверяются на уязвимости и лицензии
- нельзя: `Cargo.lock без проверки`
- надо: `cargo audit (RustSec) или cargo deny check в команде проверки`
- источник: [cargo-deny](https://embarkstudios.github.io/cargo-deny/)
- проверка: `cargo deny check`
- тяжесть: важно

### Обновления приложения подписаны
- нельзя: `updater без pubkey или по http`
- надо: `плагин updater с подписью; ключ вне репозитория`
- источник: [Tauri — Updater](https://v2.tauri.app/plugin/updater/)
- проверка: агент
- тяжесть: критично
