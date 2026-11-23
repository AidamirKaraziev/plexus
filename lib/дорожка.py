#!/usr/bin/env python3
"""Завести дорожку работника в Codex или OpenCode: git worktree вне глаз человека, своя ветка.

В Claude Code дорожку заводит `isolation: "worktree"`; в Codex и OpenCode такого
механизма нет, поэтому её заводит этот скрипт. Среда — `--среда codex` (по
умолчанию) или `--среда opencode`: каталог — `<репо>/<.codex|.opencode>/worktrees/<имя>`,
ветка — `<codex|opencode>/<имя>` от текущего коммита main-checkout'а. Каталог среды
(`.codex/`, `.opencode/`) вносится в `.git/info/exclude`, так что `git status` в main
дорожек не показывает, а .gitignore проекта не правится. Человек остаётся в main.

    python3 <корень Плексуса>/lib/дорожка.py завести <имя> [--репозиторий .]      # codex: печатает путь дорожки
    python3 <корень Плексуса>/lib/дорожка.py путь <имя>                          # путь без создания
    python3 <корень Плексуса>/lib/дорожка.py --среда opencode завести <имя>       # .opencode/worktrees/<имя>, ветка opencode/<имя>
    python3 <корень Плексуса>/lib/дорожка.py --среда opencode путь <имя>         # путь без создания
    python3 <корень Плексуса>/lib/дорожка.py --самопроверка                       # тест во временном репозитории

Убирает дорожки `lib/уборка.py` (опознаёт префиксы `codex/` и `opencode/`, сносит только влитые).
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

# среда: префикс ветки и папка дорожек внутри репо
СРЕДЫ = {"codex": ("codex/", ".codex"), "opencode": ("opencode/", ".opencode")}


def git(*args, cwd) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def корень_main(старт: Path) -> Path:
    """Первая строка `git worktree list` — main-checkout, даже изнутри дорожки."""
    первая = git("worktree", "list", "--porcelain", cwd=старт).splitlines()[0]
    return Path(первая.split(" ", 1)[1])


def скрыть(root: Path, папка: str) -> None:
    """`<папка>/` в .git/info/exclude (общий для всех дорожек), если ещё нет."""
    общий = Path(git("rev-parse", "--git-common-dir", cwd=root))
    if not общий.is_absolute():
        общий = root / общий
    файл = общий / "info" / "exclude"
    файл.parent.mkdir(parents=True, exist_ok=True)
    текст = файл.read_text() if файл.exists() else ""
    if f"{папка}/" not in текст.splitlines():
        файл.write_text(текст + ("" if текст.endswith("\n") or not текст else "\n") + f"{папка}/\n")


def самопроверка() -> int:
    import os
    import tempfile
    os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                      GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp).resolve()
        repo = base / "repo"
        repo.mkdir()

        def g(*args, cwd=repo):
            return git(*args, cwd=cwd)

        def прогон(*args, репозиторий=None):
            return subprocess.run([sys.executable, __file__, *args, "--репозиторий",
                                   str(репозиторий or repo)], capture_output=True, text=True)

        g("init", "-b", "work")
        (repo / "a").write_text("1\n")
        g("add", "."); g("commit", "-m", "base")
        голова = g("rev-parse", "HEAD")
        exclude = repo / ".git" / "info" / "exclude"

        def строки_исключ() -> list[str]:
            return exclude.read_text().splitlines() if exclude.exists() else []

        ошибки = []

        # «путь» печатает путь и ничего не создаёт: без --среда, с codex, с opencode
        for арги, папка in ((("путь", "x"), ".codex"),
                            (("--среда", "codex", "путь", "x"), ".codex"),
                            (("--среда", "opencode", "путь", "x"), ".opencode")):
            r = прогон(*арги)
            if r.returncode or r.stdout.strip() != str(repo / папка / "worktrees" / "x"):
                ошибки.append(f"{' '.join(арги)}: код {r.returncode}: {r.stdout}{r.stderr}")
        if (repo / ".codex").exists() or (repo / ".opencode").exists():
            ошибки.append("«путь» создал каталог")
        if {".codex/", ".opencode/"} & set(строки_исключ()):
            ошибки.append("«путь» тронул .git/info/exclude")

        # плохое имя — код 2, без --среда и с ней
        for арги in (("завести", "плохое имя"), ("--среда", "opencode", "завести", "плохое имя")):
            r = прогон(*арги)
            if r.returncode != 2:
                ошибки.append(f"плохое имя ({' '.join(арги)}): код {r.returncode}, ждал 2")

        # завод: путь напечатан, каталог существует, ветка на HEAD человека,
        # строка среды в exclude, чистый git status в main
        def проверить_завод(r, среда: str, имя: str) -> None:
            префикс, папка = СРЕДЫ[среда]
            путь = repo / папка / "worktrees" / имя
            if r.returncode:
                ошибки.append(f"завод {имя}: код {r.returncode}: {r.stdout}{r.stderr}")
                return
            if r.stdout.strip() != str(путь):
                ошибки.append(f"завод {имя} напечатал {r.stdout.strip()!r}, ждал {путь}")
            if not путь.is_dir():
                ошибки.append(f"завод {имя}: нет каталога {путь}")
            if f"{папка}/" not in строки_исключ():
                ошибки.append(f"завод {имя}: {папка}/ нет в .git/info/exclude")
            if g("rev-parse", префикс + имя) != голова:
                ошибки.append(f"завод {имя}: ветка {префикс}{имя} не на HEAD человека")
            if g("status", "--porcelain"):
                ошибки.append(f"завод {имя}: git status в main не чист")

        проверить_завод(прогон("--среда", "opencode", "завести", "op"), "opencode", "op")
        проверить_завод(прогон("завести", "cx"), "codex", "cx")
        проверить_завод(прогон("--среда", "codex", "завести", "cx2"), "codex", "cx2")

        # повторный завод — отказ
        for арги in (("--среда", "opencode", "завести", "op"), ("завести", "cx")):
            r = прогон(*арги)
            if r.returncode != 1 or "уже есть" not in r.stderr:
                ошибки.append(f"повторный завод {' '.join(арги)}: код {r.returncode}: {r.stdout}{r.stderr}")

        # завод изнутри дорожки находит main-checkout
        проверить_завод(прогон("--среда", "opencode", "завести", "изнутри",
                               репозиторий=repo / ".opencode" / "worktrees" / "op"),
                        "opencode", "изнутри")

        if ошибки:
            print("САМОПРОВЕРКА ПРОВАЛЕНА:", *ошибки, sep="\n")
            return 1
    print("самопроверка: ок (путь без создания, плохое имя — 2, заводы opencode и codex "
          "с флагом и без, повторный завод — отказ, завод изнутри дорожки)")
    return 0


def main() -> int:
    if "--самопроверка" in sys.argv:
        return самопроверка()
    ap = argparse.ArgumentParser()
    ap.add_argument("--среда", choices=sorted(СРЕДЫ), default="codex",
                    help="среда дорожки: codex или opencode (по умолчанию codex)")
    ap.add_argument("команда", choices=["завести", "путь"])
    ap.add_argument("имя")
    ap.add_argument("--репозиторий", default=".")
    a = ap.parse_args()
    префикс, папка = СРЕДЫ[a.среда]
    if not re.fullmatch(r"[\w.-]+", a.имя):
        print("✘ имя дорожки: буквы, цифры, «.», «-», «_»", file=sys.stderr)
        return 2
    try:
        root = корень_main(Path(a.репозиторий).resolve())
        путь = root / папка / "worktrees" / a.имя
        if a.команда == "путь":
            print(путь)
            return 0
        if путь.exists():
            print(f"✘ дорожка уже есть: {путь}", file=sys.stderr)
            return 1
        скрыть(root, папка)
        путь.parent.mkdir(parents=True, exist_ok=True)
        git("worktree", "add", "-b", префикс + a.имя, str(путь), "HEAD", cwd=root)
    except RuntimeError as e:
        print(f"✘ {e}", file=sys.stderr)
        return 1
    print(путь)
    return 0


if __name__ == "__main__":
    sys.exit(main())
