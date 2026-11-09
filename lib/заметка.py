#!/usr/bin/env python3
"""Заметки базы знаний по шаблону — один шаблон для /plexus:end и /plexus:note.

Виды: решение → решения/, баг → баги/, тупик → тупики/, паттерн → приёмы/.
Скрипт пишет заготовку, строку в проект.md и проверяет готовую заметку.
Ничего не удаляет: устаревшие только перечисляет, решает модель и человек.

    python3 lib/заметка.py --новая <вид> --имя "<утверждение>" --эпик E32 --круг "<имя>"
    python3 lib/заметка.py --проверить <файл>
    python3 lib/заметка.py --устаревшие <файл>
    python3 lib/заметка.py --тупики E32
    python3 lib/заметка.py --самопроверка

Флаг --repo (по умолчанию .) — репозиторий с базой знаний.
Из кода:  from заметка import тупики;  тупики(vault, "E32") -> [имя, …]

Выход: 0 — готово; 1 — неверный вызов; 2 — отказ, причина в stderr.
"""
import argparse
import datetime
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vault as сторож  # noqa: E402
from имя_файла import проверить as проверить_имя  # noqa: E402

ВИДЫ = {
    "решение": ("решения", ["Почему", "Цена решения", "Когда вернёмся"]),
    "баг": ("баги", ["Симптом", "Причина", "Как починили", "Урок"]),
    "тупик": ("тупики", ["Что пробовали", "Почему не вышло", "Что вместо"]),
    "паттерн": ("приёмы", ["Фрагмент", "Почему так", "Что важно не забыть"]),
}


class Отказ(Exception):
    pass


def найти_vault(repo):
    базы = сторож.find_vaults(os.path.abspath(repo))
    if not базы:
        raise Отказ("нет базы знаний в этом репозитории — запусти /plexus:init")
    if len(базы) > 1:
        raise Отказ("нашлось несколько баз знаний — спроси человека, в какую писать")
    return базы[0]


def карта(vault):
    try:
        return {d for d, _ in сторож.read_map(vault)}
    except SystemExit:
        raise Отказ("карта.md есть, но ни одной папки в ней не описано")


def теги(значение):
    return [t.strip() for t in значение.strip("[]").split(",") if t.strip()]


def вид_по_папке(папка):
    for вид, (п, _) in ВИДЫ.items():
        if п == папка:
            return вид
    return None


def эпики_заметки(путь):
    """Эпики заметки: «эпик:» из шапки и теги вида E31."""
    шапка = сторож.frontmatter(путь)
    из_шапки = {шапка.get("эпик", "").strip()} - {""}
    из_тегов = {t for t in теги(шапка.get("tags", "")) if re.fullmatch(r"E\d+", t)}
    return из_шапки | из_тегов


def новая(vault, вид, имя, эпик, круг):
    if вид not in ВИДЫ:
        raise Отказ(f"неизвестный вид «{вид}», бывают: " + ", ".join(ВИДЫ))
    папка, разделы = ВИДЫ[вид]
    имя = имя.strip()
    причина = проверить_имя(имя + ".md")
    if причина:
        raise Отказ(f"плохое имя файла: {причина}")
    if папка not in карта(vault):
        raise Отказ(f"папки «{папка}/» нет в карте — добавь её в карта.md и создай на диске")
    путь = Path(vault) / папка / f"{имя}.md"
    if путь.exists():
        raise Отказ(f"имя занято: {путь}")
    путь.parent.mkdir(exist_ok=True)
    сегодня = datetime.date.today().isoformat()
    текст = (
        f"---\ntags: [{папка}]\ndate: {сегодня}\nэпик: {эпик}\nкруг: {круг or '—'}\n---\n\n"
        f"# {имя[:1].upper() + имя[1:]}\n\n"
        + "".join(f"## {р}\n\n\n" for р in разделы)
    )
    путь.write_text(текст.rstrip("\n") + "\n", encoding="utf-8")
    добавить_в_проект(vault, папка, имя, эпик, круг)
    return путь


def добавить_в_проект(vault, папка, имя, эпик, круг):
    """Строка в список заметок папки и свежая дата в шапке проект.md."""
    p = Path(vault) / сторож.INDEX
    строки = p.read_text(encoding="utf-8").split("\n")
    сегодня = datetime.date.today().isoformat()
    if строки and строки[0].strip() == "---":
        for i in range(1, len(строки)):
            if строки[i].strip() == "---":
                break
            if строки[i].startswith("обновлён:"):
                строки[i] = f"обновлён: {сегодня}"
    запись = f"- [[{имя}]] — {эпик}" + (f", круг «{круг}»" if круг and круг != "—" else "")
    заголовок = f"### {папка}"
    if заголовок in строки:
        i = строки.index(заголовок) + 1
        while i < len(строки) and not строки[i].startswith("#"):
            i += 1
        while i > 0 and строки[i - 1].strip() == "":
            i -= 1
        строки.insert(i, запись)
    else:
        while строки and строки[-1].strip() == "":
            строки.pop()
        строки += ["", заголовок, "", запись, ""]
    p.write_text("\n".join(строки), encoding="utf-8")


def проверить(путь):
    путь = Path(путь)
    if not путь.is_file():
        raise Отказ(f"нет файла: {путь}")
    вид = вид_по_папке(путь.resolve().parent.name)
    if not вид:
        raise Отказ(f"папка «{путь.resolve().parent.name}» не принадлежит ни одному виду заметок")
    причина = проверить_имя(путь.name)
    if причина:
        raise Отказ(f"плохое имя файла: {причина}")
    шапка = сторож.frontmatter(путь)
    for ключ in ("эпик", "круг"):
        if not шапка.get(ключ):
            raise Отказ(f"в шапке нет «{ключ}:» (вне круга — «круг: —»)")
    содержимое = {}
    текущий = None
    for строка in путь.read_text(encoding="utf-8").split("\n"):
        if строка.startswith("## "):
            текущий = строка[3:].strip()
            содержимое[текущий] = ""
        elif текущий is not None:
            содержимое[текущий] += строка.strip()
    for раздел in ВИДЫ[вид][1]:
        if раздел not in содержимое:
            raise Отказ(f"нет раздела «{раздел}»")
        if not содержимое[раздел]:
            raise Отказ(f"раздел «{раздел}» пуст")


def устаревшие(путь):
    """Кандидаты на замену: та же папка, тот же эпик. Не удаляет."""
    путь = Path(путь).resolve()
    if not путь.is_file():
        raise Отказ(f"нет файла: {путь}")
    эпик = сторож.frontmatter(путь).get("эпик", "").strip()
    if not эпик:
        raise Отказ("в шапке нет «эпик:» — не с чем сравнивать")
    return [f.name for f in sorted(путь.parent.glob("*.md"))
            if f != путь and эпик in эпики_заметки(f)]


def тупики(vault, эпик):
    """Имена тупиков эпика без .md. Только читает."""
    папка = Path(vault) / "тупики"
    if not папка.is_dir():
        return []
    return [f.stem for f in sorted(папка.glob("*.md")) if эпик in эпики_заметки(f)]


def самопроверка():
    ошибки = []

    def ждём(условие, что):
        if not условие:
            ошибки.append(что)

    def отказ(f, *a):
        try:
            f(*a)
        except Отказ as e:
            return str(e)
        return None

    with tempfile.TemporaryDirectory() as t:
        v = Path(t) / "vault"
        for п in ("решения", "баги", "тупики", "приёмы"):
            (v / п).mkdir(parents=True)
        (v / "карта.md").write_text(
            "---\nпроект: x\n---\n\n- `решения/` — р\n- `баги/` — б\n- `тупики/` — т\n- `приёмы/` — п\n",
            encoding="utf-8")
        (v / "проект.md").write_text(
            "---\nпроект: x\nобновлён: 2000-01-01\n---\n\n# X\n\n## Заметки\n\n### решения\n\n"
            "- [[старое]] — a\n\n### баги\n\n### приёмы\n", encoding="utf-8")

        пути = {}
        for вид in ВИДЫ:
            пути[вид] = новая(str(v), вид, f"{вид} проверен", "E32", "круг один")
            ждём(пути[вид].parent.name == ВИДЫ[вид][0], f"{вид}: папка")
            ждём(отказ(проверить, пути[вид]) is not None, f"{вид}: пустая заготовка прошла")
            текст = пути[вид].read_text(encoding="utf-8")
            ждём(текст.startswith(f"---\ntags: [{ВИДЫ[вид][0]}]"), f"{вид}: шапка")
            ждём(f"# {вид[:1].upper()}{вид[1:]} проверен" in текст, f"{вид}: H1")
            пути[вид].write_text(re.sub(r"(## .+)\n+", r"\1\n\nтекст\n\n", текст), encoding="utf-8")
            ждём(отказ(проверить, пути[вид]) is None, f"{вид}: заполненная не прошла")
        п = пути["баг"]
        п.write_text(re.sub(r"(## Урок\n\n)текст\n", r"\1", п.read_text(encoding="utf-8")), encoding="utf-8")
        ждём("«Урок» пуст" in (отказ(проверить, п) or ""), "пустой раздел не пойман")
        п.write_text(п.read_text(encoding="utf-8").replace("## Урок", "## Другое"), encoding="utf-8")
        ждём("нет раздела «Урок»" in (отказ(проверить, п) or ""), "нет раздела не поймано")
        п2 = пути["решение"]
        п2.write_text(п2.read_text(encoding="utf-8").replace("круг: круг один\n", ""), encoding="utf-8")
        ждём("круг" in (отказ(проверить, п2) or ""), "нет круга не поймано")

        пр = (v / "проект.md").read_text(encoding="utf-8")
        ждём("[[решение проверен]]" in пр and "обновлён: 2000" not in пр, "проект.md не обновлён")
        ждём("### тупики" in пр and "[[тупик проверен]]" in пр, "секция тупиков")
        ждём(пр.index("[[решение проверен]]") < пр.index("### баги"), "запись не в своей секции")

        ждём("занято" in (отказ(новая, str(v), "баг", "баг проверен", "E32", "к") or ""), "занятое имя")
        ждём("файла" in (отказ(новая, str(v), "баг", "con", "E32", "к") or ""), "плохое имя")
        ждём("файла" in (отказ(новая, str(v), "баг", "а:б", "E32", "к") or ""), "двоеточие")
        ждём("вид" in (отказ(новая, str(v), "заметка", "x", "E32", "к") or ""), "неизвестный вид")

        # устаревшие: по шапке и по tags
        (v / "решения" / "по шапке.md").write_text(
            "---\ntags: [решения]\nэпик: E32\nкруг: —\n---\n\n# x\n", encoding="utf-8")
        (v / "решения" / "по тегу.md").write_text(
            "---\ntags: [решения, youtrack, E32]\n---\n\n# x\n", encoding="utf-8")
        (v / "решения" / "чужой.md").write_text(
            "---\ntags: [решения, E31]\nэпик: E31\n---\n\n# x\n", encoding="utf-8")
        ждём(устаревшие(пути["решение"]) == ["по тегу.md", "по шапке.md"],
             f"устаревшие: {устаревшие(пути['решение'])}")

        ждём(тупики(str(v), "E32") == ["тупик проверен"], f"тупики: {тупики(str(v), 'E32')}")
        ждём(тупики(str(v), "E99") == [], "тупики чужого эпика")
        ждём(тупики(str(Path(t) / "нет"), "E32") == [], "тупики без папки")

        скрипт = str(Path(__file__).resolve())

        def cli(*арг):
            return subprocess.run([sys.executable, скрипт, *арг], capture_output=True, text=True)

        к = cli("--repo", t, "--тупики", "E32")
        ждём(к.returncode == 0 and к.stdout.strip() == "тупик проверен", f"cli тупики: {к.stdout!r}")
        к = cli("--repo", t, "--проверить", str(пути["тупик"]))
        ждём(к.returncode == 0, f"cli проверить: {к.stderr}")
        к = cli("--repo", t, "--новая", "тупик", "--имя", "a|b", "--эпик", "E32", "--круг", "к")
        ждём(к.returncode == 2, f"cli плохое имя: код {к.returncode}")
        к = cli("--repo", t, "--новая", "тупик", "--имя", "cli тупик", "--эпик", "E32", "--круг", "к")
        ждём(к.returncode == 0 and (v / "тупики" / "cli тупик.md").is_file(), f"cli новая: {к.stderr}")
        к = cli("--новая", "тупик")
        ждём(к.returncode == 1, f"cli неверный вызов: код {к.returncode}")

        # папки нет в карте
        (v / "карта.md").write_text("---\n---\n\n- `решения/` — р\n", encoding="utf-8")
        ждём("нет в карте" in (отказ(новая, str(v), "тупик", "другой тупик", "E32", "к") or ""),
             "папки нет в карте")

    if ошибки:
        print("самопроверка: провал")
        for о in ошибки:
            print(" -", о)
        return 1
    print("самопроверка: ок")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Заметки по шаблону")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--новая", metavar="ВИД")
    ap.add_argument("--имя")
    ap.add_argument("--эпик")
    ap.add_argument("--круг")
    ap.add_argument("--проверить", metavar="ФАЙЛ")
    ap.add_argument("--устаревшие", metavar="ФАЙЛ")
    ap.add_argument("--тупики", metavar="ЭПИК")
    ap.add_argument("--самопроверка", action="store_true")
    try:
        a = ap.parse_args()
    except SystemExit as e:
        return 1 if e.code else 0
    if a.самопроверка:
        return самопроверка()
    try:
        if a.новая:
            if not (a.имя and a.эпик and a.круг):
                print("нужны --имя, --эпик и --круг", file=sys.stderr)
                return 1
            print(новая(найти_vault(a.repo), a.новая, a.имя, a.эпик, a.круг))
        elif a.проверить:
            проверить(a.проверить)
        elif a.устаревшие:
            for имя in устаревшие(a.устаревшие):
                print(имя)
        elif a.тупики:
            for имя in тупики(найти_vault(a.repo), a.тупики):
                print(имя)
        else:
            ap.print_help()
            return 1
    except Отказ as e:
        print(e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
