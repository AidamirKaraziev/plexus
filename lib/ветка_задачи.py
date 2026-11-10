#!/usr/bin/env python3
"""Ветка задачи от старта до main: завести, узнать где ты, влить.

Ветка живёт в папке человека (без worktree), всегда растёт от основной ветки.
Метка ветки задачи — git config `branch.<имя>.plexus-zadacha=<формулировка>`.

    python3 <корень Плексуса>/lib/ветка_задачи.py имя "<формулировка>"      # печатает транслит-имя
    python3 <корень Плексуса>/lib/ветка_задачи.py завести "<формулировка>"  # ветка от main; есть — переключает; чужая ветка задачи — код 2
    python3 <корень Плексуса>/lib/ветка_задачи.py где                       # `main` или `задача <ветка>` (+ формулировка второй строкой)
    python3 <корень Плексуса>/lib/ветка_задачи.py утвердить "<формулировка>" <файл>… [--сообщение "<текст>"]
        # коммит ТОЛЬКО перечисленных файлов; на main сначала заводит ветку задачи; на чужой ветке/detached — код 2;
        # прочие правки и проиндексированное остаются как были; менять нечего — «нечего коммитить», код 0
    python3 <корень Плексуса>/lib/ветка_задачи.py влить                     # merge --no-ff в main, ветка удаляется; конфликт — abort, код 2
    python3 <корень Плексуса>/lib/ветка_задачи.py --самопроверка

Общий ключ: `--repo <путь>` (по умолчанию текущая папка).
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

МАКС = 40
ТРАНСЛИТ = dict(zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "i", "k", "l", "m", "n", "o", "p",
     "r", "s", "t", "u", "f", "h", "c", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


class Отказ(Exception):
    """Понятный отказ: одна строка причины, код выхода 2."""


def имя(формулировка: str) -> str:
    s = "".join(ТРАНСЛИТ.get(c, c) for c in формулировка.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if len(s) > МАКС:
        обрезка = s[:МАКС]
        # по границе слова, если она не слишком близко к началу
        if s[МАКС] != "-" and "-" in обрезка and обрезка.rfind("-") > МАКС // 2:
            обрезка = обрезка[:обрезка.rfind("-")]
        s = обрезка.strip("-")
    if not s:
        raise Отказ("из формулировки не получилось имя ветки")
    return s


def git(repo, *args, ok=False):
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if r.returncode and not ok:
        raise Отказ(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()}")
    return r if ok else r.stdout.strip()


def есть_ветка(repo, b) -> bool:
    return git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{b}", ok=True).returncode == 0


def основная(repo) -> str:
    r = git(repo, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD", ok=True)
    if r.returncode == 0 and r.stdout.strip():
        b = r.stdout.strip().split("/", 1)[-1]
        if есть_ветка(repo, b):
            return b
    for b in ("main", "master"):
        if есть_ветка(repo, b):
            return b
    raise Отказ("не нашёл основную ветку (main или master)")


def текущая(repo) -> str:
    return git(repo, "symbolic-ref", "-q", "--short", "HEAD", ok=True).stdout.strip()


def метка(repo, b) -> str:
    return git(repo, "config", "--get", f"branch.{b}.plexus-zadacha", ok=True).stdout.strip()


def завести(repo, формулировка) -> str:
    b, main, cur = имя(формулировка), основная(repo), текущая(repo)
    if cur == b:
        return f"ты уже на ветке {b}"
    if cur != main:
        raise Отказ(f"ты на ветке {cur or 'без имени (detached HEAD)'} — сначала /plexus:end")
    грязно = bool(git(repo, "status", "--porcelain"))
    хвосты = "; хвосты переехали на ветку" if грязно else ""
    if есть_ветка(repo, b):
        git(repo, "switch", b)
        return f"ветка {b} уже была — продолжаем{хвосты}"
    git(repo, "switch", "-c", b)
    git(repo, "config", f"branch.{b}.plexus-zadacha", формулировка)
    return f"ветка {b} заведена от {main}{хвосты}"


def где(repo) -> str:
    cur, main = текущая(repo), основная(repo)
    if cur == main:
        return "main"
    м = метка(repo, cur)
    return f"задача {cur}" + (f"\n{м}" if м else "")


def влить(repo) -> str:
    main, cur = основная(repo), текущая(repo)
    if cur == main:
        raise Отказ("ты в основной ветке — вливать нечего")
    м = метка(repo, cur)
    if not м:
        raise Отказ(f"ветка {cur} не помечена как ветка задачи — не вливаю")
    git(repo, "switch", main)
    r = git(repo, "merge", "--no-ff", "-m", f"задача: {м}", cur, ok=True)
    if r.returncode:
        git(repo, "merge", "--abort", ok=True)
        git(repo, "switch", cur, ok=True)
        raise Отказ(f"конфликт при вливании {cur} в {main}; ветка не тронута")
    git(repo, "branch", "-d", cur)
    git(repo, "config", "--unset", f"branch.{cur}.plexus-zadacha", ok=True)
    return f"{cur} влита в {main}, ветка удалена"


def утвердить(repo, формулировка, файлы, сообщение=None) -> str:
    if not файлы:
        raise Отказ("не названы файлы для коммита")
    main, cur = основная(repo), текущая(repo)
    if cur != main and not (cur and метка(repo, cur)):
        raise Отказ(f"ты на ветке {cur or 'без имени (detached HEAD)'} — это не ветка задачи и не основная; "
                    "утверждение не коммичу")
    if not git(repo, "status", "--porcelain", "--", *файлы):
        return "нечего коммитить"
    заведена = завести(repo, формулировка) + "\n" if cur == main else ""
    git(repo, "add", "-A", "--", *файлы)
    # --only: в коммит идут только эти пути, остальной индекс не трогается
    git(repo, "commit", "-q", "--only", "-m", сообщение or f"утверждено: {формулировка}", "--", *файлы)
    return f"{заведена}закоммичено в {текущая(repo)}: {', '.join(файлы)}"


def самопроверка() -> int:
    def ск(cond, msg):
        if not cond:
            print(f"самопроверка: ПРОВАЛ — {msg}")
            sys.exit(1)

    ск(имя("Ветка задачи: от старта до main") == "vetka-zadachi-ot-starta-do-main", "транслит")
    ск(len(имя("очень длинная формулировка этапа которая не влезает в сорок символов")) <= МАКС, "длина")
    ск(имя("Щука — ёж") == "schuka-ezh", "щ/ё")
    with tempfile.TemporaryDirectory() as t:
        r = Path(t)
        for a in (["init", "-q", "-b", "master"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
            git(r, *a)
        (r / "a.txt").write_text("1\n")
        git(r, "add", "-A")
        git(r, "commit", "-qm", "init")
        ск(где(r) == "main", "где на основной")
        (r / "хвост.txt").write_text("x\n")
        o = завести(r, "Первая задача")
        b = имя("Первая задача")
        ск(текущая(r) == b and "хвосты переехали на ветку" in o, "завести с хвостами")
        ск(где(r).splitlines() == [f"задача {b}", "Первая задача"], "где на задаче")
        try:
            завести(r, "Вторая задача")
            ск(False, "чужая ветка должна давать отказ")
        except Отказ as e:
            ск("сначала /plexus:end" in str(e) and текущая(r) == b, "отказ на чужой ветке")
        ск("уже на ветке" in завести(r, "Первая задача"), "повтор на своей")
        git(r, "add", "-A")
        git(r, "commit", "-qm", "работа")
        влить(r)
        ск(текущая(r) == "master" and not есть_ветка(r, b), "влить + удалить ветку")
        ск(git(r, "log", "-1", "--format=%s") == "задача: Первая задача", "сообщение слияния")
        ск(len(git(r, "log", "-1", "--format=%P").split()) == 2, "no-ff коммит слияния")
        # существующая ветка → переключение
        старая = имя("Старая")
        git(r, "branch", старая)
        ск("продолжаем" in завести(r, "Старая") and текущая(r) == старая, "существующая")
        git(r, "switch", "master")
        # конфликт
        завести(r, "Конфликтная")
        k = имя("Конфликтная")
        (r / "a.txt").write_text("ветка\n")
        git(r, "commit", "-qam", "в ветке")
        git(r, "switch", "master")
        (r / "a.txt").write_text("main\n")
        git(r, "commit", "-qam", "в main")
        git(r, "switch", k)
        try:
            влить(r)
            ск(False, "конфликт должен давать отказ")
        except Отказ as e:
            ск("конфликт" in str(e), "причина конфликта")
        ск(текущая(r) == k and есть_ветка(r, k) and not git(r, "status", "--porcelain")
           and not (r / ".git" / "MERGE_HEAD").exists(), "после abort ветка цела")
    with tempfile.TemporaryDirectory() as t:
        r = Path(t)
        for a in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
            git(r, *a)
        (r / "a.txt").write_text("1\n")
        (r / "чужой.txt").write_text("1\n")
        git(r, "add", "-A")
        git(r, "commit", "-qm", "init")
        # хвосты: правка tracked, проиндексированная правка, untracked
        (r / "a.txt").write_text("2\n")
        (r / "чужой.txt").write_text("2\n")
        git(r, "add", "чужой.txt")
        (r / "хвост.txt").write_text("x\n")
        (r / "круг мой.md").write_text("круг\n")
        # 1. main -> ветка + коммит, только названный файл
        o = утвердить(r, "Новая задача", ["круг мой.md"])
        b = имя("Новая задача")
        ск(текущая(r) == b and метка(r, b) == "Новая задача" and "закоммичено" in o, "main→ветка")
        ск(git(r, "log", "-1", "--format=%s") == "утверждено: Новая задача", "сообщение по умолчанию")
        ск(git(r, "-c", "core.quotepath=false", "show", "--name-only", "--format=", "HEAD") == "круг мой.md",
           "в коммите только названный")
        # 4. чужие хвосты и индекс сохранились
        st = git(r, "-c", "core.quotepath=false", "status", "--porcelain")
        ск("M  чужой.txt" in st and "M a.txt" in st and "?? хвост.txt" in st, "хвосты и индекс целы")
        # 2. на ветке задачи, свой текст сообщения, файл с кириллицей
        (r / "заметка.md").write_text("н\n")
        утвердить(r, "Новая задача", ["заметка.md"], "своё сообщение")
        ск(текущая(r) == b and git(r, "log", "-1", "--format=%s") == "своё сообщение", "на ветке задачи")
        ск("M  чужой.txt" in git(r, "-c", "core.quotepath=false", "status", "--porcelain"),
           "индекс цел и после второго")
        # 5. нечего коммитить
        ск(утвердить(r, "Новая задача", ["заметка.md"]) == "нечего коммитить", "нечего коммитить")
        # 3. чужая ветка и detached -> отказ
        git(r, "switch", "-q", "-c", "левая")
        (r / "z.md").write_text("z\n")
        try:
            утвердить(r, "Х", ["z.md"])
            ск(False, "чужая ветка должна давать отказ")
        except Отказ as e:
            ск("не ветка задачи" in str(e), "причина чужой ветки")
        git(r, "switch", "-q", "--detach")
        try:
            утвердить(r, "Х", ["z.md"])
            ск(False, "detached должен давать отказ")
        except Отказ as e:
            ск("detached" in str(e), "причина detached")
    print("самопроверка: ок")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", default=".")
    p.add_argument("--самопроверка", action="store_true", dest="сам")
    p.add_argument("команда", nargs="?", choices=["имя", "завести", "где", "влить", "утвердить"])
    p.add_argument("формулировка", nargs="?")
    p.add_argument("файлы", nargs="*")
    p.add_argument("--сообщение", dest="сообщение")
    a = p.parse_args()
    if a.сам:
        return самопроверка()
    if not a.команда:
        p.error("нужна команда")
    try:
        if a.команда in ("имя", "завести", "утвердить") and not a.формулировка:
            raise Отказ("нужна формулировка")
        print({"имя": lambda: имя(a.формулировка or ""),
               "завести": lambda: завести(a.repo, a.формулировка),
               "утвердить": lambda: утвердить(a.repo, a.формулировка, a.файлы, a.сообщение),
               "где": lambda: где(a.repo),
               "влить": lambda: влить(a.repo)}[a.команда]())
    except Отказ as e:
        print(e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
