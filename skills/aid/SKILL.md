---
name: aid
description: Cheat sheet for the user's own skills — what each command does, when to call it and in what order. Use when the user invokes /plexus:aid, or says «какие у меня команды», «что делает каждый скилл», «напомни список команд», «шпаргалка по скиллам», "list my commands", "what skills do I have".
version: 1.8.0
---

# Cheat sheet for my own commands

Корень Плексуса — `${CLAUDE_PLUGIN_ROOT}`; в Codex эта строка не раскрывается — бери путь из строки контекста «корень Плексуса: …», а если её нет — папку на два уровня выше этого SKILL.md.

Read the version from `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json` (field
`version`) — one read, the only tool call allowed. The source comes from the
`${CLAUDE_PLUGIN_ROOT}` path itself, no tool call: path contains
`/plugins/cache/plexus-beta/` → «бета»; `/plugins/cache/plexus/` → «релиз»;
any other path (no `plugins/cache`) → «черновик». Then print the block below
**verbatim**, with «Плексус <версия> · <источник>» as its first line, and stop.
No other files, no line of prose before or after it — one message, one screen.
The version is never written in this text: it is always read from `plugin.json`.

```
Плексус <версия> · <источник>

МОИ КОМАНДЫ

ХОД РАБОТЫ   /plexus:start → работа делают работники → /plexus:close → коммит руками
             две двери; внутри них система сама зовёт нужный скилл

СЕССИЯ    /plexus:start   вход: состояние проекта, один вопрос вариантами, передача работы;
                          плана нет — заведёт, круг открыт — продолжит молча
          /plexus:close   выход: проверки по файлу круга, итог с расходом, знание,
                          уборка дорожек, текст коммита; сам не коммитит
          /plexus:commit-message  текст коммита отдельно, посреди работы; сам не коммитит

КРУГ      /plexus:task    собрать задание: вопросы до 100 %, файл в круги/ базы
                          с задачами «готово, когда» и командой проверки;
                          после «утверждаю» раздаёт задачи работникам и ведёт экран
          /plexus:analyst разбор сессий на паттерны, предложения правок скиллам

ПЛАН      /plexus:roadmap        создать план, нарезать эпик на этапы
          /plexus:roadmap sync   свести план с ledger и git
          /plexus:status         что в работе, что дальше, расход по областям

ЗНАНИЕ    /plexus:note    одна заметка в vault и строка в проект.md
          /plexus:map     карта базы: какие папки, что куда, сколько заметок

НАСТРОЙКА /plexus:aid-project-init  завести проект: база знаний, план, ledger, хук
          /plexus:update            обновить Плексус до последней версии, потом перезапуск Claude
          /plexus:aid               этот экран

ЧАСТОТА   каждую сессию: start, close, коммит руками
          раз в неделю: roadmap sync
```

The screen is hand-written, not generated: a new skill in the plugin's `skills/`
means one more line here, added by hand when the skill is added.

## When asked about one command

`/plexus:aid close` or «что делает close» — then the block above is not
printed at all. Read that one `SKILL.md` (`${CLAUDE_PLUGIN_ROOT}/skills/<имя>/SKILL.md`) and
answer in at most 12 lines: what it does, when to call it, what it touches,
what it deliberately does not do. No advice afterwards.

## Never

- Never edit a skill, the plan, the ledger or the vault; this screen is read-only.
- Never run a command to build the screen — it is already written above; the only read is the version in `plugin.json`.
- Never list built-in or plugin skills; these are the user's own commands only.
- Do not offer to run any of the listed commands. The user reads and picks.
