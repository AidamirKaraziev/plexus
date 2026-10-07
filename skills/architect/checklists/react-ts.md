# React + TypeScript — фронтенд

Уточняет `общее.md` для фронта. Формат правила: заголовок — суть;
нельзя → надо; источник; проверка; тяжесть по умолчанию. Линтер — ESLint 9+
flat config (`eslint.config.js`) с typescript-eslint.

## Структура и границы

### Код фронта разложен по фичам, зеркально модулям бэкенда
- нельзя: `src/components/, src/hooks/, src/api/ на весь проект`
- надо: `src/features/<модуль>/{ui,model,api}; src/shared/{ui,lib}; src/app/ — сборка`
- источник: [Feature-Sliced Design — Overview](https://feature-sliced.design/docs/get-started/overview)
- проверка: агент
- тяжесть: важно

### Фича не импортирует внутренности другой фичи
- нельзя: `import { calc } from "@/features/payroll/model/calc"` из features/budgeting
- надо: `только через публичный index.ts фичи или через shared`
- источник: [eslint-plugin-boundaries](https://github.com/javierbrea/eslint-plugin-boundaries)
- проверка: `eslint .` (eslint-plugin-boundaries)
- тяжесть: критично

### Бизнес-логики во фронте нет
- нельзя: `расчёт сумм, проверка прав, правила проводок в компоненте`
- надо: `фронт показывает и собирает ввод; правила — в бэкенде, фронт получает результат`
- источник: `общее.md` — модуль-вертикаль, логика у владельца данных
- проверка: агент
- тяжесть: критично

## Типы

### TypeScript в строгом режиме
- нельзя: `"strict": false; noUncheckedIndexedAccess выключен`
- надо: `"strict": true, "noUncheckedIndexedAccess": true, "exactOptionalPropertyTypes": true`
- источник: [TypeScript — tsconfig strict](https://www.typescriptlang.org/tsconfig/#strict)
- проверка: `tsc --noEmit`
- тяжесть: важно

### Никакого any и непроверенного as
- нельзя: `const data: any = await res.json(); user as User`
- надо: `unknown + разбор схемой (zod) или тип из сгенерированного API-клиента`
- источник: [typescript-eslint — no-explicit-any](https://typescript-eslint.io/rules/no-explicit-any)
- проверка: `eslint .` (no-explicit-any, no-unsafe-*)
- тяжесть: важно

### Типы API генерируются из контракта, не пишутся руками
- нельзя: `interface Invoice { ... } переписан вручную с бэкенда`
- надо: `типы из OpenAPI (openapi-typescript); контракт — единственный источник`
- источник: [openapi-typescript](https://openapi-ts.dev/)
- проверка: генерация в команде проверки + `git diff --exit-code`
- тяжесть: важно

### Состояния описаны размеченным объединением
- нельзя: `isLoading, isError, data — три независимых флага`
- надо: `type State = {status:"loading"} | {status:"error"; error} | {status:"ok"; data}`
- источник: [TypeScript Handbook — Discriminated Unions](https://www.typescriptlang.org/docs/handbook/2/narrowing.html#discriminated-unions)
- проверка: агент
- тяжесть: мелочь

## React

### Правила хуков соблюдаются
- нельзя: `хук внутри if; пропущенная зависимость useEffect`
- надо: `хуки на верхнем уровне; зависимости полные`
- источник: [React — Rules of Hooks](https://react.dev/reference/rules/rules-of-hooks)
- проверка: `eslint .` (eslint-plugin-react-hooks, flat recommended)
- тяжесть: важно

### Effect не используется для вычислений и событий
- нельзя: `useEffect(() => setTotal(a + b), [a, b])`
- надо: `const total = a + b; реакция на клик — в обработчике`
- источник: [React — You Might Not Need an Effect](https://react.dev/learn/you-might-not-need-an-effect)
- проверка: агент
- тяжесть: важно

### Серверные данные — через библиотеку запросов, не useEffect + fetch
- нельзя: `useEffect(() => { fetch(...).then(setData) }, [])`
- надо: `useQuery({ queryKey: ["invoice", id], queryFn })` — кэш, отмена, повтор
- источник: [React — Fetching data with Effects (недостатки)](https://react.dev/reference/react/useEffect#fetching-data-with-effects)
- проверка: агент
- тяжесть: важно

### Компонент чистый: тот же ввод — тот же вывод
- нельзя: `мутация пропсов, Math.random() / Date.now() в рендере`
- надо: `побочные эффекты в обработчиках и эффектах`
- источник: [React — Components and Hooks must be pure](https://react.dev/reference/rules/components-and-hooks-must-be-pure)
- проверка: `eslint .` (react-hooks recommended-latest с правилами компилятора)
- тяжесть: важно

### Ключ списка — стабильный id, не индекс
- нельзя: `items.map((x, i) => <Row key={i} />)`
- надо: `<Row key={x.id} />`
- источник: [React — Rendering Lists: keys](https://react.dev/learn/rendering-lists#keeping-list-items-in-order-with-key)
- проверка: `eslint .` (react/no-array-index-key)
- тяжесть: мелочь

### Состояние живёт как можно ниже и не дублируется
- нельзя: `глобальный стор для поля формы; копия пропса в state`
- надо: `состояние в ближайшем общем родителе; производное — вычислять`
- источник: [React — Choosing the State Structure](https://react.dev/learn/choosing-the-state-structure)
- проверка: агент
- тяжесть: мелочь

### Экраны построены из UI-кита проекта
- нельзя: `своя кнопка и таблица в каждой фиче`
- надо: `компоненты из src/shared/ui или принятой библиотеки; новый общий — через ревью`
- источник: эталонный модуль проекта
- проверка: агент
- тяжесть: важно

## Безопасность фронта

### HTML не вставляется из данных
- нельзя: `<div dangerouslySetInnerHTML={{ __html: comment }} />`
- надо: `рендерить текст; если HTML нужен — санитайзер (DOMPurify)`
- источник: [React — dangerouslySetInnerHTML](https://react.dev/reference/react-dom/components/common#dangerously-setting-the-inner-html)
- проверка: `eslint .` (react/no-danger)
- тяжесть: критично

### Токены и секреты не хранятся в браузерном хранилище
- нельзя: `localStorage.setItem("token", t)`
- надо: `сессия держится нативной стороной / httpOnly-cookie; фронт токена не видит`
- источник: [OWASP — HTML5 Security: Local Storage](https://cheatsheetseries.owasp.org/cheatsheets/HTML5_Security_Cheat_Sheet.html#local-storage)
- проверка: агент (grep localStorage/sessionStorage)
- тяжесть: критично

## Тесты

### Компонент тестируется как пользователь его видит
- нельзя: `проверка внутреннего state, поиск по className`
- надо: `screen.getByRole("button", { name: "Провести" })` и userEvent
- источник: [Testing Library — Guiding Principles](https://testing-library.com/docs/guiding-principles)
- проверка: агент
- тяжесть: важно

### Тесты и проверка типов — в команде проверки
- нельзя: `vitest только локально по желанию`
- надо: `tsc --noEmit && eslint . && vitest run`
- источник: [Vitest — CLI](https://vitest.dev/guide/cli)
- проверка: команда проверки
- тяжесть: важно

## Инструменты

### Форматирует Prettier, стиль не спорится
- нельзя: `правила отступов в ESLint и в ревью`
- надо: `prettier --check в команде проверки; eslint-config-prettier снимает конфликт`
- источник: [Prettier — Integrating with Linters](https://prettier.io/docs/integrating-with-linters)
- проверка: `prettier --check .`
- тяжесть: мелочь

### Импорты по алиасу, без лестниц ../../..
- нельзя: `import x from "../../../shared/lib/money"`
- надо: `import x from "@/shared/lib/money"`
- источник: [TypeScript — paths](https://www.typescriptlang.org/tsconfig/#paths)
- проверка: `eslint .` (no-restricted-imports на "../../*")
- тяжесть: мелочь
