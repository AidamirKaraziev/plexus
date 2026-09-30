#!/usr/bin/env python3
"""Расход по областям и по веткам: читает .claude/ledger.jsonl и транскрипты Claude Code.

Модель этот файл не парсит — запускает и печатает готовую таблицу.
Транскрипты — папки ~/.claude/projects/<slug> для main-checkout и каждого
.claude/worktrees/E0N (slug: всё не-буквенно-цифровое → «-»). Ветка — из
ledger.branch, строки без него идут в «main».

    python3 ${CLAUDE_PLUGIN_ROOT}/lib/spend.py            # всё время
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/spend.py --days 7   # за неделю
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/spend.py --json     # машиночитаемо
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import subprocess


def main_root(start: Path) -> Path:
    """Корень main-checkout'а — первая строка `git worktree list`, даже изнутри дорожки."""
    r = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=start, capture_output=True, text=True)
    return Path(r.stdout.splitlines()[0].split(" ", 1)[1])

GAP = timedelta(minutes=15)  # пауза больше — время не считаем


def slug(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))  # как Claude Code: `.claude` → `-claude`


def transcripts_dirs(root: Path) -> list[Path]:
    """Папки транскриптов main-checkout'а и всех его worktree."""
    projects = Path.home() / ".claude" / "projects"
    wt = root / ".claude" / "worktrees"
    paths = [root] + (sorted(p for p in wt.iterdir() if p.is_dir()) if wt.is_dir() else [])
    return [projects / slug(p) for p in paths]


def load_ledger(repo: Path):
    """session_id -> (areas, stage, branch). Одна сессия = один этап = одна ветка."""
    path = repo / ".claude" / "ledger.jsonl"
    by_session = {}
    rows = []
    if not path.exists():
        return by_session, rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows.append(row)
        sid = row.get("session")
        if sid:
            areas = [a.strip() for a in str(row.get("area", "прочее")).split("+") if a.strip()]
            by_session[sid[:8]] = (areas or ["прочее"], row.get("stage", ""), row.get("branch") or "main")
    return by_session, rows


def scan(dirs: list[Path], since):
    """session_id -> {minutes, tokens, output, first, last} по всем папкам транскриптов."""
    out = {}
    for f in sorted(f for d in dirs if d.exists() for f in d.glob("*.jsonl")):
        stamps, tokens, output = [], 0, 0
        try:
            fh = f.open(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"timestamp"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = d.get("timestamp")
                if not ts:
                    continue
                try:
                    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except ValueError:
                    continue
                stamps.append(t)
                u = (d.get("message") or {}).get("usage") or {}
                if u:
                    output += u.get("output_tokens", 0)
                    # свежие токены: кэш-чтение вдесятеро дешевле и картину искажает
                    tokens += (
                        u.get("input_tokens", 0)
                        + u.get("output_tokens", 0)
                        + u.get("cache_creation_input_tokens", 0)
                    )
        if not stamps:
            continue
        stamps.sort()
        if since and stamps[-1] < since:
            continue
        active = sum(
            ((b - a).total_seconds() for a, b in zip(stamps, stamps[1:]) if (b - a) <= GAP),
            0.0,
        )
        out[f.stem[:8]] = {
            "minutes": round(active / 60),
            "tokens": tokens,
            "output": output,
            "first": stamps[0],
            "last": stamps[-1],
        }
    return out


def human(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def bar(part: float, width: int = 18) -> str:
    filled = round(part * width)
    return "█" * filled + "·" * (width - filled)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    try:
        root = main_root(repo)  # ledger берём где стоим (в worktree он свежее), транскрипты — по main и всем дорожкам
    except SystemExit:
        root = repo
    since = datetime.now(timezone.utc) - timedelta(days=args.days) if args.days else None

    by_session, rows = load_ledger(repo)
    sessions = scan(transcripts_dirs(root), since)

    areas = defaultdict(lambda: {"minutes": 0, "tokens": 0, "sessions": 0})
    branches = defaultdict(lambda: {"minutes": 0, "tokens": 0, "sessions": 0})
    unmapped = {"minutes": 0, "tokens": 0, "sessions": 0}
    for sid, s in sessions.items():
        hit = by_session.get(sid)
        if not hit:
            unmapped["minutes"] += s["minutes"]
            unmapped["tokens"] += s["tokens"]
            unmapped["sessions"] += 1
            continue
        names = hit[0]
        for name in names:
            a = areas[name]
            a["minutes"] += s["minutes"] / len(names)
            a["tokens"] += s["tokens"] / len(names)
            a["sessions"] += 1   # этап на два слоя считается в обеих областях
        b = branches[hit[2]]
        b["minutes"] += s["minutes"]
        b["tokens"] += s["tokens"]
        b["sessions"] += 1

    if args.json:
        print(json.dumps(
            {"areas": {k: {kk: round(vv) for kk, vv in v.items()} for k, v in areas.items()},
             "branches": {k: {kk: round(vv) for kk, vv in v.items()} for k, v in branches.items()},
             "unmapped": unmapped, "stages": len(rows)},
            ensure_ascii=False, indent=2))
        return 0

    total_min = sum(v["minutes"] for v in areas.values()) or 1
    period = f"за {args.days} дн." if args.days else "всего"
    print(f"РАСХОД ПО ОБЛАСТЯМ ({period})   токены — свежие, без кэш-чтения")
    if not areas:
        print("  ledger пуст — размеченных этапов ещё нет")
    for name, v in sorted(areas.items(), key=lambda kv: -kv[1]["minutes"]):
        h = v["minutes"] / 60
        print(f"  {name:<8} {bar(v['minutes'] / total_min)} {h:>5.1f} ч  "
              f"{human(round(v['tokens'])):>6}  этапов {v['sessions']:.0f}")
    print(f"  {'ИТОГО':<8} {' ' * 18} {total_min / 60:>5.1f} ч  "
          f"{human(round(sum(v['tokens'] for v in areas.values()))):>6}  этапов {len(rows)}")
    if branches:
        print("ПО ВЕТКАМ")
        total_b = sum(v["minutes"] for v in branches.values()) or 1
        for name, v in sorted(branches.items(), key=lambda kv: -kv[1]["minutes"]):
            print(f"  {name:<8} {bar(v['minutes'] / total_b)} {v['minutes'] / 60:>5.1f} ч  "
                  f"{human(round(v['tokens'])):>6}  сессий {v['sessions']}")
    if unmapped["sessions"]:
        print(f"  вне учёта: {unmapped['sessions']} сессий, "
              f"{unmapped['minutes'] / 60:.1f} ч, {human(unmapped['tokens'])} "
              f"(этап не закрывали через /этап-конец)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
