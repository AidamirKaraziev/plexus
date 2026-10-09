---
name: commit-message
description: Compose the commit message for the current working-copy changes, in this repository's own style, and hand the text to the user to copy. Commits nothing. Use when the user invokes /plexus:commit-message, or says «напиши описание коммита», «текст коммита», "write a commit message".
version: 2.1.0
---

# Commit message

Корень Плексуса — `${CLAUDE_PLUGIN_ROOT}`; в Codex эта строка не раскрывается — бери путь из строки контекста «корень Плексуса: …», а если её нет — папку на два уровня выше этого SKILL.md.

The job: look at what changed and produce the **finished text** of a commit
message. **Never run `git add`, `git commit` or `git push`** — what enters
history, and when, is the user's decision. They copy the text by hand and commit
from the IDE, so the answer must contain no git commands and no Run-button blocks.

The message itself is written in Russian.

`/plexus:end` calls this skill as its last step, so the user gets the commit
text without a second command; the rules are the same either way.

## What to do

1. Get the picture of the changes:

   ```
   git status --short
   git diff --stat HEAD
   git diff HEAD
   ```

   New files do not appear in `git diff HEAD` — read them separately
   (`git status --short` lists them as `??`).

   If the user passed an argument (`/plexus:commit-message staged`, a filename, a
   range) — stay within that slice. Without an argument, take everything
   uncommitted.

2. Nothing changed — say so and stop.

3. Look up this repository's vocabulary, unless the session already knows it:

   ```
   git log --oneline -20
   ```

   That is where the **scopes** (what goes in parentheses) and this project's
   names for its modules come from. The message format itself is always the one
   below, even if the project's older history was written differently — the one
   exception being a commit format prescribed in the project's `CLAUDE.md`,
   which wins.

4. **Always one message for the whole slice.** Even when the edits are unrelated,
   do not propose splitting them into several commits — the logical division of
   history is the user's job. Unrelated pieces simply become separate bullets.

5. Do not retell the diff line by line. Work out **what was done** and why: which
   human or system problem the change closes. If that was established earlier in
   this session, use what is already known rather than re-deriving it from code.

6. Output the text in a single fenced block with no language tag, so it can be
   copied whole. Nothing else goes in the answer — no preamble, no explanation
   afterwards, no commands.

## The ledger needs no attention here

Commit hashes are appended to `.claude/ledger.jsonl` by the `post-commit` git
hook (installed by `/plexus:init`), the moment the user commits. This skill never
writes to the ledger and stays what it was: fast.

## Format

```
тип(область): суть одной строкой

- сделанное дело, глаголом
- сделанное дело, глаголом
- сделанное дело, глаголом

Миграция 026 · env FOO_BAR · 969 тестов · ручной шаг: перезапуск docker

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

**Subject line:** 72 characters or fewer, the type in Latin, the scope and the
gist in Russian, lowercase after the colon, no full stop. Types in use: `feat`,
`fix`, `ui`, `docs`, `refactor`, `test`, `chore`. Scopes are Russian and stated
in product terms, taken from this repository's vocabulary (step 3): `профиль`,
`рассылки`, `логи`, `метрики`, `миграции`, `тесты`, `vault` and the like. When
the slice holds several unrelated edits, the subject names the main one and the
rest live in the bullets.

**The body is points, not prose.** It has to be readable at a glance:

- 3–7 bullets, marker `-`, a blank line between subject and list;
- each bullet is **a thing done**, not a problem: «uv ставится колесом с PyPI»,
  «пол профиля добавлен в payload», not «uv не ставился с ghcr»;
- why it was done that way goes as a short tail after a dash in the same bullet,
  when it is not obvious: «— зависимости от ghcr.io в сборке нет»;
- one bullet = one thought, at most 2 lines of 76 characters. It does not fit —
  then it is two bullets;
- order: first what the person will see in the product, then internal decisions,
  then holes closed along the way.

**The service line** is the last line before the trailer, separated by a blank
line, parts joined with `·`. It collects what matters at deploy time and must not
be missed:

- the Alembic migration number and what it applies;
- a new environment variable;
- a manual step after deploy;
- what it was verified against (a live database, a real account, a test count),
  if it was verified.

None of that applies — write `Миграций нет`, so the line is always present and
the eye finds it without reading.

Add the `Co-Authored-By` trailer only if the change was made by the agent. If the
user wrote the code themselves — remove it.

## Never

- Never write «обновлены файлы», «различные улучшения», «рефакторинг кода» — such
  a subject carries no information.
- Do not list filenames and function names instead of meaning. A module name
  belongs there when the decision cannot be explained without it
  (`users_crud.clear_birth_time`).
- Do not expand a bullet into a paragraph of prose: this skill exists so that the
  meaning of a commit reads at a glance.
- Do not invent a check that did not happen.
- Do not add links to issues or PRs if this repository's history has none.
- Do not take scopes and terms from another project — only from this one.
- Never give a `git commit` command and never offer to commit.

## Example

```
feat(спроси астрид): черты партнёра и повторяющийся сценарий

- добавлены два платных вопроса в теме «Любовь» по 1 ⭐: «Черты моего
  судьбоносного партнёра?» и «Почему я снова и снова обжигаюсь?»
- типаж (8 штук) и петля (7 штук) считаются Python по порогам, модель их
  только объясняет; пороги подобраны на 250 случайных картах
- пол профиля добавлен в payload обоих продуктов — раньше не доходил до
  модели, мужчина мог получить разбор в женском роде
- card_caption убран под try: исключение после списания звёзд оставляло
  человека без ответа и без возврата
- тест изоляции переписан на обход по SPECS + проверка полноты контракта

Миграции 026 и 027 · 969 тестов · оба промпта прогнаны на DeepSeek

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

The example is about the shape of the message, not about its subject area: its
terms come from another project and should not be reused.
