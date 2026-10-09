#!/usr/bin/env python3
"""Проверяет форму чек-листов архитектора: у каждого правила пять полей.

Правило — блок под заголовком «### ». В нём строки «- нельзя:», «- надо:»,
«- источник:», «- проверка:», «- тяжесть:» (критично | важно | мелочь).
Печатает число правил по файлу и каждое нарушение; код 0 — всё в порядке.
Папка: $1, иначе skills/architect/checklists рядом с lib/.
"""
import pathlib
import re
import sys

ПОЛЯ = ("нельзя", "надо", "источник", "проверка", "тяжесть")
ТЯЖЕСТЬ = {"критично", "важно", "мелочь"}

папка = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else \
    pathlib.Path(__file__).resolve().parent.parent / "skills/architect/checklists"

ошибки = []
итог = []
for файл in sorted(папка.glob("*.md")):
    блоки = re.split(r"^### ", файл.read_text(encoding="utf-8"), flags=re.M)[1:]
    for блок in блоки:
        заголовок, *строки = блок.strip().splitlines()
        поля = {}
        for с in строки:
            м = re.match(r"- (\S+): (.+)", с)
            if м:
                поля[м.group(1)] = м.group(2).strip()
        нет = [п for п in ПОЛЯ if not поля.get(п)]
        if нет:
            ошибки.append(f"{файл.name}: «{заголовок}» — нет {', '.join(нет)}")
        elif поля["тяжесть"] not in ТЯЖЕСТЬ:
            ошибки.append(f"{файл.name}: «{заголовок}» — тяжесть «{поля['тяжесть']}»")
    итог.append(f"{файл.name} {len(блоки)}")

print(" · ".join(итог) or f"нет чек-листов в {папка}")
for о in ошибки:
    print("  ✗", о)
sys.exit(1 if ошибки or not итог else 0)
