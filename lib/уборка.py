#!/usr/bin/env python3
"""Снести дорожки и ветки работников закрытого круга. Невлитое не трогает.

Дорожку работника заводит встроенный `isolation: "worktree"` Claude Code:
каталог `.claude/worktrees/<имя>`, ветка `claude/<имя>`. В Codex дорожку заводит
`lib/дорожка.py`: `.codex/worktrees/<имя>`, ветка `codex/<имя>`. Убирать их некому —
этим и занят этот скрипт (опознаёт оба префикса).

Сносится только то, что влито в main и не имеет несохранённых правок.
Всё остальное остаётся и печатается с причиной.

    python3 ${CLAUDE_PLUGIN_ROOT}/lib/уборка.py --сухой-прогон   # только показать
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/уборка.py                  # снести
"""
import argparse
import subprocess
import sys
from pathlib import Path


def main_root(start: Path) -> Path:
    """Корень main-checkout'а — первая строка `git worktree list`, даже изнутри дорожки."""
    r = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=start, capture_output=True, text=True)
    return Path(r.stdout.splitlines()[0].split(" ", 1)[1])


def git(*args, cwd, check=True) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def дорожки(root: Path) -> list[dict]:
    """Из `git worktree list --porcelain`: путь и ветка каждой дорожки, кроме main-checkout."""
    out, текущая = [], {}
    for строка in git("worktree", "list", "--porcelain", cwd=root).splitlines() + [""]:
        if not строка:
            if текущая.get("путь") and текущая["путь"] != root:
                out.append(текущая)
            текущая = {}
        elif строка.startswith("worktree "):
            текущая["путь"] = Path(строка.split(" ", 1)[1])
        elif строка.startswith("branch "):
            текущая["ветка"] = строка.split(" ", 1)[1].removeprefix("refs/heads/")
    return out


def влита(ветка: str, root: Path) -> bool:
    r = subprocess.run(["git", "merge-base", "--is-ancestor", ветка, "main"],
                       cwd=root, capture_output=True)
    return r.returncode == 0


def грязная(путь: Path, root: Path) -> bool:
    return bool(git("status", "--porcelain", cwd=путь, check=False))


def ветки_без_дорожек(root: Path, префикс: str, занятые: set[str]) -> list[str]:
    все = git("branch", "--list", f"{префикс}*", "--format=%(refname:short)", cwd=root)
    return [b for b in все.splitlines() if b and b not in занятые]


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--сухой-прогон", action="store_true", help="только показать, ничего не трогать")
    ap.add_argument("--префикс", action="append", help="префикс веток работников (по умолчанию claude/ и codex/)")
    ap.add_argument("--репозиторий", default=".")
    a = ap.parse_args()
    сухой = getattr(a, "сухой_прогон")
    префиксы = tuple(a.префикс or ["claude/", "codex/"])

    root = main_root(Path(a.репозиторий).resolve())
    снёс, оставил = [], []
    занятые = set()

    for д in дорожки(root):
        ветка = д.get("ветка", "")
        занятые.add(ветка)
        если_чужая = not ветка.startswith(префиксы)
        if если_чужая:
            оставил.append(f"{д['путь'].name} · {ветка or 'без ветки'} — не дорожка работника")
            continue
        if грязная(д["путь"], root):
            оставил.append(f"{д['путь'].name} · {ветка} — есть несохранённые правки")
            continue
        if not влита(ветка, root):
            оставил.append(f"{д['путь'].name} · {ветка} — не влита в main")
            continue
        if not сухой:
            git("worktree", "remove", str(д["путь"]), cwd=root)
            git("branch", "-d", ветка, cwd=root)
        снёс.append(f"{д['путь'].name} · {ветка}")

    for ветка in [b for п in префиксы for b in ветки_без_дорожек(root, п, занятые)]:
        if not влита(ветка, root):
            оставил.append(f"— · {ветка} — не влита в main")
            continue
        if not сухой:
            git("branch", "-d", ветка, cwd=root)
        снёс.append(f"— · {ветка} (ветка без дорожки)")

    if not сухой:
        git("worktree", "prune", cwd=root)

    шапка = "СУХОЙ ПРОГОН — ничего не тронуто" if сухой else "УБОРКА"
    print(f"{шапка} · {root}")
    for строка in снёс:
        print(f"  {'снёс бы' if сухой else 'снёс'}: {строка}")
    for строка in оставил:
        print(f"  оставил: {строка}")
    if not снёс and not оставил:
        print("  дорожек работников нет")
    return 0


if __name__ == "__main__":
    sys.exit(main())
