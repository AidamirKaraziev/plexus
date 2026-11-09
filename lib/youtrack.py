#!/usr/bin/env python3
"""YouTrack: аналитика уходит задачей, круг — чек-листом в её описании.

Настройка — строка в шапке .claude/plan/roadmap.md: `youtrack: <адрес> · <проект>`;
токен — переменная окружения YOUTRACK_TOKEN. Нет строки → «YouTrack: не настроен»,
нет токена → «YouTrack: нет YOUTRACK_TOKEN»; в обоих случаях ни одного запроса, код 0.

  * аналитика в vault/модули/*/*/аналитика/ со статусом утверждено, в работе или
    сделано и без `youtrack:` → задача (название → summary, тело заметки → description);
    id вписывается в шапку заметки ключом `youtrack:`;
  * круг в vault/круги/ (не архив/) со статусом «утверждено …»: его `этап:` совпадает
    с `этап:` аналитики, у которой есть `youtrack:` → блок-чек-лист между метками
    `<!-- плексус: круг <имя> -->` и `<!-- /плексус -->` в описании этой задачи;
    остальное описание не трогается; не изменилось — запрос не шлётся.

    python3 ${CLAUDE_PLUGIN_ROOT}/lib/youtrack.py [--repo <папка>] [--сухой]
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/youtrack.py --самопроверка

`--сухой` печатает запросы (метод, URL, тело) и ничего не шлёт и не пишет.
Коды выхода: 0 — готово или не настроено; 2 — ошибка аргументов или настройки;
3 — сеть или YouTrack ответили ошибкой (строка с причиной, файлы без запроса не тронуты).
"""
import argparse
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from аналитика_заметки import шапка, пусто  # noqa: E402

СТАТУСЫ_ЗАДАЧИ = {"утверждено", "в работе", "сделано"}


class Сбой(Exception):
    pass


def настройка(repo: Path):
    """(адрес, проект) из шапки roadmap.md; None — строки нет; Сбой — строка кривая."""
    p = repo / ".claude" / "plan" / "roadmap.md"
    if not p.exists():
        return None
    h = шапка(p.read_text(encoding="utf-8")) or {}
    val = h.get("youtrack")
    if пусто(val):
        return None
    адрес, sep, проект = val.partition("·")
    адрес, проект = адрес.strip().rstrip("/"), проект.strip()
    if not sep or not адрес or not проект:
        raise Сбой("в roadmap.md строка `youtrack:` должна быть `<адрес> · <проект>`")
    return адрес, проект


def тело_заметки(текст: str) -> str:
    строки = текст.splitlines()
    if строки and строки[0].strip() == "---":
        for i, с in enumerate(строки[1:], 1):
            if с.strip() == "---":
                return "\n".join(строки[i + 1:]).strip()
    return текст.strip()


def вписать_ключ(текст: str, id_: str) -> str:
    строки = текст.split("\n")
    конец = None
    for i, с in enumerate(строки[1:], 1):
        if с.strip() == "---":
            конец = i
            break
        if с.startswith("youtrack:"):
            строки[i] = f"youtrack: {id_}"
            return "\n".join(строки)
    строки.insert(конец, f"youtrack: {id_}")
    return "\n".join(строки)


def аналитики(repo: Path):
    """Заметки аналитики: [(путь, шапка, текст)]."""
    out = []
    for p in sorted((repo / "vault" / "модули").glob("*/*/аналитика/*.md")):
        t = p.read_text(encoding="utf-8")
        h = шапка(t)
        if h:
            out.append((p, h, t))
    return out


def круги(repo: Path):
    """Утверждённые круги: [(имя, этап, [(задача, закрыта)])]."""
    out = []
    for p in sorted((repo / "vault" / "круги").glob("*.md")):
        t = p.read_text(encoding="utf-8")
        h = шапка(t) or {}
        if not (h.get("статус") or "").startswith("утверждено"):
            continue
        задачи, итог, раздел = [], [], None
        for с in t.splitlines():
            if с.startswith("## "):
                раздел = с[3:].strip()
            elif раздел == "Задачи" and с.startswith("### "):
                задачи.append(re.split(r"\s·\s", с[4:], 1)[0].strip())
            elif раздел == "Итог":
                итог.append(с)
        итог = "\n".join(итог)
        out.append((p.stem, (h.get("этап") or "").strip(), [(з, з in итог) for з in задачи]))
    return out


def блок(имя: str, задачи) -> str:
    стр = [f"<!-- плексус: круг {имя} -->", f"### Круг {имя}"]
    стр += [f"- [{'x' if д else ' '}] {з}" for з, д in задачи]
    стр.append("<!-- /плексус -->")
    return "\n".join(стр)


def влить(описание: str, имя: str, новый: str) -> str:
    шаблон = re.compile(r"<!-- плексус: круг " + re.escape(имя) + r" -->.*?<!-- /плексус -->", re.S)
    if шаблон.search(описание):
        return шаблон.sub(lambda _: новый, описание, count=1)
    return (описание.rstrip("\n") + "\n\n" if описание.strip() else "") + новый


def http_реальный(метод, url, заголовки, тело):
    data = json.dumps(тело).encode() if тело is not None else None
    req = urllib.request.Request(url, data=data, headers=заголовки, method=метод)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raise Сбой(f"HTTP {e.code} {e.reason} на {метод} {url.split('?')[0]}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise Сбой(f"нет связи с YouTrack: {getattr(e, 'reason', e)}")


def синхронизировать(repo: Path, токен: str | None, сухой: bool = False, http=http_реальный):
    """(код, [строки вывода])."""
    вывод = []
    try:
        н = настройка(repo)
    except Сбой as e:
        return 2, [f"YouTrack: {e}"]
    if н is None:
        return 0, ["YouTrack: не настроен"]
    if not токен:
        return 0, ["YouTrack: нет YOUTRACK_TOKEN"]
    адрес, проект = н
    заголовки = {"Authorization": f"Bearer {токен}", "Content-Type": "application/json",
                 "Accept": "application/json"}
    ошибки = 0

    def запрос(метод, путь, тело=None):
        url = адрес + путь
        if сухой:
            вывод.append(f"{метод} {url}" + (f" {json.dumps(тело, ensure_ascii=False)}" if тело else ""))
            return None
        return http(метод, url, заголовки, тело)

    создано = обновлено = 0
    for p, h, t in аналитики(repo):
        статус = (h.get("статус") or "").strip()
        if статус not in СТАТУСЫ_ЗАДАЧИ or not пусто(h.get("youtrack")):
            continue
        try:
            ответ = запрос("POST", "/api/issues?fields=idReadable", {
                "project": {"shortName": проект}, "summary": h.get("название") or p.stem,
                "description": тело_заметки(t)})
            if ответ is None:
                continue
            id_ = ответ["idReadable"]
            p.write_text(вписать_ключ(t, id_), encoding="utf-8")
            создано += 1
            вывод.append(f"аналитика {p.stem}: задача {id_}")
        except (Сбой, KeyError) as e:
            ошибки += 1
            вывод.append(f"YouTrack: аналитика {p.stem}: {e if isinstance(e, Сбой) else 'нет idReadable в ответе'}")

    этапы = {}
    for p, h, t in аналитики(repo):
        if not пусто(h.get("youtrack")) and not пусто(h.get("этап")):
            этапы.setdefault(h["этап"].strip().strip("\"'"), h["youtrack"].strip().strip("\"'"))
    for имя, этап, задачи in круги(repo):
        id_ = этапы.get(этап) if этап else None
        if not id_:
            вывод.append(f"круг {имя}: нет задачи YouTrack")
            continue
        новый = блок(имя, задачи)
        try:
            ответ = запрос("GET", f"/api/issues/{id_}?fields=description")
            старое = ((ответ or {}).get("description") or "") if ответ is not None else ""
            описание = влить(старое, имя, новый)
            if ответ is not None and описание == старое:
                вывод.append(f"круг {имя}: {id_} без изменений")
                continue
            запрос("POST", f"/api/issues/{id_}?fields=idReadable", {"description": описание})
            if not сухой:
                обновлено += 1
                вывод.append(f"круг {имя}: чек-лист в {id_}")
        except Сбой as e:
            ошибки += 1
            вывод.append(f"YouTrack: круг {имя}: {e}")
    if not сухой:
        вывод.append(f"YouTrack: задач создано {создано}, описаний обновлено {обновлено}")
    return (3 if ошибки else 0), вывод


class Фальшивый:
    """Подмена HTTP для самопроверки: хранит задачи, считает запросы."""

    def __init__(self, ошибка=False):
        self.задачи, self.запросы, self.ошибка = {}, [], ошибка

    def __call__(self, метод, url, заголовки, тело):
        self.запросы.append((метод, url, тело))
        if self.ошибка:
            raise Сбой("HTTP 500 Server Error")
        m = re.search(r"/api/issues/([A-Z]+-\d+)", url)
        if метод == "POST" and not m:
            id_ = f"PLX-{len(self.задачи) + 12}"
            self.задачи[id_] = тело["description"]
            return {"idReadable": id_}
        if метод == "GET":
            return {"description": self.задачи[m.group(1)]}
        self.задачи[m.group(1)] = тело["description"]
        return {"idReadable": m.group(1)}


def selftest() -> int:
    fails = []

    def ok(усл, что):
        if not усл:
            fails.append(что)

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        road = repo / ".claude" / "plan" / "roadmap.md"
        road.parent.mkdir(parents=True)
        ан = repo / "vault" / "модули" / "имущество (assets)" / "mat" / "аналитика"
        ан.mkdir(parents=True)
        кр = repo / "vault" / "круги"
        кр.mkdir(parents=True)
        (кр / "архив").mkdir()

        def шапка_roadmap(*extra):
            road.write_text("---\nпроект: x\n" + "".join(e + "\n" for e in extra) + "---\n\n# План\n",
                            encoding="utf-8")

        def заметка(имя, статус, extra=""):
            (ан / f"{имя}.md").write_text(
                f"---\nкод: A-01\nназвание: приход накладной\nмодуль: m\nэтап: E1\nстатус: {статус}\n"
                f"{extra}---\n\n# Тело\nправила прихода\n", encoding="utf-8")

        def круг(имя, этап="E1", статус="утверждено 2026-11-06", итог="", где=None):
            (где or кр).joinpath(f"{имя}.md").write_text(
                f"---\nэтап: {этап}\nстатус: {статус}\n---\n\n# К\n\n## Задачи\n\n### первая\nтекст\n\n"
                f"### вторая · после «первая»\nтекст\n\n## Итог\n{итог}", encoding="utf-8")

        ф = Фальшивый()
        # настройки нет
        шапка_roadmap()
        код, вывод = синхронизировать(repo, "t", False, ф)
        ok(код == 0 and not ф.запросы and "не настроен" in вывод[0], "нет настройки")
        шапка_roadmap("youtrack: https://yt.example.com/ · PLX")
        код, вывод = синхронизировать(repo, None, False, ф)
        ok(код == 0 and not ф.запросы and "нет YOUTRACK_TOKEN" in вывод[0], "нет токена")

        # черновик пропущен
        заметка("черн", "черновик")
        код, _ = синхронизировать(repo, "t", False, ф)
        ok(код == 0 and not ф.запросы, "черновик пропущен")
        (ан / "черн.md").unlink()

        # утверждённая → один POST, ключ во frontmatter, повтор → 0
        заметка("утв", "утверждено", 'youtrack: ""\n')
        код, _ = синхронизировать(repo, "t", False, ф)
        текст = (ан / "утв.md").read_text(encoding="utf-8")
        ok(код == 0 and len(ф.запросы) == 1 and ф.запросы[0][0] == "POST", "один POST")
        ok(ф.запросы[0][2]["summary"] == "приход накладной"
           and "правила прихода" in ф.запросы[0][2]["description"], "summary и описание")
        ok("youtrack: PLX-12\n" in текст and текст.count("youtrack:") == 1, "youtrack: во frontmatter")
        ф.запросы.clear()
        код, _ = синхронизировать(repo, "t", False, ф)
        ok(код == 0 and not ф.запросы, "повтор аналитики → 0 запросов")

        # круг без задачи
        круг("чужой", этап="E9")
        код, вывод = синхронизировать(repo, "t", False, ф)
        ok(any("круг чужой: нет задачи YouTrack" in с for с in вывод) and not ф.запросы, "круг без задачи")
        (кр / "чужой.md").unlink()
        # архив и неутверждённый не берутся
        круг("в архиве", где=кр / "архив")
        круг("черновой", статус="черновик")
        код, вывод = синхронизировать(repo, "t", False, ф)
        ok(not ф.запросы and not any("круг" in с for с in вывод), "архив и черновик круга пропущены")
        (кр / "черновой.md").unlink()
        (кр / "архив" / "в архиве.md").unlink()

        # круг с одной закрытой задачей; текст вне меток цел
        ф.задачи["PLX-12"] = "Свой текст до."
        круг("мой", итог="  ✓  первая  0.4 ч\n")
        ф.запросы.clear()
        код, _ = синхронизировать(repo, "t", False, ф)
        оп = ф.задачи["PLX-12"]
        ok(код == 0 and [з[0] for з in ф.запросы] == ["GET", "POST"], "GET затем POST")
        ok("- [x] первая" in оп and "- [ ] вторая" in оп and оп.count("[x]") == 1, "чек-лист [x]/[ ]")
        ok(оп.startswith("Свой текст до.") and "<!-- плексус: круг мой -->" in оп, "текст вне меток цел")
        ф.запросы.clear()
        код, _ = синхронизировать(repo, "t", False, ф)
        ok(код == 0 and [з[0] for з in ф.запросы] == ["GET"], "повтор → без POST")
        # изменение итога переписывает только блок, текст после блока цел
        ф.задачи["PLX-12"] += "\n\nХвост после."
        (кр / "мой.md").write_text((кр / "мой.md").read_text(encoding="utf-8")
                                    + "  ✓  вторая  0.2 ч\n", encoding="utf-8")
        синхронизировать(repo, "t", False, ф)
        оп = ф.задачи["PLX-12"]
        ok(оп.count("[x]") == 2 and оп.endswith("Хвост после.") and оп.startswith("Свой текст до."),
           "блок переписан, остальное цело")

        # --сухой: ничего не пишет, токена нет в выводе
        заметка("новая", "в работе")
        до = (ан / "новая.md").read_text(encoding="utf-8")
        ф.запросы.clear()
        код, вывод = синхронизировать(repo, "СЕКРЕТНЫЙТОКЕН", True, ф)
        ok(код == 0 and not ф.запросы and (ан / "новая.md").read_text(encoding="utf-8") == до, "сухой не пишет")
        ok(any(с.startswith("POST https://yt.example.com/api/issues") for с in вывод)
           and not any("СЕКРЕТНЫЙТОКЕН" in с for с in вывод), "сухой печатает запросы без токена")

        # ошибка HTTP → код 3, файл не изменён
        код, вывод = синхронизировать(repo, "t", False, Фальшивый(ошибка=True))
        ok(код == 3 and (ан / "новая.md").read_text(encoding="utf-8") == до
           and any("HTTP 500" in с for с in вывод) and not any("Traceback" in с for с in вывод), "ошибка HTTP")
    for f in fails:
        print("FAIL", f)
    print("самопроверка: " + ("провалена" if fails else "ок"))
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--сухой", action="store_true")
    ap.add_argument("--самопроверка", action="store_true")
    try:
        args = ap.parse_args()
    except SystemExit as e:
        return 2 if e.code else 0
    if args.самопроверка:
        return selftest()
    код, вывод = синхронизировать(Path(args.repo), os.environ.get("YOUTRACK_TOKEN"), args.сухой)
    print("\n".join(вывод))
    return код


if __name__ == "__main__":
    sys.exit(main())
