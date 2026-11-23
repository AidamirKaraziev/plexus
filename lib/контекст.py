#!/usr/bin/env python3
"""Замер контекста: сколько окна занято в последнем ответе самой свежей сессии.

Источник — самый свежий журнал между транскриптами Claude main-checkout'а
(~/.claude/projects/<slug>/), журналом OpenCode
(~/.local/share/opencode/plexus/projects/<slug>/<sessionID>.jsonl) и сессией
DSH (~/.dsh/sessions/<slug>/session-<uuid>/session.v4.jsonl.zstd): чей файл
новее по mtime, тот и источник. Claude: usage последнего ответа ассистента
(input + cache_creation + cache_read); OpenCode: максимум занятых токенов за
сессию (input + cache.read + cache.write) по всем usage-строкам файла; DSH:
максимум контекста шага (inputTokens + cacheReadTokens + cacheWriteTokens) по
шагам assistant/message с usage (журналы новее кладут его в step/end — берём и
оттуда), модель — в message.source или request/header. Настройка — строки в
шапке .claude/plan/roadmap.md:
`контекст: 20 %` (порог Claude, по умолчанию 20 %), `окно: 1M` (1M, 200k
или число; перекрывает таблицу окон по id модели; модель неизвестна → 200k,
а если занято больше окна — 1M) и `бюджет: 250k` (порог в токенах —
переопределяет порог в любой среде). Порог моделей OpenCode и DSH —
min(250k, 85 % × окно) (GLM → 25 %).

    python3 ${CLAUDE_PLUGIN_ROOT}/lib/контекст.py                      # свежая сессия
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/контекст.py --сессия <файл .jsonl | .jsonl.zstd | папка DSH | id>
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/контекст.py --repo <папка> --projects <папка транскриптов>
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/контекст.py --самопроверка

Печатает одну строку: `контекст: 182k из 1M · 18 % · порог 20 % · ок`.
Коды выхода: 0 — под порогом; 1 — порог перейдён; 2 — ошибка аргументов;
3 — нет данных (нет журнала или usage; строка `контекст: нет данных — <причина>`).
"""
import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spend import ДШ_ПАПКА, dsh_dirs, dsh_events, dsh_write, main_root, slug  # noqa: E402

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
# окна моделей OpenCode (журнал); порядок важен: flash выше базовой
OPENCODE_WINDOWS = [
    ("opencode-go/glm-5.3-flash", 1_000_000),
    ("opencode-go/glm-5.3", 1_000_000),
    ("glm-5.3-flash", 1_000_000),
    ("glm-5.3", 1_000_000),
]
OPENCODE_THRESHOLD_TOKENS = 250_000  # порог моделей OpenCode и DSH: min(250k, 85 % × окно)


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


def read_header(repo: Path) -> tuple[float, int | None, int | None]:
    """(порог в %, окно или None, бюджет в токенах или None) из frontmatter roadmap."""
    threshold, window, budget = DEFAULT_THRESHOLD, None, None
    path = repo / ".claude" / "plan" / "roadmap.md"
    if not path.exists():
        return threshold, window, budget
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return threshold, window, budget
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
        elif key == "бюджет":
            budget = parse_size(val) or budget
    return threshold, window, budget


def model_window(model: str | None) -> int:
    model = model or ""
    if "[1m]" in model.lower():
        return 1_000_000
    for prefix, size in OPENCODE_WINDOWS + WINDOWS:
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


def journal_usage(path: Path):
    """(максимум занятых токенов за сессию, модель) из журнала OpenCode, или None."""
    used_max, model = None, None
    with path.open(encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if '"session.usage.updated"' not in line and '"model"' not in line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            m = d.get("model")
            if isinstance(m, dict) and m.get("id"):
                model = m["id"]
            elif isinstance(m, str) and m:
                model = m
            if d.get("type") != "session.usage.updated":
                continue
            t = d.get("tokens") or {}
            c = t.get("cache") or {}
            used = t.get("input", 0) + c.get("read", 0) + c.get("write", 0)
            if used_max is None or used > used_max:  # пик уже записан, компактация ужмёт контекст
                used_max = used
    return None if used_max is None else (used_max, model)


def dsh_session(arg, dsh: Path | None = None):
    """(журнал DSH | None, «dsh» | None) по пути .zstd, папке сессии или её id."""
    p = Path(arg)
    if str(p).endswith((".zstd", ".zst")):
        return (p, "dsh") if p.is_file() else (None, None)
    if p.is_dir():
        fs = sorted((f for f in p.glob("session*.jsonl.zstd") if f.is_file()),
                    key=lambda f: f.stat().st_mtime)
        return (fs[-1], "dsh") if fs else (None, None)
    if p.is_file():
        return None, None  # .jsonl — источник решит разбор: opencode или claude
    root = Path(dsh) if dsh else ДШ_ПАПКА
    fs = [f for f in root.glob(f"*/*{p}*/session*.jsonl.zstd") if f.is_file()]
    return (max(fs, key=lambda f: f.stat().st_mtime), "dsh") if fs else (None, None)


def dsh_usage(path: Path):
    """(максимум контекста шага за сессию, модель) из журнала DSH, или None."""
    used_max, model = None, None
    for d in dsh_events(path):
        t, data = d.get("type"), d.get("data") or {}
        if t == "request/header":
            cfg = (data.get("header") or {}).get("config") or {}
            if cfg.get("model"):
                model = cfg["model"]
        elif t in ("assistant/message", "step/end"):
            if t == "assistant/message":
                src = (data.get("message") or {}).get("source") or {}
                if src.get("model"):
                    model = src["model"]
            u = data.get("usage")
            if not u:
                continue
            used = (u.get("inputTokens", 0) + u.get("cacheReadTokens", 0)
                    + u.get("cacheWriteTokens", 0))
            if used_max is None or used > used_max:  # пик уже записан, компакция ужмёт контекст
                used_max = used
    return None if used_max is None else (used_max, model)


def _opencode_root(repo: Path) -> Path:
    try:
        root = main_root(repo)
    except Exception:
        root = repo.resolve()
    return root


def newest_journal(repo: Path, projects: Path | None, opencode: Path | None = None,
                   dsh: Path | None = None):
    """(файл, источник) — самый свежий журнал между транскриптами Claude,
    журналом OpenCode и сессиями DSH."""
    projects = projects or Path.home() / ".claude" / "projects"
    opencode = opencode or Path.home() / ".local" / "share" / "opencode" / "plexus"
    s = slug(_opencode_root(repo))

    def newest(d: Path, pat: str = "*.jsonl"):
        files = (sorted((f for f in d.glob(pat) if f.is_file()),
                        key=lambda f: f.stat().st_mtime) if d.is_dir() else [])
        return files[-1] if files else None

    candidates = [(f, src) for f, src in
                  ((newest(projects / s), "claude"), (newest(opencode / "projects" / s), "opencode"))
                  if f]
    for pd in dsh_dirs(repo, Path(dsh) if dsh else ДШ_ПАПКА):
        f = newest(pd, "session-*/session*.jsonl.zstd")
        if f:
            candidates.append((f, "dsh"))
    if not candidates:
        return None, "claude"
    return max(candidates, key=lambda fs: fs[0].stat().st_mtime)


def measure(repo: Path, projects: Path | None, session,
            opencode: Path | None = None, dsh: Path | None = None) -> tuple[int, str]:
    if session is not None:
        journal, is_dsh = dsh_session(session, dsh)
        if is_dsh:
            source = "dsh"
        else:
            journal = Path(session)
            source = ("opencode" if journal.is_file() and '"session.usage.updated"' in
                      journal.read_text(encoding="utf-8", errors="ignore") else "claude")
    else:
        journal, source = newest_journal(repo, projects, opencode, dsh)
    if journal is None or not journal.is_file():
        return 3, "контекст: нет данных — нет журнала сессии"
    usage = (dsh_usage(journal) if source == "dsh" else
             journal_usage(journal) if source == "opencode" else last_usage(journal))
    if usage is None:
        return 3, "контекст: нет данных — в журнале нет usage"
    used, model = usage
    threshold_hdr, window_hdr, budget = read_header(repo)
    window = window_hdr or model_window(model)
    if used > window:  # таблица отстала: занято больше окна — значит окно 1M
        window = max(window, 1_000_000)
    if budget is not None:  # бюджет из шапки переопределяет порог в любой среде
        threshold = budget / window * 100
    elif source in ("opencode", "dsh"):  # модели Go: порог в токенах, не в долях окна
        threshold = min(OPENCODE_THRESHOLD_TOKENS, 0.85 * window) / window * 100
    else:
        threshold = threshold_hdr
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


def _oc_journal(path: Path, usages, model: str = "glm-5.3"):
    """Журнал OpenCode: usage-строки с заданными занятыми токенами."""
    rows = [{"ts": 1, "sessionID": "s1", "type": "session.started",
             "model": {"id": model, "providerID": "opencode-go"}}]
    for i, u in enumerate(usages):
        rows.append({"ts": i + 2, "sessionID": "s1", "type": "session.usage.updated",
                     "tokens": {"input": u - 100, "output": 5, "reasoning": 0,
                                "cache": {"read": 100, "write": 0}}})
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

        # журнал OpenCode: фикстуры во временных папках, живое не трогаем
        stamp = [1_700_000_000]

        def touch(p):  # управляем свежестью: чей файл новее по mtime, тот и источник
            stamp[0] += 100
            os.utime(p, (stamp[0], stamp[0]))

        oc = tmp / "oc"
        od = oc / "projects" / slug(repo.resolve())
        od.mkdir(parents=True)
        touch(d / "a.jsonl")
        _oc_journal(od / "s1.jsonl", [100_000, 200_000, 150_000])  # максимум за сессию — 200k
        touch(od / "s1.jsonl")
        check("журнал свежее транскрипта", measure(repo, projects, None, oc), 0,
              "200k из 1M · 20 % · порог 25 % · ок")
        check("явный журнал opencode", measure(repo, projects, od / "s1.jsonl"), 0,
              "порог 25 % · ок")
        touch(d / "a.jsonl")
        check("транскрипт свежее журнала", measure(repo, projects, None, oc), 1,
              "250k из 1M · 25 % · порог 20 % · порог")
        touch(od / "s1.jsonl")
        _oc_journal(od / "s2.jsonl", [180_000], "vendor-x")  # окно 200k → порог min(250k, 85 %) = 85 %
        touch(od / "s2.jsonl")
        check("адаптивный порог", measure(repo, projects, None, oc), 1,
              "180k из 200k · 90 % · порог 85 % · порог")
        _oc_journal(od / "s3.jsonl", [300_000], "opencode-go/glm-5.3")
        touch(od / "s3.jsonl")
        check("окно префикса opencode-go", measure(repo, projects, None, oc), 1,
              "300k из 1M · 30 % · порог 25 % · порог")
        _oc_journal(od / "s4.jsonl", [500_000], "glm-5.3-flash")
        touch(od / "s4.jsonl")
        check("окно glm-5.3-flash", measure(repo, projects, None, oc), 1,
              "500k из 1M · 50 % · порог 25 % · порог")
        head("бюджет: 100k")
        check("бюджет перекрывает порог", measure(repo, projects, None, oc), 1,
              "500k из 1M · 50 % · порог 10 % · порог")
        _journal(d / "a.jsonl", 120_000, "claude-haiku-4-5-20251001")
        touch(d / "a.jsonl")
        check("бюджет и у Claude", measure(repo, projects, None, oc), 1,
              "120k из 200k · 60 % · порог 50 % · порог")
        head()
        check("бюджет снят — снова 20 %", measure(repo, projects, None, oc), 1,
              "120k из 200k · 60 % · порог 20 % · порог")
        _oc_journal(od / "s5.jsonl", [50_000], "glm-5.3")  # голый id без префикса
        touch(od / "s5.jsonl")
        check("окно голого glm-5.3", measure(repo, projects, None, oc), 0,
              "50k из 1M · 5 % · порог 25 % · ок")

        # сессии DSH: фикстуры сжимаются zstd во временной папке, живое ~/.dsh не трогаем
        дш = tmp / "дш"
        дд = дш / f"-{slug(repo.resolve())}--" / "session-99999999-aaaa-4f3d-bbea-414ab84e7989"
        дд.mkdir(parents=True)
        шаг = [{"type": "session", "version": 4, "id": "session-99999999-aaaa-4f3d-bbea-414ab84e7989",
                "createdAt": 1_700_000_000_000, "cwd": str(repo)},
               {"type": "request/header", "seq": 0, "time": 1_700_000_000_000,
                "data": {"header": {"config": {"provider": "opencode-go", "model": "glm-5.3"}}}}]
        for i, u in enumerate([
                {"inputTokens": 100_000, "cacheReadTokens": 50_000, "cacheWriteTokens": 0,
                 "outputTokens": 10},
                {"inputTokens": 40_000, "cacheReadTokens": 160_000, "cacheWriteTokens": 0,
                 "outputTokens": 10}], 1):
            шаг += [{"type": "assistant/message", "seq": i, "time": 1_700_000_000_000 + i * 60_000,
                     "data": {"turn": 1, "step": i,
                              "message": {"source": {"model": "glm-5.3", "provider": "opencode-go"}},
                              "usage": u}},
                    {"type": "step/end", "seq": i + 10, "time": 1_700_000_000_000 + i * 60_000 + 100,
                     "data": {"turn": 1, "step": i, "usage": u}}]  # дубль — не раздувает максимум
        if dsh_write(дд / "session.v4.jsonl.zstd", шаг):
            touch(дд / "session.v4.jsonl.zstd")
            check("сессия DSH свежее журнала", measure(repo, projects, None, oc, дш), 0,
                  "200k из 1M · 20 % · порог 25 % · ок")
            check("журнал .zstd", measure(repo, projects, дд / "session.v4.jsonl.zstd", oc, дш), 0,
                  "200k из 1M · 20 % · порог 25 % · ок")
            check("папка сессии DSH", measure(repo, projects, дд, oc, дш), 0,
                  "200k из 1M · 20 % · порог 25 % · ок")
            check("id сессии DSH", measure(repo, projects, "99999999", oc, дш), 0,
                  "200k из 1M · 20 % · порог 25 % · ок")
            touch(d / "a.jsonl")
            check("транскрипт свежее сессии DSH", measure(repo, projects, None, oc, дш), 1,
                  "120k из 200k · 60 % · порог 20 % · порог")
        else:
            print("пропуск: нет ни zstandard, ни zstd — источник DSH не проверить")
    for f in fails:
        print("FAIL", f)
    print("самопроверка: " + ("провалена" if fails else "ок"))
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--projects", default=None, help="папка транскриптов (по умолчанию ~/.claude/projects)")
    ap.add_argument("--сессия", default=None,
                    help="журнал .jsonl/.zstd, папка сессии DSH или её id")
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
