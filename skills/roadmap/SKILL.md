---
name: roadmap
description: Plan and decompose work in .claude/plan — create the project plan from scratch, cut an epic into stages that each fit one session, reconcile the plan with reality, reorder priorities. Use when the user invokes /plexus:roadmap, /plexus:roadmap new, /plexus:roadmap E01, /plexus:roadmap sync, or says «декомпозируй», «нарежь задачу», «обнови план», «что у нас по плану», "break this down", "update the plan".
version: 1.4.0
---

# The plan: epics and stages

Корень Плексуса — `${CLAUDE_PLUGIN_ROOT}`; в Codex эта строка не раскрывается — бери путь из строки контекста «корень Плексуса: …», а если её нет — папку на два уровня выше этого SKILL.md.

The plan files are the single source of truth about what is left to do. By
default this skill reads neither the project code nor the knowledge vault.

```
.claude/plan/roadmap.md      epics. ~40 lines. Always read.
.claude/plan/E01-<name>.md   the epic's stages. Read only while working on it.
.claude/plan/archive/        closed epics. Gone from context.
```

**Ownership rule.** A stage exists in exactly one place — the epic's sub-plan.
`roadmap.md` knows nothing about stages; it keeps a `4/6` counter per epic.
Status flows upward only. Never create a stage in the roadmap and never
duplicate sub-plan text there.

Speak Russian to the user throughout. The plan files are written in Russian.

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

Numbers must be real. Do not expand — the user will ask. Anything meant to be
approved or copied (stages, plan lines) goes out as a block, not as a retelling.

## Modes

The mode comes from the argument. No argument — ask with `AskUserQuestion` (в Codex — `request_user_input`; недоступен — один вопрос текстом с вариантами), one
question, and read nothing until the answer arrives.

| Call | What it does |
|---|---|
| `/plexus:roadmap new` | create the plan from scratch |
| `/plexus:roadmap E01` or `/plexus:roadmap подарки` | cut, or re-cut, one epic |
| `/plexus:roadmap sync` | reconcile the plan with reality |
| `/plexus:roadmap move` | reorder priorities |

No `.claude/plan/roadmap.md` — mention `/plexus:init` and stop.

## `/plexus:roadmap new` — the plan from scratch

1. Source. Ask the guard — `python3 ${CLAUDE_PLUGIN_ROOT}/lib/vault.py`. It returned
   a vault, read **only** `проект.md` from it. It refused, run a conversation
   instead: ask what the next release must achieve and what stands in the way.
2. Collect epics. An epic is an outcome for the person using the product, not a
   layer of the system: «дарение без трения», not «доработать API подарков».
   Five to nine of them. More than that means some are really stages.
3. Sort them into `Сейчас` (one or two), `Дальше` (two or three), `Потом` (the rest).
4. Show the user the list as one block and wait for approval. Write the file
   only after a yes.
5. Do not create sub-plans. Only the epic being started gets cut — a plan six
   months deep goes stale before anyone needs it.

## `/plexus:roadmap E01` — cutting an epic

Write `.claude/plan/E01-<name>.md` in the format below.

```markdown
## E01 · Подарки — дарение без трения

Цель: пользователь дарит разбор в один тап, получатель открывает и втягивается.
Зачем: [[подарок это самый дешёвый канал привлечения]]

- [x] S01 витрина с ценами · back · 57313fa
- [x] S02 дарение в один тап · back+front · 0a6f47c
- [ ] S03 напоминание получателю через 24ч · back
      готово, когда: не открыл за 24ч → одно напоминание, повтора нет
- [ ] S04 аналитика конверсии подарков · back+docs
- [ ] ~~S05 промокоды~~ · снято: нет спроса
```

**One epic is one line in `roadmap.md`.** `counters.py` matches the `E0N` marker
and the ` · n/m · ` counter on the same line; a wrapped line silently stops being
recounted. Shorten the description rather than wrapping it.

Every open stage must carry: a number, a statement starting with a verb, area
tags, and a `готово, когда:` line with a checkable criterion. That line is what
`/plexus:end` reads when deciding whether the stage can be closed.

### The cutting rule — one stage equals one session

A stage passes only if all four hold:

1. it fits one line: verb plus object;
2. it has a checkable «готово, когда» — not «сделано красиво»;
3. it touches one layer; two is the ceiling, and then the tag reads `back+front`;
   a stage with a migration carries `db` — `streams.py` warns when two streams
   hold open `db` stages at once;
4. it closes with one meaningful commit.

It does not pass — **do not write it down**. Show the user which condition fails
and propose the cut. Under five minutes of work — glue it onto a neighbouring
stage. This refusal is the point of the skill: a plain to-do list needs no agent.

### Order of stages

First goes the stage that removes uncertainty or unblocks the others. Nice but
optional goes last. A stage depending on another ends with `после S02`.

## `/plexus:roadmap sync` — reconciling with reality

Read: every sub-plan, `.claude/ledger.jsonl`, `git log --oneline -30`. Check four
things and propose exactly one edit per finding:

- an epic with every stage ticked → move to `## Закрыто`, file into `archive/`;
- a stage ticked with no ledger row, or the reverse → show the discrepancy;
- an epic sitting in `Сейчас` with no movement for over two weeks → ask if it is
  still alive;
- commits in git that belong to no stage → ask where they go.

Apply edits **surgically**. Never rewrite the plan wholesale: the history of
priorities lives in git, and its value is that the changes are visible.

## `/plexus:roadmap move`

Move epics between `Сейчас` / `Дальше` / `Потом`. Touch nothing else. If the
user moves an epic into `Сейчас` when two are already there, say so and ask
which one leaves.

## Never

- Never commit.
- Never write rationale or decision history into the plan — only a `[[note]]`
  link. The why belongs in the knowledge vault: that is `/plexus:note`.
- Never read project code to "clarify" the plan.
- Never create stages in `roadmap.md`, and never edit the `n/m` counters by hand.
- Never cut epics in advance.
