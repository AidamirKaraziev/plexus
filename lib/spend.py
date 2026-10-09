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
import tempfile


def main_root(start: Path) -> Path:
    """Корень main-checkout'а — первая строка `git worktree list`, даже изнутри дорожки."""
    r = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=start, capture_output=True, text=True)
    return Path(r.stdout.splitlines()[0].split(" ", 1)[1])

GAP = timedelta(minutes=15)  # пауза больше — время не считаем


def slug(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))  # как Claude Code: `.claude` → `-claude`


WT_CWD = re.compile(r"/\.claude/worktrees/([^/\s]+)")
WT_DIR = re.compile(r"-claude-worktrees-(.+)$")
# хвост ответа Agent в транскрипте родителя: agentId, (worktreeBranch), <usage>
NOTE = re.compile(
    r"agentId: (\w+)(.{0,800}?)<usage>\s*subagent_tokens: (\d+).{0,80}?duration_ms: (\d+)", re.S)
WT_BRANCH = re.compile(r"worktreeBranch: ([^\s\\]+)")


def branch_from_cwd(cwd: str) -> str | None:
    """cwd внутри .claude/worktrees/<имя> → ветка worktree-<имя>."""
    m = WT_CWD.search(cwd or "")
    return f"worktree-{m.group(1)}" if m else None


def transcripts_dirs(root: Path, projects: Path | None = None) -> list[Path]:
    """Папки транскриптов main-checkout'а и всех его worktree."""
    projects = projects or Path.home() / ".claude" / "projects"
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


def _files(d: Path):
    """Транскрипты сессий и транскрипты субагентов (<сессия>/subagents/agent-*.jsonl)."""
    yield from d.glob("*.jsonl")
    yield from d.glob("*/subagents/agent-*.jsonl")


def scan(dirs: list[Path], since):
    """ключ сессии -> {minutes, tokens, output, first, last, branch}.

    Ключ: первые 8 символов id сессии; у субагента — полное имя файла.
    Если транскрипта субагента нет, цифры берём из <usage> в транскрипте родителя.
    """
    out = {}
    notes = {}  # agentId -> (ветка, токены, мс)
    seen_agents = set()
    for f in sorted(f for d in dirs if d.exists() for f in _files(d)):
        is_agent = f.stem.startswith("agent-") and f.parent.name == "subagents"
        if is_agent:
            seen_agents.add(f.stem[len("agent-"):])
        stamps, tokens, output, cwd = [], 0, 0, None
        try:
            fh = f.open(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                if "subagent_tokens" in line:
                    for m in NOTE.finditer(line.replace("\\n", "\n")):
                        b = WT_BRANCH.search(m.group(2))
                        notes[m.group(1)] = (b.group(1) if b else None, int(m.group(3)), int(m.group(4)))
                if '"timestamp"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if cwd is None and d.get("cwd"):
                    cwd = d["cwd"]
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
        branch = branch_from_cwd(cwd)
        if not branch and not is_agent:
            m = WT_DIR.search(f.parent.name)
            branch = f"worktree-{m.group(1)}" if m else None
        out[f.stem if is_agent else f.stem[:8]] = {
            "minutes": round(active / 60),
            "tokens": tokens,
            "output": output,
            "first": stamps[0],
            "last": stamps[-1],
            "branch": branch,
        }
    for aid, (branch, tok, ms) in notes.items():
        if aid in seen_agents:
            continue  # есть настоящий транскрипт — он точнее
        out[f"agent-{aid}"] = {
            "minutes": round(ms / 60000), "tokens": tok, "output": 0,
            "first": None, "last": None, "branch": branch,
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


def compute(repo: Path, projects: Path | None, since):
    try:
        root = main_root(repo)  # ledger берём где стоим (в worktree он свежее), транскрипты — по main и всем дорожкам
    except (SystemExit, IndexError, OSError):
        root = repo
    by_session, rows = load_ledger(repo)
    sessions = scan(transcripts_dirs(root, projects), since)

    areas = defaultdict(lambda: {"minutes": 0, "tokens": 0, "sessions": 0})
    branches = defaultdict(lambda: {"minutes": 0, "tokens": 0, "sessions": 0})
    unmapped = {"minutes": 0, "tokens": 0, "sessions": 0}
    for sid, s in sessions.items():
        hit = by_session.get(sid)
        branch = (hit[2] if hit else None) or s.get("branch")
        if hit:
            names = hit[0]
            for name in names:
                a = areas[name]
                a["minutes"] += s["minutes"] / len(names)
                a["tokens"] += s["tokens"] / len(names)
                a["sessions"] += 1   # этап на два слоя считается в обеих областях
        if branch:
            b = branches[branch]
            b["minutes"] += s["minutes"]
            b["tokens"] += s["tokens"]
            b["sessions"] += 1
        else:
            unmapped["minutes"] += s["minutes"]
            unmapped["tokens"] += s["tokens"]
            unmapped["sessions"] += 1
    return areas, branches, unmapped, rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--projects", default=None, help="папка транскриптов (по умолчанию ~/.claude/projects)")
    ap.add_argument("--самопроверка", action="store_true")
    args = ap.parse_args()
    if args.самопроверка:
        return самопроверка()

    repo = Path(args.repo).resolve()
    since = datetime.now(timezone.utc) - timedelta(days=args.days) if args.days else None
    areas, branches, unmapped, rows = compute(repo, Path(args.projects) if args.projects else None, since)

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


def самопроверка() -> int:
    """Фиктивные репо и папка транскриптов во временной папке; живое не читаем и не пишем."""
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("  ок   " if cond else "  FAIL ") + name)
        ok = ok and bool(cond)

    def line(ts, cwd):
        return json.dumps({"timestamp": ts, "cwd": cwd, "message": {"usage": {"input_tokens": 10, "output_tokens": 5}}})

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp).resolve()
        repo, proj = tmp / "repo", tmp / "projects"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        wt = repo / ".claude" / "worktrees" / "agent-abc"
        wt.mkdir(parents=True)
        # 1. сессия из дорожки: cwd в .claude/worktrees/agent-abc
        d = proj / slug(wt)
        d.mkdir(parents=True)
        (d / "11111111-aaaa.jsonl").write_text(
            line("2026-10-01T10:00:00Z", str(wt)) + "\n" + line("2026-10-01T10:05:00Z", str(wt)) + "\n")
        # 2. сессия человека без дорожки — в unmapped; в ней уведомление о субагенте без транскрипта
        m = proj / slug(repo)
        m.mkdir(parents=True)
        note = ("agentId: zzz999 (use SendMessage)\nworktreeBranch: worktree-agent-zzz\n"
                "<usage>subagent_tokens: 4200\ntool_uses: 3\nduration_ms: 180000</usage>")
        (m / "22222222-bbbb.jsonl").write_text(
            line("2026-10-01T09:00:00Z", str(repo)) + "\n"
            + line("2026-10-01T09:02:00Z", str(repo)) + "\n"
            + json.dumps({"timestamp": "2026-10-01T09:03:00Z", "cwd": str(repo),
                          "message": {"content": [{"type": "tool_result", "content": note}]}}) + "\n")
        r = subprocess.run([sys.executable, __file__, "--json", "--repo", str(repo), "--projects", str(proj)],
                           capture_output=True, text=True)
        try:
            res = json.loads(r.stdout)
        except json.JSONDecodeError:
            res = {"branches": {}, "unmapped": {}}
            print(r.stderr)
        br = res["branches"]
        check("branches непуст", bool(br))
        check("cwd agent-abc → worktree-agent-abc", br.get("worktree-agent-abc", {}).get("sessions") == 1
              and br["worktree-agent-abc"]["minutes"] == 5)
        z = br.get("worktree-agent-zzz", {})
        check("нет транскрипта субагента → цифры из subagent_tokens и duration_ms",
              z.get("tokens") == 4200 and z.get("minutes") == 3)
        check("сессия вне дорожек — в unmapped", res["unmapped"].get("sessions") == 1)
    print("ок" if ok else "ПРОВАЛ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
