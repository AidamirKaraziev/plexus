---
name: note
description: Record one decision, one solved bug or one reusable pattern in the project's vault/ — a single note plus a single line in проект.md, without walking the whole vault. Use when the user invokes /plexus:note, or says «запиши это решение», «зафиксируй, почему так сделали», «сохрани находку», "write this down".
version: 2.0.0
---

# One note into the knowledge base

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

2. Pick the folder from the map the guard returned. The map is this project's
   own — the folders are named by the person who set it up, so read the
   description after the dash rather than guessing by name.

   No folder fits — tell the user this does not amount to a note and write no
   file. A small fix with no fork in it is not knowledge.

3. Check there is no such note already: `ls <vault>/<папка>/`. Names are
   statements, so the listing is enough to tell whether to open one. A close
   note exists — **update it** instead of creating a second.

4. Write the file. The name is a statement, in Russian, spaces not dashes, no
   date: `подарочная ссылка живёт в экране а не карточкой в чате.md`.

5. Append one line to the note list in `<vault>/проект.md` and bump `обновлён:`
   in its frontmatter. A note missing from that file does not exist for the
   next session.

6. Check every `[[link]]` in the new note against existing filenames. A link to
   a note not written yet is fine — say so in one line.

## Note format

Frontmatter `tags` + `date`, first tag is the folder name. The H1 repeats the
statement from the filename. Wiki-links to related notes at the end. Prose,
lines under 79 characters, Russian.

Three kinds of note carry the whole system and are worth writing in a fixed
shape whatever the folders are called in this project:

- **решения** — the H1 is the decision itself. Sections: **Почему**, **Цена
  решения** (what it cost), **Когда вернёмся** (the condition for revisiting).
  Name the rejected alternative outright.
- **баги** — the H1 is the bug as a past-tense statement. The symptom, the
  real cause, **Как починили**, then **Урок** — what to check next time.
- **приёмы** — the H1 is the technique as a statement. A short code fragment,
  **Почему так**, then **Что важно не забыть** — the traps invisible in the code.

## Never

- Never commit.
- Never read the whole vault: only the folder being written into, and `проект.md`.
- Never touch `.claude/plan/` or the archive — that is `/plexus:roadmap`.
- Never bypass the guard: no `find`, no `~`, no `../`.
- Do not retell the diff: the vault holds what the code does not show.
- Do not invent hashes, test counts or checks that did not happen.
