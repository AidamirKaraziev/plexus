---
name: note
description: Record one decision, one solved bug, one dead end or one reusable pattern in the project's vault/ — a single note plus a single line in проект.md, without walking the whole vault. Use when the user invokes /plexus:note, or says «запиши это решение», «зафиксируй, почему так сделали», «сохрани находку», "write this down".
version: 3.0.0
---

# One note into the knowledge base

Корень Плексуса — `${CLAUDE_PLUGIN_ROOT}`; в Codex эта строка не раскрывается — бери путь из строки контекста «корень Плексуса: …», а если её нет — папку на два уровня выше этого SKILL.md.

The cheap way to record knowledge: **one file, one line in `проект.md`**.
Nothing else is touched — not the plan, not the archive.

Where to write is decided by the guard, not by this skill: one call returns the
vault path and the project's own folder map, or refuses. Never search for the
vault by hand and never write outside the current repository.

The material comes from the current session. Do not re-derive it from code.

Speak Russian to the user throughout; the notes themselves are Russian.

## How to answer

Three blocks, in this order; an empty one is skipped. No prose paragraphs, no
preamble, no summing up afterwards. The headers stay Russian.

```
Сделал:
1. …            (one line = one thing, ≤ 12 words, verb first)

Нужно от тебя:
1. …            (a decision, or a ready-to-run command)

Дальше:
1. …            (my next step)
```

## Steps

1. Ask the guard:

   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/lib/vault.py
   ```

   It returns the vault path, the project name and the folder map. It refuses —
   show the refusal to the user word for word and stop. Do not look for a vault
   yourself, do not create one, do not write anywhere else.

2. Pick the kind: решение, баг, тупик или паттерн. The kind decides the folder
   (решение → `решения/`, баг → `баги/`, тупик → `тупики/`, паттерн →
   `приёмы/`); the format of each kind lives in the script, not here.

   Nothing fits — tell the user this does not amount to a note and write no
   file. A small fix with no fork in it is not knowledge. The script refuses
   (code 2) when the folder is missing from the map in `проект.md` — show the
   reason word for word and stop.

3. Find the epic and the circle in your own lock: the file
   `.claude/locks/<круг>.json` whose `кто` equals `git config user.name`. The
   file name is the `круг`; `цель` `E32-S02` gives the `эпик` `E32`. No lock —
   `круг: —`, and the epic is asked of the user or `—`.

4. Check there is no such note already: `ls <vault>/<папка>/`. Names are
   statements, so the listing is enough. A close note exists — **update it**
   instead of creating a second. Optionally
   `python3 ${CLAUDE_PLUGIN_ROOT}/lib/заметка.py --устаревшие <файл>` lists
   outdated candidates of the same area; show them and delete only after the
   user's «да».

5. Create the draft. The name is a statement, in Russian, spaces not dashes, no
   date:

   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/lib/заметка.py --новая <вид> --имя "<утверждение>" --эпик <E..> --круг "<имя>"
   ```

   It writes the template, the line in the note list of `проект.md` and
   `обновлён:`, and prints the path. Code 2 — the name is taken (update that
   note), Windows rejects it (rename), or the folder is not in the map: show
   the reason, fix, retry.

6. Fill every section of the draft from the session; the sections are the
   script's. Then check:

   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/lib/заметка.py --проверить <файл>
   ```

   Code 2 — a section is missing or empty: complete it and check again.

## Never

- Never commit.
- Never read the whole vault: only the folder being written into, and `проект.md`.
- Never touch `.claude/plan/` or the archive — that is `/plexus:roadmap`.
- Never bypass the guard: no `find`, no `~`, no `../`.
- Do not retell the diff: the vault holds what the code does not show.
- Do not invent hashes, test counts or checks that did not happen.
