# @plexus-dsh/plexus — Плексус в DeepSeek Harness

Один пакет ставит в профиль DSH обе половины Плексуса:

- **скиллы** `/plexus-*` — провайдер реестра скиллов (`index.js`) отдаёт
  `skills/*/SKILL.md` из этого пакета; в профиль ничего не копируется;
- **работники** — пресеты `plexus-programmer` и `plexus-analyst`
  (бриф — `agents/programmer.md` и `agents/analyst.md` Плексуса).

Расход, кэш промпта, обрезка чтений и разведчик — не здесь: это плагины
plexus-dsh. Совместимость: DSH `0.2.2-rc.5` (`engines.dsh`).

## Установка

```bash
dsh plugin --profile <профиль> add @plexus-dsh/plexus
```

Нужны реестр скиллов и инструмент загрузки (`@deepseek-ai/dsh-skill`,
`@deepseek-ai/dsh-tool-skill`) и реестр пресетов — они есть в стандартном
наборе DSH (`dsh-base`, `dsh-web-app`).

## Имена команд

Имя скилла в DSH — только `kebab-case` (`:`, точка и косая черта недопустимы),
поэтому `/plexus:start` в DSH — `/plexus-start`, `/plexus:end` — `/plexus-end`
и так далее. В тексте скиллов команды пишутся как `/plexus:start` — так их
зовут в Claude Code, Codex и OpenCode.

Работники — пресеты `plexus-programmer` и `plexus-analyst` в выборе пресета
при создании сессии; модель выбирается там же (строка пресета её не пинит).

## Настройки

Строка `plexus-skills`: `prefix` — префикс имени скилла (по умолчанию
`plexus-`), `root` — свой каталог скиллов (пусто — `skills/` пакета).

## Сборка и проверки (в репозитории Плексуса)

Исходник — `доставка/dsh/`; пакет в git не лежит, его собирает сборщик:

```bash
node доставка/собрать.mjs dsh              # пакет в сборка/dsh/
node доставка/собрать.mjs dsh --проверить  # и проверки по собранной папке
cd сборка/dsh && npm pack                  # архив пакета
```

Проверки: `check-patch.mjs` — манифест и строки `cordis.patch.yml`,
`test-provider.mjs` — фронтматтер, каталог скиллов, тело скилла.
