#!/usr/bin/env python3
"""Дорожки: эпики из «Сейчас» и «Дальше» одним экраном.

Для каждого эпика — n/m и следующий этап (как counters.py), плюс что у него
есть по дорожке: worktree, передача (handoff/E0N.md), входящие (inbox/E0N.md).
⚠ у эпиков «Сейчас», чьи ближайшие этапы делят область или оба несут `db`.
Roadmap не трогает — счётчики пересчитывает counters.py.

    python3 ${CLAUDE_PLUGIN_ROOT}/lib/streams.py [--repo .]
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/streams.py --json   # для picker'а в этап-старт
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from counters import EPIC, TODO, stages  # noqa: E402

SECTIONS = {"## Сейчас": "Сейчас", "## Дальше": "Дальше"}
FIELD = re.compile(r"^(статус|дата|ветка):\s*(.+?)\s*$")
ITEM = re.compile(r"^\s*-\s+\S")


def frontmatter(path: Path) -> dict:
    """`статус`, `дата` и `ветка` из шапки передачи. Шапки нет — пусто."""
    out = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return out
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = FIELD.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def inbox_items(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for l in path.read_text(encoding="utf-8").splitlines() if ITEM.match(l))


def open_areas(path: Path) -> list[set[str]]:
    """Теги каждого открытого этапа подплана, по порядку: `S03 имя · lib+skills · после S02` → {lib, skills}."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if "~~" in line or not TODO.match(line):
            continue
        parts = [x.strip() for x in line.split("]", 1)[1].split(" · ")]
        out.append(set(parts[1].split("+")) if len(parts) > 1 else set())
    return out


def warn(items: list[dict]) -> None:
    """⚠ внутри «Сейчас»: общая область у ближайших этапов, или db-этапы открыты в двух дорожках."""
    now = [e for e in items if e["section"] == "Сейчас" and e["total"] is not None]
    for e in now:
        reasons = []
        for o in now:
            if o is e:
                continue
            common = set(e["next_area"].split("+")) & set(o["next_area"].split("+")) - {""}
            if common:
                reasons.append(f"общая область {'+'.join(sorted(common))} с {o['id']}")
            if e["db_open"] and o["db_open"]:
                reasons.append(f"db-этапы открыты и в {o['id']}")
        e["warn"] = " · ".join(reasons)


def branch_exists(repo: Path, branch: str) -> bool:
    return subprocess.run(["git", "rev-parse", "--verify", "-q", branch], cwd=repo,
                          capture_output=True).returncode == 0


def epics(repo: Path):
    plan = repo / ".claude" / "plan"
    dot = repo / ".claude"
    section = None
    for line in (plan / "roadmap.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = SECTIONS.get(line.strip())
            continue
        m = EPIC.search(line)
        if not section or not m:
            continue
        eid = m.group(1)
        name = line.split("**")[1]
        area = line.rsplit(" · ", 1)[1].strip() if " · " in line else ""
        wt = dot / "worktrees" / eid
        files = sorted(plan.glob(f"{eid}-*.md"))
        if files and (wt / ".claude" / "plan" / files[0].name).exists():  # дорожка свежее main: чекбоксы тикают там
            files = [wt / ".claude" / "plan" / files[0].name]
        done, total, nxt = stages(files[0]) if files else (None, None, None)
        areas = open_areas(files[0]) if files else []
        handoff = dot / "handoff" / f"{eid}.md"
        if (wt / ".claude" / "handoff" / f"{eid}.md").exists():  # и передача пишется там же
            handoff = wt / ".claude" / "handoff" / f"{eid}.md"
        fm = frontmatter(handoff) if handoff.exists() else None
        branch = fm.get("ветка", "") if fm else ""
        unmerged = ""
        if fm and fm.get("статус") == "закрыт" and branch.startswith(eid + "-") and branch_exists(repo, branch):
            unmerged = branch
        yield {
            "id": eid,
            "name": name,
            "area": area,
            "section": section,
            "done": done,
            "total": total,
            "next": nxt,
            "next_area": "+".join(sorted(areas[0])) if areas else "",
            "db_open": any("db" in a for a in areas),
            "warn": "",
            "worktree": wt.is_dir(),
            "handoff": {"status": fm.get("статус", "?"), "date": fm.get("дата", "?"), "branch": branch} if fm is not None else None,
            "unmerged": unmerged,
            "inbox": inbox_items(dot / "inbox" / f"{eid}.md"),
        }


def render(items) -> str:
    out, current = [], None
    for e in items:
        if e["section"] != current:
            current = e["section"]
            out.append(current.upper())
        mark = "⚠ " if e["warn"] else ""
        if e["total"] is None:
            head = f"  {mark}{e['name']}  —/—  подплана нет"
        else:
            tail = f"→ {e['next']}" if e["next"] else "→ всё закрыто"
            head = f"  {mark}{e['name']}  {e['done']}/{e['total']}  {tail}"
        if e["area"] and not e["next"]:  # у этапа своя область, эпика хватит без подплана
            head += f" · {e['area']}"
        out.append(head)
        flags = []
        if e["warn"]:
            flags.append(f"⚠ {e['warn']}")
        if e["worktree"]:
            flags.append("worktree ✓")
        if e["handoff"]:
            flags.append(f"передача: {e['handoff']['status']} {e['handoff']['date']}")
        if e["unmerged"]:
            flags.append(f"⏳ {e['unmerged']} закрыт, не влит")
        if e["inbox"]:
            flags.append(f"inbox {e['inbox']}")
        if flags:
            out.append("      " + " · ".join(flags))
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    if not (repo / ".claude" / "plan" / "roadmap.md").exists():
        print("нет .claude/plan/roadmap.md — запусти /aid-project-init")
        return 1
    items = list(epics(repo))
    warn(items)
    print(json.dumps(items, ensure_ascii=False, indent=1) if args.json else render(items))
    return 0


if __name__ == "__main__":
    sys.exit(main())
