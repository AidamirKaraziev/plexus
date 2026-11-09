#!/usr/bin/env python3
"""Снести дорожки и ветки работников закрытого круга. Невлитое не трогает.

Дорожку работника заводит встроенный `isolation: "worktree"` Claude Code:
каталог `.claude/worktrees/<имя>`, ветка `claude/<имя>`. В Codex дорожку заводит
`lib/дорожка.py`: `.codex/worktrees/<имя>`, ветка `codex/<имя>`. Убирать их некому —
этим и занят этот скрипт (опознаёт оба префикса). Ветки `worktree-agent-*` тоже опознаются.

Сносится только то, что влито в текущую ветку человека (по содержимому: `git cherry`
пуст — перенос cherry-pick'ом тоже считается) и не имеет несохранённых правок.
Всё остальное остаётся и печатается с причиной. Ветку удаляет `branch -D`, но только
после своей проверки `git cherry`: `-d` смотрит на предков HEAD и после cherry-pick'а
отказывает. Сбой на одной дорожке не обрывает уборку остальных — она остаётся с причиной.

    python3 ${CLAUDE_PLUGIN_ROOT}/lib/уборка.py --сухой-прогон   # только показать
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/уборка.py                  # снести
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/уборка.py --забрать        # перенести коммиты «+» работников в ветку человека
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/уборка.py --забрать --сухой-прогон   # только показать, что перенёс бы

`--забрать`: для каждой ветки работника коммиты «+» из `git cherry <ветка человека> <ветка>`
переносятся cherry-pick'ом по порядку (целиком ветку вливать нельзя — она стоит на коммите
человека). Конфликт → `cherry-pick --abort`, код 2, имя ветки и коммита, дальше не идёт. Затем
обычная уборка видит ветку влитой. Без `--забрать` поведение прежнее.

    python3 ${CLAUDE_PLUGIN_ROOT}/lib/уборка.py --забрать --ветка <имя>    # забрать только одну ветку (после приёмки отчёта)

`--ветка <имя>` (только вместе с `--забрать`): переносит коммиты «+» одной этой ветки, остальные
не трогает; работает и с `--сухой-прогон`. Ветки нет → код 2 с причиной. Без `--ветка` забираются
все ветки работников (страховка для `/plexus:end`).
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


def ветка_человека(root: Path) -> str:
    """Текущая ветка main-checkout'а; при detached HEAD — HEAD."""
    return git("branch", "--show-current", cwd=root, check=False) or "HEAD"


def влита(ветка: str, root: Path) -> bool:
    """Влита по содержимому: в `git cherry <ветка человека> <ветка>` нет строк «+»."""
    r = subprocess.run(["git", "cherry", ветка_человека(root), ветка],
                       cwd=root, capture_output=True, text=True)
    return r.returncode == 0 and not any(l.startswith("+") for l in r.stdout.splitlines())


def снести_ветку(ветка: str, root: Path) -> None:
    """`branch -D` после проверки `git cherry`: невлитое не удаляется никогда."""
    if not влита(ветка, root):
        raise RuntimeError(f"не влита в {ветка_человека(root)}")
    git("branch", "-D", ветка, cwd=root)


def грязная(путь: Path, root: Path) -> bool:
    return bool(git("status", "--porcelain", cwd=путь, check=False))


def ветки_без_дорожек(root: Path, префикс: str, занятые: set[str]) -> list[str]:
    все = git("branch", "--list", f"{префикс}*", "--format=%(refname:short)", cwd=root)
    return [b for b in все.splitlines() if b and b not in занятые]


def ветки_работников(root: Path, префиксы: tuple) -> list[str]:
    """Все ветки работников (с дорожкой и без), по имени, без ветки человека."""
    человек = ветка_человека(root)
    все = git("branch", "--format=%(refname:short)", cwd=root).splitlines()
    return sorted(b for b in все if b.startswith(префиксы) and b != человек)


def забрать(root: Path, префиксы: tuple, сухой: bool, только: str | None = None) -> int:
    """Перенести коммиты «+» веток работников (или одной `только`) в ветку человека. 0 — ок, 2 — конфликт или нет ветки."""
    человек = ветка_человека(root)
    if только is not None:
        есть = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{только}"],
                              cwd=root, capture_output=True, text=True).returncode == 0
        if not есть:
            print(f"ОШИБКА: ветки {только} нет в {root}")
            return 2
        if только == человек:
            print(f"ОШИБКА: {только} — ветка человека, забирать из неё нечего")
            return 2
    print(f"{'СУХОЙ ПРОГОН — ничего не тронуто' if сухой else 'ЗАБРАТЬ'} · {root} → {человек}")
    нашёл = False
    for ветка in ([только] if только is not None else ветки_работников(root, префиксы)):
        r = subprocess.run(["git", "cherry", человек, ветка], cwd=root, capture_output=True, text=True)
        коммиты = [l[2:].strip() for l in r.stdout.splitlines() if l.startswith("+")]
        if not коммиты:
            continue
        нашёл = True
        if сухой:
            print(f"  забрал бы: {ветка} — коммитов {len(коммиты)}")
            continue
        for sha in коммиты:
            p = subprocess.run(["git", "cherry-pick", sha], cwd=root, capture_output=True, text=True)
            if p.returncode:
                subprocess.run(["git", "cherry-pick", "--abort"], cwd=root, capture_output=True, text=True)
                print(f"  КОНФЛИКТ: ветка {ветка}, коммит {sha[:7]} — cherry-pick отменён, дальше не иду")
                return 2
        print(f"  забрал: {ветка} — коммитов {len(коммиты)}")
    if not нашёл:
        print("  забирать нечего")
    return 0


def самопроверка_забрать() -> int:
    import os
    import tempfile
    os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp).resolve()
        repo = base / "repo"
        repo.mkdir()

        def g(*args, cwd=repo):
            return git(*args, cwd=cwd)

        def коммит(cwd, файл, текст, msg):
            (cwd / файл).write_text(текст)
            g("add", ".", cwd=cwd); g("commit", "-m", msg, cwd=cwd)

        g("init", "-b", "work")
        коммит(repo, "f", "0\n", "base")
        # работник с двумя коммитами
        g("worktree", "add", "-b", "claude/a", str(base / "wa"))
        коммит(base / "wa", "a1", "1\n", "a1"); коммит(base / "wa", "a2", "2\n", "a2")
        # уже влитая ветка (перенос cherry-pick'ом)
        g("worktree", "add", "-b", "claude/m", str(base / "wm"))
        коммит(base / "wm", "m", "m\n", "m")
        # конфликтующая: правит f иначе, чем work
        g("worktree", "add", "-b", "codex/c", str(base / "wc"))
        коммит(base / "wc", "f", "c\n", "c")
        # вторая чистая ветка: проверка «забрать одну из двух»
        g("worktree", "add", "-b", "claude/b", str(base / "wb"))
        коммит(base / "wb", "b1", "b\n", "b1")
        # человек правит f и сам забирает m
        коммит(repo, "f", "human\n", "human")
        g("cherry-pick", "claude/m")

        def прогон(*флаги):
            return subprocess.run([sys.executable, __file__, "--забрать", *флаги, "--репозиторий", str(repo)],
                                  capture_output=True, text=True)

        ошибки = []
        голова = g("rev-parse", "HEAD")
        r = прогон("--сухой-прогон")
        if r.returncode or g("rev-parse", "HEAD") != голова or "забрал бы: claude/a — коммитов 2" not in r.stdout:
            ошибки.append(f"сухой прогон: {r.stdout}{r.stderr}")
        if "claude/m" in r.stdout:
            ошибки.append("влитая ветка claude/m в списке переноса")

        r = прогон("--сухой-прогон", "--ветка", "claude/b")
        if r.returncode or "забрал бы: claude/b — коммитов 1" not in r.stdout or "claude/a" in r.stdout:
            ошибки.append(f"сухой прогон --ветка: {r.stdout}{r.stderr}")
        if g("rev-parse", "HEAD") != голова:
            ошибки.append("сухой прогон --ветка тронул HEAD")

        r = прогон("--ветка", "claude/a")
        if r.returncode or not all((repo / x).exists() for x in ("a1", "a2")) or "забрал: claude/a" not in r.stdout:
            ошибки.append(f"--ветка claude/a: код {r.returncode}: {r.stdout}{r.stderr}")
        if (repo / "b1").exists() or not any(l.startswith("+") for l in g("cherry", "work", "claude/b").splitlines()):
            ошибки.append("--ветка claude/a тронула вторую ветку claude/b")

        r = прогон("--ветка", "claude/нет")
        if r.returncode != 2 or "claude/нет" not in r.stdout:
            ошибки.append(f"ветки нет: код {r.returncode}: {r.stdout}{r.stderr}")

        r = прогон("--ветка", "codex/c")
        if r.returncode != 2 or "ветка codex/c, коммит" not in r.stdout:
            ошибки.append(f"--ветка конфликт: код {r.returncode}: {r.stdout}{r.stderr}")
        if (repo / ".git" / "CHERRY_PICK_HEAD").exists() or g("status", "--porcelain"):
            ошибки.append("после --ветка-конфликта остался cherry-pick или грязное дерево")

        r = прогон()
        if r.returncode != 2 or "КОНФЛИКТ: ветка codex/c" not in r.stdout:
            ошибки.append(f"конфликт: код {r.returncode}: {r.stdout}{r.stderr}")
        if (repo / ".git" / "CHERRY_PICK_HEAD").exists() or g("status", "--porcelain"):
            ошибки.append("после конфликта остался незавершённый cherry-pick или грязное дерево")
        if not all((repo / x).exists() for x in ("a1", "a2", "b1")) or (repo / "f").read_text() != "human\n":
            ошибки.append("перенос claude/a не прошёл или f испорчен")
        if any(l.startswith("+") for l in g("cherry", "work", "claude/a").splitlines()):
            ошибки.append("после переноса у claude/a остались «+»")
        if any(l.startswith("+") for l in g("cherry", "work", "claude/m").splitlines()):
            ошибки.append("влитая claude/m дала «+»")
        if not any(l.startswith("+") for l in g("cherry", "work", "codex/c").splitlines()):
            ошибки.append("конфликтная codex/c потеряла «+»")
        if ошибки:
            print("САМОПРОВЕРКА ПРОВАЛЕНА (забрать):", *ошибки, sep="\n")
            return 1
    print("самопроверка забрать: ок (сухой прогон, перенос, одна из двух, ветки нет, влитая, конфликт)")
    return 0


def самопроверка() -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp).resolve()
        repo = base / "repo"
        repo.mkdir()

        def g(*args, cwd=repo):
            return git("-c", "user.name=t", "-c", "user.email=t@t", *args, cwd=cwd)

        g("init", "-b", "work")
        (repo / "a").write_text("1\n")
        g("add", "."); g("commit", "-m", "base")
        # дорожка с коммитом, перенесённым в work cherry-pick'ом
        g("worktree", "add", "-b", "worktree-agent-abc", str(base / "w1"))
        (base / "w1" / "b").write_text("b\n")
        g("add", ".", cwd=base / "w1"); g("commit", "-m", "b", cwd=base / "w1")
        # свой коммит в work до переноса: иначе cherry-pick в ту же секунду даёт тот же SHA,
        # ветка становится предком HEAD, и сбой `branch -d` не воспроизводится
        (repo / "d").write_text("d\n")
        g("add", "."); g("commit", "-m", "d")
        g("cherry-pick", "worktree-agent-abc")
        # дорожка с невлитым коммитом
        g("worktree", "add", "-b", "claude/x", str(base / "w2"))
        (base / "w2" / "c").write_text("c\n")
        g("add", ".", cwd=base / "w2"); g("commit", "-m", "c", cwd=base / "w2")
        # ветки без дорожки: пустая (влита) и с невлитым коммитом
        g("branch", "worktree-agent-old")
        g("branch", "worktree-agent-new", "claude/x")

        r = subprocess.run([sys.executable, __file__, "--сухой-прогон", "--репозиторий", str(repo)],
                           capture_output=True, text=True)
        out = r.stdout
        ожидание = [
            "снёс бы: w1 · worktree-agent-abc",
            "оставил: w2 · claude/x — не влита в work",
            "снёс бы: — · worktree-agent-old (ветка без дорожки)",
            "оставил: — · worktree-agent-new — не влита в work",
        ]
        ошибки = [e for e in ожидание if e not in out]
        if "не влита в main" in out:
            ошибки.append("в выводе есть «не влита в main»")
        if ошибки:
            print("САМОПРОВЕРКА ПРОВАЛЕНА:", *ошибки, out, r.stderr, sep="\n")
            return 1

        # настоящий прогон: забранное cherry-pick'ом сносится без сбоя, невлитое остаётся
        r = subprocess.run([sys.executable, __file__, "--репозиторий", str(repo)],
                           capture_output=True, text=True)
        ветки = set(g("branch", "--format=%(refname:short)").splitlines())
        if r.returncode or "сбой" in r.stdout:
            ошибки.append("уборка упала или дала сбой")
        if ветки & {"worktree-agent-abc", "worktree-agent-old"}:
            ошибки.append(f"влитые ветки остались: {sorted(ветки)}")
        if not {"claude/x", "worktree-agent-new"} <= ветки:
            ошибки.append(f"невлитые ветки снесены: {sorted(ветки)}")
        if (base / "w1").exists() or not (base / "w2").exists():
            ошибки.append("дорожки w1/w2 не в том состоянии")
        if ошибки:
            print("САМОПРОВЕРКА ПРОВАЛЕНА:", *ошибки, r.stdout, r.stderr, sep="\n")
            return 1
    print("самопроверка: ок (4 случая сухим прогоном + настоящий прогон)")
    return самопроверка_забрать()


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--сухой-прогон", action="store_true", help="только показать, ничего не трогать")
    ap.add_argument("--префикс", action="append", help="префикс веток работников (по умолчанию claude/, codex/ и worktree-agent-)")
    ap.add_argument("--забрать", action="store_true", help="перенести коммиты «+» веток работников в ветку человека")
    ap.add_argument("--ветка", help="с --забрать: забрать только эту ветку работника")
    ap.add_argument("--репозиторий", default=".")
    ap.add_argument("--самопроверка", action="store_true", help="тест во временном репозитории")
    a = ap.parse_args()
    if getattr(a, "самопроверка"):
        return самопроверка()
    сухой = getattr(a, "сухой_прогон")
    префиксы = tuple(a.префикс or ["claude/", "codex/", "worktree-agent-"])

    root = main_root(Path(a.репозиторий).resolve())
    if a.ветка and not getattr(a, "забрать"):
        ap.error("--ветка работает только вместе с --забрать")
    if getattr(a, "забрать"):
        return забрать(root, префиксы, сухой, a.ветка)
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
            оставил.append(f"{д['путь'].name} · {ветка} — не влита в {ветка_человека(root)}")
            continue
        if not сухой:
            try:
                git("worktree", "remove", str(д["путь"]), cwd=root)
                снести_ветку(ветка, root)
            except RuntimeError as e:
                оставил.append(f"{д['путь'].name} · {ветка} — сбой: {e}")
                continue
        снёс.append(f"{д['путь'].name} · {ветка}")

    for ветка in [b for п in префиксы for b in ветки_без_дорожек(root, п, занятые)]:
        if not влита(ветка, root):
            оставил.append(f"— · {ветка} — не влита в {ветка_человека(root)}")
            continue
        if not сухой:
            try:
                снести_ветку(ветка, root)
            except RuntimeError as e:
                оставил.append(f"— · {ветка} — сбой: {e}")
                continue
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
