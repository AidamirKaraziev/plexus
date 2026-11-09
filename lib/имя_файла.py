#!/usr/bin/env python3
"""Имя файла, которое откроется в любой ОС.

Имена, которые заводит ИИ (заметки, передачи), проходят этот модуль.
Запрещены: < > : " / \\ | ? *, управляющие символы, точка или пробел
в конце, имена CON PRN AUX NUL COM1-9 LPT1-9 (без учёта регистра
и расширения). Плохое имя не исправляется молча — только причина.

    python3 lib/имя_файла.py --проверить <папка>   плохие имена с причиной
    python3 lib/имя_файла.py --переименовать <vault> [--сухой]
                                         починить плохие имена и [[ссылки]]
    python3 lib/имя_файла.py --самопроверка

Из кода:  from имя_файла import проверить;  проверить("a:b.md") -> причина | None
          from имя_файла import исправить;  исправить("a:b.md") -> "a - b.md"

Починка: «:» → « - » (пробелы вокруг схлопнуты); < > " | ? * и управляющие → «_»;
точки и пробелы в конце срезаются; зарезервированная основа → «<основа>_».

Выход: 0 — всё в порядке; 2 — есть плохие имена (список в stdout)
или переименование невозможно (имена сходятся в одно / новое уже занято).
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ЗАПРЕЩЁННЫЕ = '<>:"/\\|?*'
ЗАРЕЗЕРВИРОВАНО = {"CON", "PRN", "AUX", "NUL",
                   *(f"COM{n}" for n in range(1, 10)),
                   *(f"LPT{n}" for n in range(1, 10))}
УПРАВЛЯЮЩИЕ = re.compile(r"[\x00-\x1f\x7f]")


def проверить(имя: str) -> "str | None":
    """Причина, почему имя плохое, или None."""
    if not имя:
        return "пустое имя"
    for с in имя:
        if с in ЗАПРЕЩЁННЫЕ:
            return f"запрещённый символ «{с}»"
    if УПРАВЛЯЮЩИЕ.search(имя):
        return "управляющий символ"
    if имя[-1] == ".":
        return "точка в конце"
    if имя[-1] == " ":
        return "пробел в конце"
    основа = имя.split(".", 1)[0].rstrip(" ")
    if основа.upper() in ЗАРЕЗЕРВИРОВАНО:
        return f"зарезервированное имя «{основа}»"
    return None


def проверить_папку(папка: Path) -> list:
    """[(путь относительно папки, причина)] по всем файлам и папкам."""
    плохие = []
    for p in sorted(папка.rglob("*")):
        причина = проверить(p.name)
        if причина:
            плохие.append((p.relative_to(папка).as_posix(), причина))
    return плохие


def исправить(имя: str) -> str:
    """Имя, которое проходит `проверить`; хорошее имя возвращается как есть."""
    for _ in range(5):
        if проверить(имя) is None:
            return имя
        имя = re.sub(r"\s*:\s*", " - ", имя)
        имя = re.sub(r'[<>"|?*\x00-\x1f\x7f]', "_", имя)
        имя = имя.rstrip(". ")
        сырая = имя.split(".", 1)[0]
        if сырая.rstrip(" ").upper() in ЗАРЕЗЕРВИРОВАНО:
            имя = сырая.rstrip(" ") + "_" + имя[len(сырая):]
        if not имя:
            имя = "_"
    return имя


def _ключ(путь: tuple) -> tuple:
    return tuple(ч.casefold() for ч in путь)


def план_переименования(корень: Path):
    """([(старый путь-кортеж, новый путь-кортеж)], [ошибки]); глубже сначала.

    Путь — части относительно корня; в новом пути исправлены и родители."""
    записи = sorted((p.relative_to(корень).parts for p in корень.rglob("*")),
                    key=lambda ч: (-len(ч), ч))
    новые = {ч: tuple(исправить(к) for к in ч) for ч in записи}
    ошибки = []
    занято = {}
    for ч, н in новые.items():
        занято.setdefault(_ключ(н), []).append(ч)
    for источники in занято.values():
        if len(источники) > 1:
            список = ", ".join("/".join(i) for i in источники)
            ошибки.append(f"имена сходятся в «{'/'.join(новые[источники[0]])}»: {список}")
    план = [(ч, новые[ч]) for ч in записи if новые[ч] != ч]
    return план, ошибки


def _чинить_ссылки(текст: str, стебли: dict) -> str:
    def замена(m):
        цель, хвост = m.group(1), m.group(2) or ""
        части = цель.split("/")
        последняя = части[-1]
        суффикс = ""
        if последняя.endswith(".md"):
            последняя, суффикс = последняя[:-3], ".md"
        части = [исправить(ч) if проверить(ч) else ч for ч in части[:-1]]
        части.append(стебли.get(последняя, последняя) + суффикс)
        return "[[" + "/".join(части) + хвост + "]]"
    return re.sub(r"\[\[([^\]|#]*)([|#][^\]]*)?\]\]", замена, текст)


def переименовать(корень: Path, сухой: bool) -> int:
    план, ошибки = план_переименования(корень)
    if ошибки:
        for о in ошибки:
            print(о)
        print("переименовывать нельзя, на диске ничего не изменено")
        return 2
    if not план:
        print("нечего переименовывать")
        return 0
    for ст, нов in план:
        print(f"{'/'.join(ст)} → {'/'.join(нов)}")
    if сухой:
        return 0
    стебли = {}
    for ст, нов in план:
        if ст[-1].endswith(".md") and нов[-1].endswith(".md"):
            стебли.setdefault(ст[-1][:-3], нов[-1][:-3])
    for ст, нов in план:
        # глубже сначала: родители ещё в старых именах
        корень.joinpath(*ст).rename(корень.joinpath(*ст[:-1], нов[-1]))
    изменено = 0
    for f in sorted(корень.rglob("*.md")):
        if not f.is_file() or ".git" in f.relative_to(корень).parts:
            continue
        try:
            т = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        н = _чинить_ссылки(т, стебли)
        if н != т:
            f.write_text(н, encoding="utf-8")
            изменено += 1
    print(f"переименовано: {len(план)}, файлов со ссылками исправлено: {изменено}")
    return 0


def самопроверка() -> int:
    ошибки = []

    def ждём(имя, есть):
        р = проверить(имя)
        if (р is not None) != есть:
            ошибки.append(f"{имя!r}: ждали {'причину' if есть else 'None'}, получили {р!r}")

    for с in ЗАПРЕЩЁННЫЕ:
        ждём(f"а{с}б.md", True)
    ждём("а\x00б", True)
    ждём("а\tб", True)
    ждём("а\x7fб", True)
    ждём("заметка.", True)
    ждём("заметка ", True)
    ждём("con.md", True)
    ждём("CON", True)
    ждём("Lpt1", True)
    ждём("aux.tar.gz", True)
    ждём("COM9.txt", True)
    ждём("com0.md", False)
    ждём("console.md", False)
    ждём("Решение — выбор базы.md", False)
    ждём("a.b.md", False)

    with tempfile.TemporaryDirectory() as t:
        ч, п = Path(t) / "чистая", Path(t) / "грязная"
        (ч / "вложенная").mkdir(parents=True)
        (ч / "вложенная" / "Решение — выбор.md").write_text("x")
        (п / "вложенная").mkdir(parents=True)
        (п / "вложенная" / "con.md").write_text("x")
        (п / "хорошо.md").write_text("x")
        рч = проверить_папку(ч)
        рп = проверить_папку(п)
        if рч:
            ошибки.append(f"чистая папка: {рч}")
        if рп != [("вложенная/con.md", "зарезервированное имя «con»")]:
            ошибки.append(f"грязная папка: {рп}")
        скрипт = str(Path(__file__).resolve())
        к = subprocess.run([sys.executable, скрипт, "--проверить", str(ч)],
                           capture_output=True, text=True)
        з = subprocess.run([sys.executable, скрипт, "--проверить", str(п)],
                           capture_output=True, text=True)
        if к.returncode != 0:
            ошибки.append(f"чистая: код {к.returncode}")
        if з.returncode != 2 or "вложенная/con.md" not in з.stdout:
            ошибки.append(f"грязная: код {з.returncode}, {з.stdout!r}")

    # исправить: каждое правило замены
    for имя, ждём_имя in [
        ("Заказ: статусы.md", "Заказ - статусы.md"),
        ("a:b.md", "a - b.md"),
        ("a :  b.md", "a - b.md"),
        ("a<b>c.md", "a_b_c.md"),
        ('a"b|c?d*e.md', "a_b_c_d_e.md"),
        ("а\tб.md", "а_б.md"),
        ("а\x00б", "а_б"),
        ("заметка.", "заметка"),
        ("заметка. .", "заметка"),
        ("заметка ", "заметка"),
        ("con.md", "con_.md"),
        ("CON", "CON_"),
        ("aux.tar.gz", "aux_.tar.gz"),
        ("Lpt1.", "Lpt1_"),
        ("хорошо.md", "хорошо.md"),
        ("...", "_"),
    ]:
        р = исправить(имя)
        if р != ждём_имя:
            ошибки.append(f"исправить({имя!r}): ждали {ждём_имя!r}, получили {р!r}")
        if проверить(р) is not None:
            ошибки.append(f"исправить({имя!r}) = {р!r} всё ещё плохое")

    def снимок(корень):
        return sorted((p.relative_to(корень).as_posix(),
                       p.read_bytes() if p.is_file() else None)
                      for p in корень.rglob("*"))

    скрипт_ = str(Path(__file__).resolve())

    def запуск(*арг):
        return subprocess.run([sys.executable, скрипт_, *арг],
                              capture_output=True, text=True)

    with tempfile.TemporaryDirectory() as t:
        в = Path(t) / "vault"
        (в / "Папка: x").mkdir(parents=True)
        (в / "Папка: x" / "con.md").write_text("внутри")
        (в / "Заказ: статусы.md").write_text("x")
        (в / "Читает.md").write_text(
            "[[Заказ: статусы]] [[Заказ: статусы|псевдоним]] [[Заказ: статусы#раздел]] "
            "[[Папка: x/con]] [[Заказ: статусы.md]] [[Другая]]")
        до = снимок(в)
        с = запуск("--переименовать", str(в), "--сухой")
        if с.returncode != 0 or "Заказ: статусы.md → Заказ - статусы.md" not in с.stdout:
            ошибки.append(f"сухой: код {с.returncode}, {с.stdout!r}")
        if "Папка: x/con.md → Папка - x/con_.md" not in с.stdout:
            ошибки.append(f"сухой: нет пути внутри папки, {с.stdout!r}")
        строки = [л for л in с.stdout.splitlines() if "→" in л]
        if not строки or not строки[0].startswith("Папка: x/con.md"):
            ошибки.append(f"сухой: глубже должно идти первым, {строки!r}")
        if снимок(в) != до:
            ошибки.append("сухой прогон изменил диск")
        с = запуск("--переименовать", str(в))
        if с.returncode != 0:
            ошибки.append(f"переименование: код {с.returncode}, {с.stdout!r}")
        if not (в / "Папка - x" / "con_.md").is_file() or not (в / "Заказ - статусы.md").is_file():
            ошибки.append("переименование: файлы не на месте")
        if (в / "Папка: x").exists() or (в / "Заказ: статусы.md").exists():
            ошибки.append("переименование: старые имена остались")
        ссылки = (в / "Читает.md").read_text()
        ждём_ссылки = ("[[Заказ - статусы]] [[Заказ - статусы|псевдоним]] "
                       "[[Заказ - статусы#раздел]] [[Папка - x/con_]] "
                       "[[Заказ - статусы.md]] [[Другая]]")
        if ссылки != ждём_ссылки:
            ошибки.append(f"ссылки: {ссылки!r}")
        if проверить_папку(в):
            ошибки.append(f"после переименования остались плохие: {проверить_папку(в)}")
        с = запуск("--переименовать", str(в))
        if с.returncode != 0 or "нечего переименовывать" not in с.stdout:
            ошибки.append(f"повтор: код {с.returncode}, {с.stdout!r}")

    # столкновения: два плохих в одно; новое имя уже занято
    for файлы in (["a?.md", "a*.md"], ["a:b.md", "a - b.md"]):
        with tempfile.TemporaryDirectory() as t:
            в = Path(t) / "vault"
            в.mkdir()
            for ф in файлы:
                (в / ф).write_text(ф)
            до = снимок(в)
            for арг in ([], ["--сухой"]):
                с = запуск("--переименовать", str(в), *арг)
                if с.returncode != 2:
                    ошибки.append(f"столкновение {файлы}{арг}: код {с.returncode}")
                if снимок(в) != до:
                    ошибки.append(f"столкновение {файлы}{арг}: диск изменён")

    if ошибки:
        print("самопроверка: провал")
        for о in ошибки:
            print(" -", о)
        return 1
    print("самопроверка: ок")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Имя файла для любой ОС")
    ap.add_argument("--проверить", metavar="ПАПКА")
    ap.add_argument("--переименовать", metavar="ПАПКА")
    ap.add_argument("--сухой", action="store_true")
    ap.add_argument("--самопроверка", action="store_true")
    a = ap.parse_args()
    if a.самопроверка:
        return самопроверка()
    if a.переименовать:
        папка = Path(a.переименовать)
        if not папка.is_dir():
            print(f"нет папки: {папка}", file=sys.stderr)
            return 1
        return переименовать(папка, a.сухой)
    if a.проверить:
        папка = Path(a.проверить)
        if not папка.is_dir():
            print(f"нет папки: {папка}", file=sys.stderr)
            return 1
        плохие = проверить_папку(папка)
        for путь, причина in плохие:
            print(f"{путь}: {причина}")
        return 2 if плохие else 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
