#!/usr/bin/env python3
"""Расход по областям и по веткам: ledger.jsonl, транскрипты Claude Code, журнал opencode и сессии DSH.

Модель этот файл не парсит — запускает и печатает готовую таблицу.
Транскрипты — папки ~/.claude/projects/<slug> для main-checkout и каждого
.claude/worktrees/E0N (slug: всё не-буквенно-цифровое → «-»). Ветка — из
ledger.branch, строки без него идут в «main».
Журнал opencode — ~/.local/share/opencode/plexus/projects/<slug каталога>/
<sessionID>.jsonl, строка {ts, sessionID, type, directory?, tokens?, cost?,
parentID?}.
Сессии DSH — ~/.dsh/sessions/<slug проекта>/session-<uuid>/session.v4.jsonl.zstd:
журнал сжат zstd (модуль zstandard, иначе `zstd -dc`), события {type, time,
seq, data}; usage — у шагов assistant/message (inputTokens, cacheReadTokens,
cacheWriteTokens, outputTokens), модель — в message.source или request/header.
Токены — свежие (вход + выход + запись кэша), время — по полю time, деньги —
расчёт по ДШ_ЦЕНЫ (цены моделей провайдера Go), ключ — uuid сессии без
префикса «session-», как поле session в ledger.
Сводка объединяет все источники: токены и время из всех, деньги — cost строк
журнала и расчёт DSH, у Claude честное «—». Области —
из ledger по полю session; строки журналов без ledger-записи — «прочее».
Ветка строки журнала — из directory: дорожка .codex/worktrees/<имя> →
codex/<имя>, иначе «main»; сессии DSH — из их cwd по тем же правилам.
Расход работников — из дочерних сессий по parentID; журналы его не несут —
в работниках «—».

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
CODEX_WT = re.compile(r"/\.codex/worktrees/([^/\s]+)")
# хвост ответа Agent в транскрипте родителя: agentId, (worktreeBranch), <usage>
NOTE = re.compile(
    r"agentId: (\w+)(.{0,800}?)<usage>\s*subagent_tokens: (\d+).{0,80}?duration_ms: (\d+)", re.S)
WT_BRANCH = re.compile(r"worktreeBranch: ([^\s\\]+)")


def branch_from_cwd(cwd: str) -> str | None:
    """cwd внутри .claude/worktrees/<имя> → ветка worktree-<имя>."""
    m = WT_CWD.search(cwd or "")
    return f"worktree-{m.group(1)}" if m else None


def branch_from_directory(d: str | None) -> str:
    """directory строки журнала → ветка: дорожка .codex/worktrees/<имя> → codex/<имя>, иначе «main»."""
    m = CODEX_WT.search(d or "")
    return f"codex/{m.group(1)}" if m else "main"


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


ЖУРНАЛ_ПАПКА = Path.home() / ".local" / "share" / "opencode" / "plexus" / "projects"
ДШ_ПАПКА = Path.home() / ".dsh" / "sessions"
# $ за 1M токенов: (вход, чтение кэша, запись кэша, выход) — модели провайдера Go
# (каталог pi-ai 1.3.0, тот же справочник, что в dsh_digest.py кортекса)
ДШ_ЦЕНЫ = {
    "glm-5.3": (1.4, 0.26, 0.0, 4.4), "glm-5.3-flash": (0.15, 0.03, 0.0, 0.5),
    "qwen4-max": (1.5, 0.075, 1.875, 4.5), "qwen3.8-max": (2, 0.25, 2.5, 6), "kimi-k3": (3, 0.3, 0, 15),
    "deepseek-v4-pro": (0.66, 0.022, 0, 1.98), "deepseek-v4.1-flash": (0.15, 0.003, 0, 0.6),
}


def read_ts(v):
    """ts строки журнала → datetime: миллисекунды epoch (Date.now плагина) или ISO-строка."""
    try:
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v / 1000, tz=timezone.utc)
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (ValueError, TypeError, OSError, OverflowError):
        return None


def journal_scan(jroot: Path | None, since):
    """Журнал плагина opencode → (сессии, работники).

    сессии: ключ (первые 8 символов sessionID) -> {minutes, tokens, cost,
    cost_known, first, last, branch, opencode: True}.
    работники: parentID -> {minutes, tokens, cost, cost_known, sessions} —
    из дочерних сессий (строки с parentID); журналу нечего сказать — словарь пуст.
    Токены — только у строк session.usage.updated, свежие: input + output +
    cache.write. Время — из ts строк, пауза больше GAP не считается.
    Деньги — cost строк журнала; у источника без cost — cost_known = 0.
    """
    out, workers = {}, {}
    if not jroot:
        return out, workers
    jroot = Path(jroot)
    if not jroot.is_dir():
        return out, workers
    for f in sorted(jroot.glob("*/*.jsonl")):
        stamps, tokens, cost, cost_known, parent, directory = [], 0, 0.0, False, None, None
        try:
            fh = f.open(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = read_ts(d.get("ts"))
                if t:
                    stamps.append(t)
                if d.get("directory"):
                    directory = d["directory"]
                if d.get("parentID"):
                    parent = d["parentID"]
                if d.get("type") == "session.usage.updated":
                    u = d.get("tokens") or {}
                    c = u.get("cache") or {}
                    tokens += u.get("input", 0) + u.get("output", 0) + c.get("write", 0)
                if isinstance(d.get("cost"), (int, float)):
                    cost += d["cost"]
                    cost_known = True
        if not stamps:
            continue
        stamps.sort()
        if since and stamps[-1] < since:
            continue
        active = sum(
            ((b - a).total_seconds() for a, b in zip(stamps, stamps[1:]) if (b - a) <= GAP),
            0.0,
        )
        entry = {
            "minutes": round(active / 60),
            "tokens": tokens,
            "output": 0,
            "cost": cost if cost_known else None,
            "cost_known": cost_known,
            "first": stamps[0],
            "last": stamps[-1],
            "branch": branch_from_directory(directory),
            "opencode": True,
        }
        out[f.stem[:8]] = entry
        if parent:
            w = workers.setdefault(parent, {"minutes": 0, "tokens": 0, "cost": 0.0, "cost_known": 0, "sessions": 0})
            w["minutes"] += entry["minutes"]
            w["tokens"] += tokens
            w["cost"] += cost
            w["cost_known"] += int(cost_known)
            w["sessions"] += 1
    return out, workers


def dsh_events(path: Path):
    """События журнала сессии DSH (.jsonl.zstd): zstandard, иначе `zstd -dc`."""
    try:
        import zstandard
    except ImportError:
        raw = subprocess.run(["zstd", "-dc", str(path)], capture_output=True, check=True).stdout
    else:
        with open(path, "rb") as fh:
            raw = zstandard.ZstdDecompressor().stream_reader(fh).read()
    for line in raw.decode("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def dsh_write(path: Path, events) -> bool:
    """Сжать события в журнал DSH для самопроверки; False — сжимать нечем."""
    raw = ("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n").encode("utf-8")
    try:
        import zstandard
    except ImportError:
        try:
            raw = subprocess.run(["zstd", "-q", "-c"], input=raw,
                                 capture_output=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            return False
    else:
        raw = zstandard.ZstdCompressor().compress(raw)
    path.write_bytes(raw)
    return True


def dsh_dirs(repo: Path, droot: Path) -> list[Path]:
    """Папки сессий DSH проекта: main-checkout, где стоим, дорожки работников."""
    try:
        base = main_root(repo)
    except (IndexError, OSError):  # не git-репозиторий — считаем папку саму по себе
        base = repo.resolve()
    paths = [base, repo.resolve()]
    wt = base / ".claude" / "worktrees"
    if wt.is_dir():
        paths += [p for p in sorted(wt.iterdir()) if p.is_dir()]
    out, seen = [], set()
    for p in paths:  # DSH слугает путь с хвостовым разделителем и оборачивает дефисами:
        for name in (f"-{slug(p)}--", f"-{slug(p)}-", slug(p)):  # /a/b/p → --a-b-p--
            d = droot / name
            if d.is_dir() and d not in seen:
                seen.add(d)
                out.append(d)
    return out


def dsh_scan(repo: Path, droot: Path | None, since):
    """Сессии DSH → ключ (первые 8 символов uuid) -> {minutes, tokens, cost, …}.

    Токены — свежие: inputTokens + outputTokens + cacheWriteTokens по шагам с
    usage (assistant/message; если harness кладёт usage в step/end, берём и
    его — шаг считается один раз). Деньги — расчёт по ДШ_ЦЕНЫ; модель без цены
    не считается, у сессии без единственной цены — «—». Время — по полю
    time/createdAt (мс epoch), пауза больше GAP не считается. Ветка — из cwd
    сессии; родителя (parentID) журнал не несёт — в работниках «—».
    """
    out = {}
    if not droot:
        return out
    files = sorted(f for d in dsh_dirs(repo, Path(droot))
                   for f in d.glob("session-*/session*.jsonl.zstd") if f.is_file())
    for f in files:
        stamps, tokens, cost, cost_known, cwd, sid = [], 0, 0.0, False, None, None
        counted = set()
        for d in dsh_events(f):
            t = read_ts(d.get("time") or d.get("createdAt"))
            if t:
                stamps.append(t)
            typ, data = d.get("type"), d.get("data") or {}
            if typ == "session":
                cwd, sid = d.get("cwd"), d.get("id")
            elif typ in ("assistant/message", "step/end"):
                u = data.get("usage")
                if not u:
                    continue
                key = (data.get("turn"), data.get("step"))
                if key in counted:  # usage шага уже учтён, step/end не дублирует
                    continue
                counted.add(key)
                src = (data.get("message") or {}).get("source") or {}
                inp, rd = u.get("inputTokens", 0), u.get("cacheReadTokens", 0)
                wr, outp = u.get("cacheWriteTokens", 0), u.get("outputTokens", 0)
                tokens += inp + outp + wr
                p = ДШ_ЦЕНЫ.get(src.get("model") or "")
                if p:
                    ci, cr, cw, co = p
                    cost += (inp * ci + rd * cr + wr * cw + outp * co) / 1e6
                    cost_known = True
        if not stamps:
            continue
        stamps.sort()
        if since and stamps[-1] < since:
            continue
        active = sum(
            ((b - a).total_seconds() for a, b in zip(stamps, stamps[1:]) if (b - a) <= GAP),
            0.0,
        )
        sid = (sid or f.parent.name).removeprefix("session-")
        out[sid[:8]] = {
            "minutes": round(active / 60),
            "tokens": tokens,
            "output": 0,
            "cost": cost if cost_known else None,
            "cost_known": cost_known,
            "first": stamps[0],
            "last": stamps[-1],
            "branch": branch_from_cwd(cwd) or branch_from_directory(cwd) or "main",
            "dsh": True,
        }
    return out


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
            "cost": None,
            "cost_known": False,
            "first": stamps[0],
            "last": stamps[-1],
            "branch": branch,
        }
    for aid, (branch, tok, ms) in notes.items():
        if aid in seen_agents:
            continue  # есть настоящий транскрипт — он точнее
        out[f"agent-{aid}"] = {
            "minutes": round(ms / 60000), "tokens": tok, "output": 0,
            "cost": None, "cost_known": False,
            "first": None, "last": None, "branch": branch,
        }
    return out


def human(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def money(c: float) -> str:
    return f"${c:.2f}"


def деньги(v: dict) -> str:
    """Колонка «деньги»: cost строк журнала и расчёт сессий DSH; у источника
    без денег (Claude, модель без цены) — честное «—»."""
    return money(v["cost"]) if v.get("cost_known") else "—"


def bar(part: float, width: int = 18) -> str:
    filled = round(part * width)
    return "█" * filled + "·" * (width - filled)


def compute(repo: Path, projects: Path | None, since, journal_root: Path | None = None,
            dsh_root: Path | None = None):
    try:
        root = main_root(repo)  # ledger берём где стоим (в worktree он свежее), транскрипты — по main и всем дорожкам
    except (SystemExit, IndexError, OSError):
        root = repo
    by_session, rows = load_ledger(repo)
    sessions = scan(transcripts_dirs(root, projects), since)
    jsessions, jworkers = journal_scan(journal_root, since)
    dsessions = dsh_scan(repo, dsh_root, since)

    def влить(key, j):
        s = sessions.get(key)
        if s:
            s["minutes"] += j["minutes"]
            s["tokens"] += j["tokens"]
            if s["first"] and j["first"]:
                s["first"] = min(s["first"], j["first"])
                s["last"] = max(s["last"], j["last"])
            if j["cost_known"]:
                s["cost"] = (s["cost"] or 0) + j["cost"]
                s["cost_known"] = True
            s["branch"] = j["branch"]
        else:
            sessions[key] = j

    # объединение источников: один ключ в двух — суммируем токены и время,
    # деньги (cost) — только у журналов; ветка строки журнала — из directory
    for key, j in jsessions.items():
        влить(key, j)
    for key, j in dsessions.items():
        if key not in jsessions:  # id, уже учтённый журналом opencode, не дублируем
            влить(key, j)

    areas = defaultdict(lambda: {"minutes": 0.0, "tokens": 0, "sessions": 0, "cost": 0.0, "cost_known": 0})
    branches = defaultdict(lambda: {"minutes": 0.0, "tokens": 0, "sessions": 0, "cost": 0.0, "cost_known": 0})
    unmapped = {"minutes": 0.0, "tokens": 0, "sessions": 0, "cost": 0.0, "cost_known": 0}

    def долить(bucket, s):
        bucket["minutes"] += s["minutes"]
        bucket["tokens"] += s["tokens"]
        bucket["cost"] += s["cost"] or 0
        bucket["cost_known"] += int(bool(s["cost_known"]))
        bucket["sessions"] += 1

    for sid, s in sessions.items():
        hit = by_session.get(sid)
        branch = (hit[2] if hit else None) or s.get("branch")
        if hit:
            names = hit[0]
            for name in names:
                a = areas[name]
                a["minutes"] += s["minutes"] / len(names)
                a["tokens"] += s["tokens"] / len(names)
                a["cost"] += (s["cost"] or 0) / len(names)
                a["cost_known"] += int(bool(s["cost_known"]))
                a["sessions"] += 1   # этап на два слоя считается в обеих областях
        elif s.get("opencode") or s.get("dsh"):
            долить(areas["прочее"], s)  # строка журнала без ledger-записи — область «прочее»
        if branch:
            долить(branches[branch], s)
        else:
            долить(unmapped, s)
    return areas, branches, unmapped, rows, jworkers, bool(jsessions or dsessions)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--projects", default=None, help="папка транскриптов (по умолчанию ~/.claude/projects)")
    ap.add_argument("--journal", default=None,
                    help="папка журнала opencode (по умолчанию ~/.local/share/opencode/plexus/projects)")
    ap.add_argument("--dsh", default=None,
                    help="папка сессий DSH (по умолчанию ~/.dsh/sessions)")
    ap.add_argument("--самопроверка", action="store_true")
    args = ap.parse_args()
    if args.самопроверка:
        return самопроверка()

    repo = Path(args.repo).resolve()
    since = datetime.now(timezone.utc) - timedelta(days=args.days) if args.days else None
    areas, branches, unmapped, rows, jworkers, есть_журнал = compute(
        repo, Path(args.projects) if args.projects else None, since,
        Path(args.journal) if args.journal else ЖУРНАЛ_ПАПКА,
        Path(args.dsh) if args.dsh else ДШ_ПАПКА)

    if args.json:
        def срезать(v):
            return {k: (round(x, 3) if k == "cost" else round(x)) for k, x in v.items()}
        print(json.dumps(
            {"areas": {k: срезать(v) for k, v in areas.items()},
             "branches": {k: срезать(v) for k, v in branches.items()},
             "unmapped": срезать(unmapped), "stages": len(rows),
             "workers": {p[:8]: срезать(w) for p, w in jworkers.items()}},
            ensure_ascii=False, indent=2))
        return 0

    total_min = sum(v["minutes"] for v in areas.values()) or 1
    период = f"за {args.days} дн." if args.days else "всего"
    print(f"РАСХОД ПО ОБЛАСТЯМ ({период})   токены — свежие, без кэш-чтения; деньги — журнал opencode и расчёт DSH")
    if not areas:
        print("  ledger пуст — размеченных этапов ещё нет")
    for name, v in sorted(areas.items(), key=lambda kv: -kv[1]["minutes"]):
        h = v["minutes"] / 60
        print(f"  {name:<8} {bar(v['minutes'] / total_min)} {h:>5.1f} ч  "
              f"{human(round(v['tokens'])):>6}  {деньги(v):>7}  этапов {v['sessions']:.0f}")
    итого_деньги = (money(sum(v["cost"] for v in areas.values()))
                    if any(v["cost_known"] for v in areas.values()) else "—")
    print(f"  {'ИТОГО':<8} {' ' * 18} {total_min / 60:>5.1f} ч  "
          f"{human(round(sum(v['tokens'] for v in areas.values()))):>6}  {итого_деньги:>7}  этапов {len(rows)}")
    if branches:
        print("ПО ВЕТКАМ")
        total_b = sum(v["minutes"] for v in branches.values()) or 1
        for name, v in sorted(branches.items(), key=lambda kv: -kv[1]["minutes"]):
            print(f"  {name:<8} {bar(v['minutes'] / total_b)} {v['minutes'] / 60:>5.1f} ч  "
                  f"{human(round(v['tokens'])):>6}  {деньги(v):>7}  сессий {v['sessions']}")
    if unmapped["sessions"]:
        print(f"  вне учёта: {unmapped['sessions']} сессий, "
              f"{unmapped['minutes'] / 60:.1f} ч, {human(unmapped['tokens'])} "
              f"(этап не закрывали через /этап-конец)")
    if есть_журнал:
        print("РАБОТНИКИ (дочерние сессии журнала по parentID)")
        if jworkers:
            for pid, w in sorted(jworkers.items(), key=lambda kv: -kv[1]["tokens"]):
                print(f"  {pid[:8]:<8} {w['minutes'] / 60:>5.1f} ч  {human(w['tokens']):>6}  "
                      f"{(money(w['cost']) if w['cost_known'] else '—'):>7}  сессий {w['sessions']}")
        else:
            print("  —  журнал не несёт parentID: расход работников не считается")
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
        r = subprocess.run([sys.executable, __file__, "--json", "--repo", str(repo), "--projects", str(proj),
                            "--journal", str(tmp / "журнала-нет"), "--dsh", str(tmp / "дш-нет")],
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

        # --- журнал opencode: фикстуры во временной папке, живой журнал не трогаем
        jroot = tmp / "журнал"
        base = 1798246800000  # произвольная точка; важны только разности между ts

        def jline(ts, sid, typ, **kw):
            return json.dumps({"ts": ts, "sessionID": sid, "type": typ, **kw})

        # сессия в main-checkout, размечена в ledger: область из ledger, деньги из журнала
        (repo / ".claude" / "ledger.jsonl").write_text(
            json.dumps({"session": "33333333-cccc-абв", "area": "расход", "stage": "S02", "branch": "main"}) + "\n"
            + json.dumps({"session": "77777777-gggg", "area": "учёт", "stage": "S01", "branch": "main"}) + "\n"
            + json.dumps({"session": "88888888-hhhh", "area": "кортекс", "stage": "S03",
                          "branch": "worktree-agent-dsh"}) + "\n",
            encoding="utf-8")
        # Claude-сессия в main, размеченная в ledger: с ней ветка main объединяет оба источника
        (m / "77777777-gggg.jsonl").write_text(
            line("2026-10-01T08:00:00Z", str(repo)) + "\n" + line("2026-10-01T08:04:00Z", str(repo)) + "\n",
            encoding="utf-8")
        jmain = jroot / slug(repo)
        jmain.mkdir(parents=True)
        (jmain / "33333333-cccc.jsonl").write_text("\n".join([
            jline(base, "33333333-cccc", "session.created", directory=str(repo)),
            jline(base + 60_000, "33333333-cccc", "session.step.started", directory=str(repo),
                  model={"id": "glm-5.3-flash", "providerID": "opencode-go"}),
            jline(base + 120_000, "33333333-cccc", "session.usage.updated", directory=str(repo),
                  tokens={"input": 100, "output": 50, "reasoning": 10, "cache": {"read": 7000, "write": 30}},
                  cost=0.02),
            jline(base + 360_000, "33333333-cccc", "session.usage.updated", directory=str(repo),
                  tokens={"input": 10, "output": 5, "reasoning": 0, "cache": {"read": 0, "write": 0}}, cost=0.01),
        ]) + "\n", encoding="utf-8")
        # дорожка: directory в .codex/worktrees/dorozhka → ветка codex/dorozhka; ledger-записи нет → область «прочее»
        wt_codex = repo / ".codex" / "worktrees" / "dorozhka"
        jw = jroot / slug(wt_codex)
        jw.mkdir(parents=True)
        (jw / "44444444-dddd.jsonl").write_text("\n".join([
            jline(base, "44444444-dddd", "session.created", directory=str(wt_codex)),
            jline(base + 120_000, "44444444-dddd", "session.usage.updated", directory=str(wt_codex),
                  tokens={"input": 20, "output": 10, "reasoning": 0, "cache": {"read": 0, "write": 2}}, cost=0.05),
        ]) + "\n", encoding="utf-8")
        # работник: дочерняя сессия с parentID → расход работника у родителя 33333333
        (jmain / "55555555-eeee.jsonl").write_text("\n".join([
            jline(base, "55555555-eeee", "session.created", directory=str(repo), parentID="33333333-cccc-абв"),
            jline(base + 60_000, "55555555-eeee", "session.usage.updated", directory=str(repo),
                  tokens={"input": 7, "output": 3, "reasoning": 0, "cache": {"read": 0, "write": 1}}, cost=0.005),
        ]) + "\n", encoding="utf-8")

        # --- сессии DSH: фикстуры сжимаются zstd во временной папке, живое ~/.dsh не трогаем
        дш = tmp / "дш"

        def дш_сессия(wt: str, sid: str, usage: list, model="glm-5.3") -> bool:
            """Журнал DSH в дорожке <wt>: шаги с usage и их дубли в step/end."""
            папка = repo / ".claude" / "worktrees" / wt
            папка.mkdir(parents=True, exist_ok=True)
            sd = дш / f"-{slug(папка)}--" / f"session-{sid}"
            sd.mkdir(parents=True, exist_ok=True)
            ev = [{"type": "session", "version": 4, "id": f"session-{sid}", "createdAt": base,
                   "cwd": str(папка)},
                  {"type": "request/header", "seq": 0, "time": base,
                   "data": {"header": {"config": {"provider": "opencode-go", "model": model}}}}]
            for i, u in enumerate(usage, 1):
                ev += [{"type": "assistant/message", "seq": 2 * i, "time": base + i * 60_000,
                         "data": {"turn": 1, "step": i,
                                  "message": {"role": "assistant", "source": {"model": model}},
                                  "usage": u}},
                        {"type": "step/end", "seq": 2 * i + 1, "time": base + i * 60_000 + 500,
                         "data": {"turn": 1, "step": i, "usage": u}}]  # дубль — шаг один раз
            return dsh_write(sd / "session.v4.jsonl.zstd", ev)

        дш_готов = all([
            # размечена в ledger: область «кортекс», деньги по glm-5.3, шаг не задваивается
            дш_сессия("agent-dsh", "88888888-hhhh-4f3d-bbea-414ab84e7989",
                      [{"inputTokens": 100_000, "cacheReadTokens": 0, "cacheWriteTokens": 0,
                        "outputTokens": 1_000},
                       {"inputTokens": 1_000, "cacheReadTokens": 200_000, "cacheWriteTokens": 3_000,
                        "outputTokens": 2_000}]),
            # без ledger-записи → «прочее», flash по своей цене
            дш_сессия("agent-flash", "99990000-zzzz-4f3d-bbea-414ab84e7989",
                      [{"inputTokens": 1_000_000, "cacheReadTokens": 0, "cacheWriteTokens": 0,
                        "outputTokens": 10_000}], "glm-5.3-flash"),
            # модель без цены → деньги «—»
            дш_сессия("agent-без-цен", "99991111-qqqq-4f3d-bbea-414ab84e7989",
                      [{"inputTokens": 500, "cacheReadTokens": 0, "cacheWriteTokens": 0,
                        "outputTokens": 5}], "модель-без-цен"),
        ])
        if not дш_готов:
            print("  пропуск: нет ни zstandard, ни zstd — источник DSH не проверить")
        r = subprocess.run([sys.executable, __file__, "--json", "--repo", str(repo), "--projects", str(proj),
                            "--journal", str(jroot), "--dsh", str(дш)], capture_output=True, text=True)
        try:
            res = json.loads(r.stdout)
        except json.JSONDecodeError:
            res = {"branches": {}, "areas": {}, "unmapped": {}, "workers": {}}
            print(r.stderr)
        br, ar, wk = res["branches"], res["areas"], res["workers"]
        check("журнал: ветка из directory — дорожка .codex/worktrees → codex/dorozhka",
              br.get("codex/dorozhka", {}).get("sessions") == 1)
        check("журнал без ledger-записи → область «прочее»",
              ar.get("прочее", {}).get("sessions") == (4 if дш_готов else 2))
        check("журнал с ledger-записью → область из ledger", ar.get("расход", {}).get("tokens") == 195)
        check("объединение: токены и время из обоих источников",
              br["main"]["sessions"] == 3 and br["main"]["minutes"] == 11)
        check("деньги только у журнала: у Claude-ветки «—»",
              br["worktree-agent-abc"].get("cost_known") == 0)
        check("деньги журнала сходятся (cost строк)",
              br["main"]["cost"] == 0.035 and br["main"]["cost_known"] == 2)
        check("работники: расход дочерних сессий по parentID",
              wk.get("33333333", {}).get("tokens") == 11 and wk["33333333"]["cost"] == 0.005)
        if дш_готов:
            check("DSH: сессия из ledger по полю session, шаг считается один раз",
                  ar.get("кортекс", {}).get("tokens") == 107_000 and ar["кортекс"]["sessions"] == 1)
            check("DSH: деньги — расчёт по ценам Go (вход + чтение кэша + выход)",
                  ar.get("кортекс", {}).get("cost") == 0.207 and ar["кортекс"]["cost_known"] == 1)
            check("DSH: ветка из cwd сессии, flash по своей цене",
                  br.get("worktree-agent-flash", {}).get("cost") == 0.155)
            check("DSH: модель без цены → деньги «—»",
                  br.get("worktree-agent-без-цен", {}).get("cost_known") == 0)

        # журнал без parentID → работники «—» (честное пусто, не ноль)
        jroot2 = tmp / "журнал-без-родителя"
        j2 = jroot2 / slug(repo)
        j2.mkdir(parents=True)
        (j2 / "66666666-ffff.jsonl").write_text(
            jline(base, "66666666-ffff", "session.usage.updated", directory=str(repo),
                  tokens={"input": 1, "output": 1, "reasoning": 0, "cache": {"read": 0, "write": 0}},
                  cost=0.01) + "\n", encoding="utf-8")
        r2 = subprocess.run([sys.executable, __file__, "--json", "--repo", str(repo), "--projects", str(proj),
                             "--journal", str(jroot2), "--dsh", str(tmp / "дш-нет")],
                            capture_output=True, text=True)
        try:
            res2 = json.loads(r2.stdout)
        except json.JSONDecodeError:
            res2 = {"workers": {"x": 1}}
            print(r2.stderr)
        check("журнал без parentID → работники «—»", res2.get("workers") == {})

    print("ок" if ok else "ПРОВАЛ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
