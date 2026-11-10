#!/usr/bin/env python3
"""Замер контекста: сколько окна занято в последнем ответе самой свежей сессии.

Читает usage последнего ответа ассистента (input + cache_creation + cache_read)
в самом свежем .jsonl транскрипта main-checkout'а и сравнивает с порогом —
долей окна. Настройка — строки в шапке .claude/plan/roadmap.md:
`контекст: 20 %` (порог, по умолчанию 20 %) и `окно: 1M` (1M, 200k или число;
перекрывает таблицу окон по id модели; модель неизвестна → 200k, а если
занято больше окна — 1M).

    python3 ${CLAUDE_PLUGIN_ROOT}/lib/контекст.py                      # свежая сессия
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/контекст.py --сессия <файл.jsonl>
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/контекст.py --repo <папка> --projects <папка транскриптов>
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/контекст.py --самопроверка

Печатает одну строку: `контекст: 182k из 1M · 18 % · порог 20 % · ок`.
Коды выхода: 0 — под порогом; 1 — порог перейдён; 2 — ошибка аргументов;
3 — нет данных (нет журнала или usage; строка `контекст: нет данных — <причина>`).
"""
import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spend import main_root, slug  # noqa: E402

DEFAULT_THRESHOLD = 20.0
DEFAULT_WINDOW = 200_000
# окно по умолчанию по префиксу id модели (справочник моделей Anthropic,
# 2026-10); первый совпавший, поэтому частное выше общего (opus-4-6 выше opus-4).
# Суффикс [1m] даёт 1M независимо от таблицы, но в транскрипт он не попадает.
WINDOWS = [
    # 1M
    ("claude-fable-5", 1_000_000),     # fable-5, 5-1, 5-2
    ("claude-mythos-5", 1_000_000),
    ("claude-opus-5", 1_000_000),      # opus-5, 5-5
    ("claude-sonnet-5", 1_000_000),    # sonnet-5, 5-5
    ("claude-haiku-5", 1_000_000),     # haiku-5-5
    ("claude-opus-4-8", 1_000_000),
    ("claude-opus-4-7", 1_000_000),
    ("claude-opus-4-6", 1_000_000),
    ("claude-sonnet-4-6", 1_000_000),
    # 200k
    ("claude-opus-4", 200_000),        # opus-4, 4-1, 4-5
    ("claude-sonnet-4", 200_000),      # sonnet-4, 4-5 (1M только с [1m])
    ("claude-haiku-4", 200_000),       # haiku-4-5
    ("claude-3", 200_000),
]


def parse_size(text: str) -> int | None:
    m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*([kKкК]|[mMмМ])?\s*", text)
    if not m:
        return None
    n = float(m.group(1).replace(",", "."))
    unit = (m.group(2) or "").lower()
    n *= 1_000_000 if unit in ("m", "м") else 1000 if unit in ("k", "к") else 1
    return int(n)


def fmt_size(n: int) -> str:
    if n >= 1_000_000 and n % 1_000_000 == 0:
        return f"{n // 1_000_000}M"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    return f"{round(n / 1000)}k" if n >= 1000 else str(n)


def read_header(repo: Path) -> tuple[float, int | None]:
    """(порог в %, окно или None) из frontmatter .claude/plan/roadmap.md."""
    threshold, window = DEFAULT_THRESHOLD, None
    path = repo / ".claude" / "plan" / "roadmap.md"
    if not path.exists():
        return threshold, window
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return threshold, window
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, _, val = line.partition(":")
        key = key.strip()
        if key == "контекст":
            m = re.match(r"\s*(\d+(?:[.,]\d+)?)\s*%?\s*$", val)
            if m:
                threshold = float(m.group(1).replace(",", "."))
        elif key == "окно":
            window = parse_size(val) or window
    return threshold, window


def model_window(model: str | None) -> int:
    model = model or ""
    if "[1m]" in model.lower():
        return 1_000_000
    for prefix, size in WINDOWS:
        if model.startswith(prefix):
            return size
    return DEFAULT_WINDOW


def last_usage(path: Path):
    """(занято токенов, модель) из последнего ответа ассистента с usage, или None."""
    found = None
    with path.open(encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if '"usage"' not in line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = d.get("message") or {}
            u = msg.get("usage")
            if msg.get("role") != "assistant" or not u or msg.get("model") == "<synthetic>":
                continue
            used = (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                    + u.get("cache_read_input_tokens", 0))
            found = (used, msg.get("model"))
    return found


def newest_journal(repo: Path, projects: Path | None):
    projects = projects or Path.home() / ".claude" / "projects"
    try:
        root = main_root(repo)
    except Exception:
        root = repo.resolve()
    d = projects / slug(root)
    files = sorted(d.glob("*.jsonl"), key=lambda f: f.stat().st_mtime) if d.is_dir() else []
    return files[-1] if files else None


def measure(repo: Path, projects: Path | None, session: Path | None) -> tuple[int, str]:
    journal = session or newest_journal(repo, projects)
    if journal is None or not journal.is_file():
        return 3, "контекст: нет данных — нет журнала сессии"
    usage = last_usage(journal)
    if usage is None:
        return 3, "контекст: нет данных — в журнале нет usage"
    used, model = usage
    threshold, window = read_header(repo)
    window = window or model_window(model)
    if used > window:  # таблица отстала: занято больше окна — значит окно 1M
        window = max(window, 1_000_000)
    pct = used / window * 100
    over = pct >= threshold
    line = (f"контекст: {fmt_size(used)} из {fmt_size(window)} · {round(pct)} % · "
            f"порог {threshold:g} % · {'порог' if over else 'ок'}")
    return (1 if over else 0), line


def _journal(path: Path, used: int, model: str = "claude-haiku-4-5-20251001"):
    rows = [{"message": {"role": "user", "content": "hi"}},
            {"message": {"role": "assistant", "model": model, "usage": {
                "input_tokens": 1, "cache_creation_input_tokens": used - 1 - 100,
                "cache_read_input_tokens": 100, "output_tokens": 5}}}]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def selftest() -> int:
    fails = []

    def check(name, got, want_code, want_sub):
        code, line = got
        if code != want_code or want_sub not in line:
            fails.append(f"{name}: {code} {line!r}, ждали {want_code} {want_sub!r}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        repo = tmp / "repo"
        (repo / ".claude" / "plan").mkdir(parents=True)
        projects = tmp / "projects"
        d = projects / slug(repo.resolve())
        d.mkdir(parents=True)
        road = repo / ".claude" / "plan" / "roadmap.md"

        def head(*extra):
            road.write_text("---\nпроект: x\n" + "".join(e + "\n" for e in extra) + "---\n\n# План\n",
                            encoding="utf-8")

        head()
        check("нет журнала", measure(repo, projects, None), 3, "нет данных — нет журнала")
        (d / "a.jsonl").write_text('{"message": {"role": "user"}}\n', encoding="utf-8")
        check("без usage", measure(repo, projects, None), 3, "нет данных — в журнале нет usage")
        _journal(d / "a.jsonl", 30_000)
        check("под порогом", measure(repo, projects, None), 0, "30k из 200k · 15 % · порог 20 % · ок")
        _journal(d / "a.jsonl", 50_000)
        check("над порогом", measure(repo, projects, None), 1, "25 % · порог 20 % · порог")
        head("контекст: 30 %")
        check("своё значение", measure(repo, projects, None), 0, "порог 30 % · ок")
        head("окно: 1M")
        check("окно перекрывает", measure(repo, projects, None), 0, "50k из 1M · 5 % · порог 20 % · ок")
        head()
        _journal(d / "a.jsonl", 50_000, "gpt-unknown")
        check("неизвестная модель", measure(repo, projects, None), 1, "из 200k")
        _journal(d / "a.jsonl", 50_000, "claude-sonnet-4-5[1m]")
        check("суффикс [1m]", measure(repo, projects, None), 0, "из 1M")
        _journal(d / "a.jsonl", 109_000, "claude-opus-5-5")
        check("opus-5 — 1M", measure(repo, projects, None), 0, "109k из 1M · 11 %")
        _journal(d / "a.jsonl", 109_000, "claude-opus-4-8")
        check("opus-4-8 раньше opus-4", measure(repo, projects, None), 0, "из 1M")
        for m, w in [("claude-opus-4-6", "1M"), ("claude-sonnet-4-6", "1M"), ("claude-haiku-5-5", "1M"),
                     ("claude-fable-5-2", "1M"), ("claude-opus-4-5-20251101", "200k"),
                     ("claude-sonnet-4-5", "200k"), ("claude-3-7-sonnet", "200k")]:
            _journal(d / "a.jsonl", 10_000, m)
            check(f"окно {m}", measure(repo, projects, None), 0, f"из {w} ")
        _journal(d / "a.jsonl", 250_000, "claude-next-9")
        check("занято больше окна", measure(repo, projects, None), 1, "250k из 1M · 25 %")
        other = tmp / "other.jsonl"
        _journal(other, 190_000)
        check("--сессия", measure(repo, projects, other), 1, "190k из 200k")
    for f in fails:
        print("FAIL", f)
    print("самопроверка: " + ("провалена" if fails else "ок"))
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--projects", default=None, help="папка транскриптов (по умолчанию ~/.claude/projects)")
    ap.add_argument("--сессия", default=None, help="журнал .jsonl явно")
    ap.add_argument("--самопроверка", action="store_true")
    try:
        args = ap.parse_args()
    except SystemExit as e:
        return 2 if e.code else 0
    if args.самопроверка:
        return selftest()
    code, line = measure(Path(args.repo), Path(args.projects) if args.projects else None,
                         Path(args.сессия) if args.сессия else None)
    print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
