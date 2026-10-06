#!/usr/bin/env python3
"""Завести дорожку работника в Codex: git worktree вне глаз человека, своя ветка.

В Claude Code дорожку заводит `isolation: "worktree"`; в Codex такого механизма нет,
поэтому её заводит этот скрипт. Каталог — `<репо>/.codex/worktrees/<имя>`, ветка —
`codex/<имя>` от текущего коммита main-checkout'а. `.codex/` вносится в
`.git/info/exclude`, так что `git status` в main дорожек не показывает, а
.gitignore проекта не правится. Человек остаётся в main.

    python3 <корень Плексуса>/lib/дорожка.py завести <имя> [--репозиторий .]   # печатает путь дорожки
    python3 <корень Плексуса>/lib/дорожка.py путь <имя>                        # путь без создания

Убирает дорожки `lib/уборка.py` (опознаёт префикс `codex/`, сносит только влитые).
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ПРЕФИКС = "codex/"
ПАПКА = Path(".codex") / "worktrees"


def git(*args, cwd) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def корень_main(старт: Path) -> Path:
    """Первая строка `git worktree list` — main-checkout, даже изнутри дорожки."""
    первая = git("worktree", "list", "--porcelain", cwd=старт).splitlines()[0]
    return Path(первая.split(" ", 1)[1])


def скрыть(root: Path) -> None:
    """`.codex/` в .git/info/exclude (общий для всех дорожек), если ещё нет."""
    общий = Path(git("rev-parse", "--git-common-dir", cwd=root))
    if not общий.is_absolute():
        общий = root / общий
    файл = общий / "info" / "exclude"
    файл.parent.mkdir(parents=True, exist_ok=True)
    текст = файл.read_text() if файл.exists() else ""
    if ".codex/" not in текст.splitlines():
        файл.write_text(текст + ("" if текст.endswith("\n") or not текст else "\n") + ".codex/\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("команда", choices=["завести", "путь"])
    ap.add_argument("имя")
    ap.add_argument("--репозиторий", default=".")
    a = ap.parse_args()
    if not re.fullmatch(r"[\w.-]+", a.имя):
        print("✘ имя дорожки: буквы, цифры, «.», «-», «_»", file=sys.stderr)
        return 2
    try:
        root = корень_main(Path(a.репозиторий).resolve())
        путь = root / ПАПКА / a.имя
        if a.команда == "путь":
            print(путь)
            return 0
        if путь.exists():
            print(f"✘ дорожка уже есть: {путь}", file=sys.stderr)
            return 1
        скрыть(root)
        путь.parent.mkdir(parents=True, exist_ok=True)
        git("worktree", "add", "-b", ПРЕФИКС + a.имя, str(путь), "HEAD", cwd=root)
    except RuntimeError as e:
        print(f"✘ {e}", file=sys.stderr)
        return 1
    print(путь)
    return 0


if __name__ == "__main__":
    sys.exit(main())
