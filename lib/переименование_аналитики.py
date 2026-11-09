#!/usr/bin/env python3
"""Переименование заведённой аналитики vault: карточка по смыслу, имя без « — ».

Карточка `модули/<модуль>/<capability>/capability.md` становится
`<смысл> (<capability>).md`, смысл — из заголовка `# <смысл> (<КОД>)`.
Аналитика `<КОД>-<NN> <что делаем> — <проблема>.md` — `<КОД>-<NN> <что делаем>.md`.
Строка «Лежит:» в карточке и ссылки `[[…]]` во всех .md vault переписываются
на новое имя (голым именем; `|подпись` и `#раздел` сохраняются). Ссылки
разрешаются по хвосту пути, как у сторожа аналитика_заметки.py.

    python3 ${CLAUDE_PLUGIN_ROOT}/lib/переименование_аналитики.py <vault> [--сухой]
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/переименование_аналитики.py --самопроверка

Выход: 0 — готово или «нечего делать»; 1 — неверные аргументы; 2 — отказ до
первой записи (заголовок карточки не по форме, новое имя занято или у двух
файлов одно имя), vault не тронут.
"""
import argparse
import re
import subprocess
import sys
import tempfile
import unicodedata
from collections import defaultdict
from pathlib import Path

ПАПКА_МОДУЛЕЙ = "модули"
СТАРАЯ_КАРТОЧКА = "capability.md"
РАЗДЕЛИТЕЛЬ = " — "
ЗАГОЛОВОК = re.compile(r"^# (.+) \(([^()\s]+)\)\s*$")
ССЫЛКА = re.compile(r"\[\[([^\[\]]+)\]\]")
ЛЕЖИТ = re.compile(r"`[^`]*?/capability\.md`")
СТОРОЖ = Path(__file__).resolve().parent / "аналитика_заметки.py"


class Отказ(Exception):
    """Код 1: неверные аргументы."""


def нфц(s: str) -> str:
    """Имена файлов на macOS бывают в NFD — сравниваем в одной форме."""
    return unicodedata.normalize("NFC", s)


def заголовок(текст: str) -> str | None:
    """Первая строка `# …` после шапки."""
    строки = текст.splitlines()
    начало = 0
    if строки and строки[0].strip() == "---":
        for i, с in enumerate(строки[1:], 1):
            if с.strip() == "---":
                начало = i + 1
                break
    for с in строки[начало:]:
        if с.startswith("# "):
            return с
    return None


def план_имён(vault: Path, файлы: dict[Path, str]) -> tuple[dict[Path, Path], list[str]]:
    """Что переименовать: {старый путь → новый}; и причины отказа."""
    модули = vault / ПАПКА_МОДУЛЕЙ
    переименовать: dict[Path, Path] = {}
    причины: list[str] = []
    for p in sorted(файлы):
        if not p.is_relative_to(модули):
            continue
        части = p.relative_to(модули).parts
        имя = нфц(части[-1])
        новое = None
        if len(части) == 3 and имя == СТАРАЯ_КАРТОЧКА:
            строка = заголовок(файлы[p])
            m = ЗАГОЛОВОК.match(строка) if строка else None
            if not m or "/" in m.group(1):
                причины.append(f"{p.relative_to(vault).as_posix()}: заголовок карточки не по форме "
                               "«# <смысл> (<КОД>)»")
                continue
            новое = f"{m.group(1).strip()} ({нфц(части[1])}).md"
        elif len(части) == 4 and нфц(части[2]) == "аналитика" and РАЗДЕЛИТЕЛЬ in имя:
            до = имя.split(РАЗДЕЛИТЕЛЬ, 1)[0].strip()
            if not до:
                причины.append(f"{p.relative_to(vault).as_posix()}: пустое имя до « — »")
                continue
            новое = до + ".md"
        if новое is not None:
            переименовать[p] = p.with_name(новое)
    # коллизии
    занято = {нфц(p.relative_to(vault).as_posix()): p for p in файлы}
    итог: dict[str, Path] = {}
    for старый, новый in переименовать.items():
        к = нфц(новый.relative_to(vault).as_posix())
        if к in итог:
            причины.append(f"{новый.relative_to(vault).as_posix()}: одно новое имя у двух файлов — "
                           f"{итог[к].name} и {старый.name}")
        elif к in занято and занято[к] not in переименовать:
            причины.append(f"{новый.relative_to(vault).as_posix()}: новое имя занято")
        итог[к] = старый
    стемы: dict[str, list[Path]] = defaultdict(list)
    for p in файлы:
        if p not in переименовать:
            стемы[нфц(p.name[:-3])].append(p)
    for старый, новый in переименовать.items():
        if стемы.get(нфц(новый.name[:-3])):
            причины.append(f"{новый.relative_to(vault).as_posix()}: голая ссылка [[{новый.name[:-3]}]] "
                           "стала бы неоднозначной — такое имя уже есть в vault")
    return переименовать, причины


def найти(цель: str, ключи: dict[Path, str]) -> list[Path]:
    """Как у сторожа: `x/y` — путь кончается на `x/y`; голое имя — единственное."""
    цель = цель.removesuffix(".md")
    if "/" in цель:
        return [p for p, k in ключи.items() if k == цель or k.endswith("/" + цель)]
    return [p for p, k in ключи.items() if k.rsplit("/", 1)[-1] == цель]


def поправить_ссылки(текст: str, ключи: dict[Path, str],
                     новые: dict[Path, Path]) -> tuple[str, int]:
    """Заменяет цели ссылок на новые имена; код в ``` не трогает."""
    число = 0

    def замена(m: re.Match) -> str:
        nonlocal число
        внутри = m.group(1)
        разрез = re.search(r"[|#]", внутри)
        цель, хвост = (внутри[:разрез.start()], внутри[разрез.start():]) if разрез else (внутри, "")
        найдено = найти(нфц(цель.strip()), ключи)
        if len(найдено) == 1 and найдено[0] in новые:
            число += 1
            return "[[" + новые[найдено[0]].name[:-3] + хвост + "]]"
        return m.group(0)

    части = re.split(r"(```.*?```)", текст, flags=re.S)
    for i in range(0, len(части), 2):
        части[i] = ССЫЛКА.sub(замена, части[i])
    return "".join(части), число


def прогон(vault: Path, сухой: bool) -> int:
    if not (vault / ПАПКА_МОДУЛЕЙ).is_dir():
        raise Отказ(f"нет папки {vault / ПАПКА_МОДУЛЕЙ}")
    файлы = {p: p.read_text(encoding="utf-8") for p in sorted(vault.rglob("*.md"))}
    ключи = {p: нфц(p.relative_to(vault).as_posix()[:-3]) for p in файлы}
    переименовать, причины = план_имён(vault, файлы)
    if причины:
        for с in причины:
            print("отказ:", с)
        print("vault не тронут")
        return 2

    правки: dict[Path, tuple[str, int, bool]] = {}  # текст, ссылок, «Лежит» переписана
    for p, текст in файлы.items():
        новый, n = поправить_ссылки(текст, ключи, переименовать)
        лежит = False
        if p in переименовать and нфц(p.name) == СТАРАЯ_КАРТОЧКА:
            путь = нфц(переименовать[p].relative_to(vault).as_posix())
            строки = новый.splitlines(keepends=True)
            for i, с in enumerate(строки):
                if с.startswith("Лежит:") and ЛЕЖИТ.search(с):
                    строки[i] = ЛЕЖИТ.sub(lambda _: f"`{путь}`", с)
                    лежит = True
            новый = "".join(строки)
        if новый != текст:
            правки[p] = (новый, n, лежит)

    if not переименовать and not правки:
        print("нечего делать")
        return 0

    def показ(p: Path) -> str:
        return p.relative_to(vault).as_posix()

    слово = ("переименую", "поправлю") if сухой else ("переименовал", "поправил")
    for старый, новый in переименовать.items():
        print(f"{слово[0]} {показ(старый)} → {показ(новый)}")
    for p, (_, n, лежит) in правки.items():
        if n:
            print(f"{слово[1]} ссылки в {показ(переименовать.get(p, p))}: {n}")
        if лежит:
            print(f"{слово[1]} «Лежит:» в {показ(переименовать.get(p, p))}")
    if сухой:
        return 0
    for p, (текст, _, _) in правки.items():
        p.write_text(текст, encoding="utf-8")
    for старый, новый in переименовать.items():
        старый.rename(новый)
    return 0


# ---------- самопроверка ----------

def _запись(vault: Path, путь: str, текст: str) -> None:
    p = vault / путь
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(текст, encoding="utf-8")


def _снимок(vault: Path) -> dict[str, bytes]:
    return {p.relative_to(vault).as_posix(): p.read_bytes()
            for p in sorted(vault.rglob("*")) if p.is_file()}


def _vault_старого_вида(vault: Path, заголовок_карточки: str = "# Документы материального учёта (МАТДОК)") -> None:
    мод = "модули/имущество (assets)"
    старая = "МАТДОК-01 приход накладной — правила не описаны"
    _запись(vault, f"{мод}.md",
            "# Имущество (assets)\n\nКарточка: [[materialdocuments/capability]].\n")
    _запись(vault, f"{мод}/materialdocuments/capability.md",
            "---\nмодуль: имущество (assets)\ncapability: materialdocuments\nкод: МАТДОК\n---\n\n"
            f"{заголовок_карточки}\n\n"
            f"Лежит: `{мод}/materialdocuments/capability.md`.\n\n"
            f"## Своя аналитика\n\n[[{старая}]]\n\n## Меня затрагивают\n\nПока нет.\n")
    _запись(vault, f"{мод}/materialdocuments/аналитика/{старая}.md",
            "---\nкод: МАТДОК-01\nназвание: приход накладной — правила не описаны\n"
            "модуль: имущество (assets)\ncapability: materialdocuments\nтип работы: новый\n"
            "этап: ЧТО\nстатус: черновик\nавтор: работник\nроль: аналитик\nдата: 2026-11-05\n---\n\n"
            "# приход накладной — правила не описаны\n\n"
            "Карточка: [[materialdocuments/capability]].\n")
    _запись(vault, "заметки/решение.md",
            "# Решение\n\nСм. [[materialdocuments/capability|карточку]], "
            "[[модули/имущество (assets)/materialdocuments/capability#Своя аналитика]] и "
            f"[[{старая}#Критерии|аналитику]].\n\n```\n[[materialdocuments/capability]]\n```\n")


def самопроверка() -> int:
    ошибки: list[str] = []

    def проверка(условие: bool, что: str) -> None:
        if not условие:
            ошибки.append(что)

    def запуск(vault: Path, *арг: str) -> tuple[int, str]:
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(vault), *арг],
                           capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    с_ = "модули/имущество (assets)/materialdocuments"
    with tempfile.TemporaryDirectory() as t:
        vault = Path(t) / "vault"
        _vault_старого_вида(vault)
        до = _снимок(vault)
        код, вывод = запуск(vault, "--сухой")
        проверка(код == 0, f"--сухой: код {код}")
        проверка(_снимок(vault) == до, "--сухой изменил vault")
        проверка("переименую" in вывод and "поправлю ссылки в" in вывод, f"--сухой: план не напечатан: {вывод!r}")

        код, вывод = запуск(vault)
        проверка(код == 0, f"прогон: код {код}: {вывод}")
        карточка = vault / с_ / "Документы материального учёта (materialdocuments).md"
        аналитика = vault / с_ / "аналитика" / "МАТДОК-01 приход накладной.md"
        проверка(карточка.is_file() and not (vault / с_ / "capability.md").exists(), "карточка не переименована")
        проверка(аналитика.is_file(), "аналитика не переименована")
        if карточка.is_file():
            т = карточка.read_text(encoding="utf-8")
            проверка(f"Лежит: `{с_}/Документы материального учёта (materialdocuments).md`." in т,
                     "«Лежит:» не переписана")
            проверка("[[МАТДОК-01 приход накладной]]" in т, "ссылка на аналитику в карточке не поправлена")
            проверка("# Документы материального учёта (МАТДОК)" in т, "заголовок карточки изменился")
        if аналитика.is_file():
            т = аналитика.read_text(encoding="utf-8")
            проверка("[[Документы материального учёта (materialdocuments)]]" in т, "ссылка на карточку не поправлена")
            проверка("название: приход накладной — правила не описаны" in т, "шапка аналитики изменилась")
        т = (vault / "модули/имущество (assets).md").read_text(encoding="utf-8")
        проверка("[[Документы материального учёта (materialdocuments)]]" in т, "заметка модуля: ссылка не поправлена")
        т = (vault / "заметки/решение.md").read_text(encoding="utf-8")
        проверка("[[Документы материального учёта (materialdocuments)|карточку]]" in т, "|подпись потеряна")
        проверка("[[Документы материального учёта (materialdocuments)#Своя аналитика]]" in т, "#раздел потерян")
        проверка("[[МАТДОК-01 приход накладной#Критерии|аналитику]]" in т, "ссылка на аналитику с #|: не поправлена")
        проверка("```\n[[materialdocuments/capability]]\n```" in т, "ссылка в блоке кода тронута")

        r = subprocess.run([sys.executable, str(СТОРОЖ), str(vault / ПАПКА_МОДУЛЕЙ)],
                           capture_output=True, text=True)
        проверка(r.returncode == 0, f"сторож на результате: код {r.returncode}: {r.stdout}{r.stderr}")

        после = _снимок(vault)
        код, вывод = запуск(vault)
        проверка(код == 0 and "нечего делать" in вывод, f"повтор: {код} {вывод!r}")
        проверка(_снимок(vault) == после, "повтор изменил vault")

    with tempfile.TemporaryDirectory() as t:
        vault = Path(t) / "vault"
        _vault_старого_вида(vault, "# Документы материального учёта")
        до = _снимок(vault)
        код, вывод = запуск(vault)
        проверка(код == 2, f"заголовок не по форме: код {код}")
        проверка(_снимок(vault) == до, "заголовок не по форме: vault тронут")

    with tempfile.TemporaryDirectory() as t:
        vault = Path(t) / "vault"
        _vault_старого_вида(vault)
        _запись(vault, "модули/имущество (assets)/materialdocuments/аналитика/МАТДОК-01 приход накладной — другая.md",
                "---\nкод: МАТДОК-01\n---\n")
        до = _снимок(vault)
        код, вывод = запуск(vault)
        проверка(код == 2, f"два файла с одним именем: код {код}")
        проверка(_снимок(vault) == до, "два файла с одним именем: vault тронут")

    if ошибки:
        print("самопроверка: ПРОВАЛ")
        for о in ошибки:
            print(" -", о)
        return 1
    print("самопроверка: ок")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("vault", nargs="?")
    ap.add_argument("--сухой", action="store_true")
    ap.add_argument("--самопроверка", action="store_true")
    a = ap.parse_args()
    try:
        if a.самопроверка:
            return самопроверка()
        if not a.vault:
            raise Отказ("нужна папка vault или --самопроверка")
        return прогон(Path(a.vault), a.сухой)
    except Отказ as e:
        print("ошибка:", e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
