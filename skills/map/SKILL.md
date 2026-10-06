---
name: map
description: Show the project's knowledge base on one screen — which folders exist, what belongs in each, how many notes are in them and what was written last. Reads only the guard's output and проект.md, never the notes themselves. Use when the user invokes /plexus:map, or says «покажи базу знаний», «какая у нас структура», «куда это класть», «что уже записано», "show the knowledge base", "what folders do we have".
version: 1.0.0
---

# Карта базы знаний

Корень Плексуса — `${CLAUDE_PLUGIN_ROOT}`; в Codex эта строка не раскрывается — бери путь из строки контекста «корень Плексуса: …», а если её нет — папку на два уровня выше этого SKILL.md.

Budget for one call: **no more than 2k tokens**. That holds because the guard
returns the folders and the counts already computed, and no note is ever opened.

Speak Russian to the user throughout.

## Read exactly this

```
python3 ${CLAUDE_PLUGIN_ROOT}/lib/vault.py
head -12 $(python3 ${CLAUDE_PLUGIN_ROOT}/lib/vault.py --path)/проект.md
```

The guard refused — show the refusal word for word and stop. There is nothing
to draw and nothing to fix here.

Nothing else is opened. Not a note, not `карта.md` (the guard already parsed
it), not the plan.

## How to render it

One block of monospaced text, no markdown tables, no prose around it. Labels
stay Russian. 16 lines maximum.

```
ASTRA · база знаний · 7 заметок

  решения/     4   выбрали вариант, есть отклонённая альтернатива
  баги/        2   причина оказалась не там, где симптом
  приёмы/      1   техника, которая повторится в других местах
  интеграции/  0   как устроена связь с внешним сервисом

  вне карты: архив

КУДА ПИСАТЬ   /plexus:note — сам выберет папку по этой карте
```

Screen rules:

- folder names, counts and descriptions come from `vault.py` verbatim —
  never reword a description and never recount;
- a description longer than the column is cut at the word, not wrapped: the
  screen must stay one line per folder;
- `вне карты` appears only when the guard printed it;
- an empty folder still gets its line — a zero is information: nobody has had
  anything to put there yet;
- the first line takes the project name from the guard and the total from the
  sum of the counts.

## When the user asks «куда это класть»

Then the screen is not printed. Name one folder, in one line, quoting the
description from the map that made it the answer. Nothing fits — say that
plainly: it is not a note. Write nothing either way — that is `/plexus:note`.

## Never

- Never commit, never create folders, never edit `карта.md` or `проект.md`.
- Never open a note to «уточнить» a count or a description.
- Never advise reorganising the base. The map shows what is; changing it is the
  user's call, by hand, in `карта.md`.
