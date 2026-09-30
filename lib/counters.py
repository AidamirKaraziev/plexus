#!/usr/bin/env python3
"""Пересчитать счётчики n/m в roadmap.md по чекбоксам подпланов.

Строка эпика в roadmap.md обязана содержать « · N/M · » — заменяются только цифры.
Печатает сводку: id, имя, готово/всего, следующий незакрытый этап.

    python3 ${CLAUDE_PLUGIN_ROOT}/lib/counters.py [--repo .]
"""
import argparse
import re
import sys
from pathlib import Path

EPIC = re.compile(r"\*\*(E\d+)")
COUNT = re.compile(r" · \d+/\d+ · ")
DONE = re.compile(r"^\s*-\s*\[x\]", re.I)
TODO = re.compile(r"^\s*-\s*\[ \]")


def stages(path: Path):
    done, todo, nxt = 0, 0, None
    for line in path.read_text(encoding="utf-8").splitlines():
        if "~~" in line:  # снятый этап в счёт не идёт
            continue
        if DONE.match(line):
            done += 1
        elif TODO.match(line):
            todo += 1
            if nxt is None:
                nxt = line.split("]", 1)[1].strip()
    return done, done + todo, nxt


def stage_names(path: Path) -> dict[str, str]:
    """`S03` → «имя этапа» из подплана (без области и «после»); снятые этапы тоже, по ним есть ссылки."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not (DONE.match(line) or TODO.match(line)):
            continue
        body = line.split("]", 1)[1].replace("~~", "").strip()
        sid, _, rest = body.partition(" ")
        if sid.startswith("S"):
            out[sid] = rest.split(" · ")[0].strip()
    return out


def stage_title(repo: Path, eid: str, stage: str) -> str:
    """`E03-S03` → «имя»; подплана или этапа нет → пустая строка."""
    files = sorted((repo / ".claude" / "plan").glob(f"{eid}-*.md"))
    return stage_names(files[0]).get(stage, "") if files else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()
    plan = Path(args.repo).resolve() / ".claude" / "plan"
    roadmap = plan / "roadmap.md"
    if not roadmap.exists():
        print("нет .claude/plan/roadmap.md — запусти /aid-project-init")
        return 1

    out, changed, closed = [], False, False
    for line in roadmap.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            closed = line.strip() == "## Закрыто"
        m = EPIC.search(line)
        if not m or closed:  # закрытый эпик: подплан в archive/, счётчик уже финальный — не шумим
            out.append(line)
            continue
        eid = m.group(1)
        files = sorted(plan.glob(f"{eid}-*.md"))
        if not files:
            print(f"{eid}  —/—  подплана нет")
            out.append(line)
            continue
        done, total, nxt = stages(files[0])
        new = COUNT.sub(f" · {done}/{total} · ", line)
        changed = changed or new != line
        out.append(new)
        name = line.split("**")[1] if "**" in line else eid
        print(f"{name}  {done}/{total}" + (f"  → {nxt}" if nxt else "  → всё закрыто"))

    if changed:
        roadmap.write_text("\n".join(out) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
