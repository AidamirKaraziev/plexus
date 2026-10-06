---
name: status
description: Show the state of the project on one dense screen — what is in progress, what comes next in the plan, hours and tokens spent per area. Reads only .claude/plan, .claude/ledger.jsonl and the per-epic handoffs; never the project code. Use when the user invokes /plexus:status, or says «где мы», «что осталось», «сколько потратили», «покажи прогресс», "where are we", "show progress".
version: 1.4.0
---

# Project status

Корень Плексуса — `${CLAUDE_PLUGIN_ROOT}`; в Codex эта строка не раскрывается — бери путь из строки контекста «корень Плексуса: …», а если её нет — папку на два уровня выше этого SKILL.md.

Budget for one call: **no more than 4k tokens**. That holds because the numbers
are computed by scripts and the model only lays them out on screen. No file
outside the list below is opened.

Speak Russian to the user throughout.

## Read exactly this

```
python3 ${CLAUDE_PLUGIN_ROOT}/lib/counters.py          # recount n/m in roadmap
python3 ${CLAUDE_PLUGIN_ROOT}/lib/streams.py           # epics Сейчас/Дальше + next stage, worktree, handoff, inbox
python3 ${CLAUDE_PLUGIN_ROOT}/lib/spend.py             # spend per area and per stage branch
python3 ${CLAUDE_PLUGIN_ROOT}/lib/vault.py             # knowledge base: folders + counts
cat .claude/plan/roadmap.md
git status --short | head -5
tail -3 .claude/ledger.jsonl
```

Do **not** open epic sub-plans — `counters.py` already returned the next stage.
The one exception is `/plexus:status E01`: then read that single sub-plan and show all
of its stages.

No `.claude/plan/roadmap.md` — say one line about `/plexus:aid-project-init` and stop.

## How to render it

One block of monospaced text, no markdown tables, no prose around it. A section
with nothing in it is dropped whole. Labels stay Russian.

```
ASTRA · feat/clean-chat-and-gifts · 8 сен

СЕЙЧАС   E01 Подарки  4/6  ████████████░░░░░░
         → S03 напоминание получателю через 24ч · back
         ⚠ общая область back с E02 · db-этапы открыты и в E02
         передача: в работе, 2026-09-11 · inbox 2

ДАЛЬШЕ   E02 Админка   0/5 · back
         E03 Профиль   0/4 · front

РАСХОД   back  ██████████░░░░░░░░  12.4 ч   8.1M  этапов 6
         front ████░░░░░░░░░░░░░░   4.9 ч   3.2M  этапов 3
         llm   ██░░░░░░░░░░░░░░░░   2.1 ч   4.4M  этапов 1
         ИТОГО                     19.4 ч  15.7M  этапов 10
         E01-S03 ████████░░░░░░░░░░   5.1 ч   3.9M  сессий 1
         E01-S02 ██████░░░░░░░░░░░░   3.8 ч   2.7M  сессий 1
         main    ████░░░░░░░░░░░░░░   2.6 ч   1.4M  сессий 3

ЗНАНИЕ   решения 4 · баги 2 · приёмы 1 · интеграции 0     всего 7

ХВОСТЫ   2 файла не закоммичены
         5 сессий вне учёта — этап не закрывали через /plexus:close
```

Screen rules:

- 20 lines maximum; over budget means cutting `ДАЛЬШЕ`, never `СЕЙЧАС`;
- `ЗНАНИЕ` is one line, folders and counts exactly as `vault.py` printed them.
  The guard refused — drop the block whole and say nothing about it, except a
  base that does not exist at all: that is one line under `ХВОСТЫ`,
  «базы знаний нет — `/plexus:aid-project-init`»;
- percentages and bars come from the scripts — never compute them yourself;
- the branch lines are the `ПО ВЕТКАМ` block of `spend.py`, verbatim, under
  `ИТОГО`; `main` is the sessions before streams and the main-checkout work.
  Over the 20-line budget — keep the top three branches and drop the rest;
- `⚠` is the line `streams.py` printed for that epic, verbatim — two streams
  «Сейчас» share an area on their next stages, or both hold open `db` stages.
  No line printed — no `⚠` on screen;
- `передача` is the status and date `streams.py` printed for that epic, plus
  `inbox N` when it printed one; never open `.claude/handoff/E0N.md` itself.
  No such line — the epic has no handoff yet, and the line is dropped;
- after the block, nothing. No conclusions, no advice, no «дай знать, если».

## When something does not add up

One line under `ХВОСТЫ`, without investigating: «план и ledger разошлись —
`/plexus:roadmap sync`». This skill cannot fix discrepancies and should not try.

## Never

- Never commit, never edit the plan, never tick a checkbox.
- Never work out a `⚠` yourself from areas or sub-plans — only what `streams.py` printed.
- Never read code, notes or specs — not for a single line of this screen. The
  knowledge block comes from `vault.py`, never from opening the vault itself.
- Never compute time or tokens yourself: numbers come only from `spend.py`.
- Do not add advice about what to do next. The next stage is already on screen.
