#!/usr/bin/env python3
"""Экран старта: дерево работы «эпик → этап → круг → задача» с пометками.

Читает .claude/plan/roadmap.md, подпланы эпиков, vault/круги/*.md, замки
.claude/locks/<круг>.json, журнал .claude/ledger.jsonl и `git status --short`.
Рисует экран и ничего не пишет; замки пишут только --взять и --снять. Счётчики для /plexus:status остаются в counters.py и streams.py.

    python3 ${CLAUDE_PLUGIN_ROOT}/lib/экран_старта.py [--repo .]
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/экран_старта.py --взять <круг> | --снять <круг>
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/экран_старта.py --выбрать auto|E<nn>|E<nn>-S<nn>
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/экран_старта.py --передача <круг>
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/экран_старта.py --самопроверка

Замок: {"кто": …, "с": "YYYY-MM-DD HH:MM", "цель": "<id или имя круга>"}.
Коды: 0 — готово; 1 — неверный вызов; 2 — занято или нечего выбрать.
Круг открыт: `статус: утверждено` и не все `### `-задачи стоят строкой `✓  <имя>` в «Итоге».
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from counters import EPIC, stages  # noqa: E402
from streams import ТИП_ЭПИКА, project_type  # noqa: E402
from заметка import тупики  # noqa: E402
import ветка_задачи  # noqa: E402

РАЗДЕЛЫ = {"## Сейчас": "Сейчас", "## Дальше": "Дальше", "## Потом": "Потом"}
МЕСЯЦЫ = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
БРОШЕН_ЧАСОВ = 4
СПИТ_ДНЕЙ = 14
МАКС_ЗАДАЧ = 5
МАКС_ЭТАПОВ = 2
МАКС_КОЛОНКА = 72
МАКС_ПЕРЕДАЧА = 6
МАКС_ТУПИКОВ = 5
НЕ_ПОВТОРЯТЬ = "Не повторять"
ПАПКИ_ОБЛАСТИ = {"docs": {"vault", "docs"}}
ЭТАП = re.compile(r"^\s*-\s*\[([ xX])\]\s+(S\d+)\s*(.*)$")
ПОСЛЕ = re.compile(r"^(.*?)\s*·\s*после\s*«(.+?)»\s*$")


# ---------- чтение ----------

def git(repo: Path, *args: str, сырой: bool = False) -> str:
    """Вывод git. Сырой — только без хвостового перевода строки: ведущий пробел статуса ` M` нужен."""
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if r.returncode != 0:
        return ""
    return r.stdout.rstrip("\n") if сырой else r.stdout.strip()


def обрезать(s: str, n: int) -> str:
    return s if len(s) <= n else s[:max(n - 1, 0)].rstrip() + "…"


def шапка(text: str) -> dict:
    out, lines = {}, text.splitlines()
    if not lines or lines[0].strip() != "---":
        return out
    for line in lines[1:]:
        if line.strip() == "---":
            break
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out


def области_проекта(road: str) -> set[str]:
    for line in road.splitlines():
        if line.startswith("Области:"):
            return set(re.findall(r"`(\w+)`", line))
    return {"skills", "lib", "docs", "evals", "debug", "infra"}


def имя_эпика(eid: str, title: str, rest: str, files: list[Path]) -> str:
    """Имя эпика из строки плана: `**E19 · Имя**`, `**E14** Имя — описание` или имя подплана."""
    if " · " in title:
        return title.split(" · ", 1)[1].strip()
    имя = re.split(r" — | · | \(", rest, maxsplit=1)[0].strip()
    if имя:
        return имя
    if files:
        return files[0].stem.split("-", 1)[-1].strip() or eid
    return eid


def эпики(repo: Path) -> list[dict]:
    plan = repo / ".claude" / "plan"
    road = (plan / "roadmap.md").read_text(encoding="utf-8")
    ptype = project_type(plan / "roadmap.md")
    out, section = [], None
    for line in road.splitlines():
        if line.startswith("## "):
            section = РАЗДЕЛЫ.get(line.strip())
            continue
        m = EPIC.search(line)
        if not section or not m:
            continue
        eid = m.group(1)
        title = line.split("**")[1]
        files = sorted(plan.glob(f"{eid}-*.md"))
        name = имя_эпика(eid, title, line.split("**", 2)[2] if line.count("**") >= 2 else "", files)
        mt = ТИП_ЭПИКА.search(line)
        out.append({"id": eid, "name": name, "section": section,
                    "тип": (mt.group(1) if mt else "") or ptype,
                    "area": line.rsplit(" · ", 1)[1].strip() if " · " in line else "",
                    "plan": files[0] if files else None})
    return out


def этапы(path: Path | None, known: set[str]) -> list[dict]:
    """Этапы подплана: id, имя, область, после, сделан. Снятые (~~) пропущены."""
    if not path:
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = ЭТАП.match(line)
        if not m or "~~" in line:
            continue
        parts = [x.strip() for x in m.group(3).split(" · ")]
        area, after = "", []
        for p in parts[1:]:
            if p.startswith("после "):
                after = re.findall(r"S\d+", p)
            elif re.fullmatch(r"[a-z]+(\+[a-z]+)*", p) and set(p.split("+")) <= known:
                area = p
        out.append({"id": m.group(2), "name": parts[0], "area": area, "after": after,
                    "done": m.group(1) in "xX"})
    return out


def круг(path: Path) -> dict | None:
    """Открытый круг файла или None (черновик, закрытый, без задач)."""
    text = path.read_text(encoding="utf-8")
    fm = шапка(text)
    status = fm.get("статус", "")
    if not status.startswith("утверждено"):
        return None
    sect, tasks, итог, goal = None, [], [], ""
    for line in text.splitlines():
        if line.startswith("## "):
            sect = line[3:].strip()
            continue
        if line.startswith("Цель:") and not goal:
            goal = line[5:].strip()
        elif sect == "Задачи" and line.startswith("### "):
            title = line[4:].strip()
            m = ПОСЛЕ.match(title)
            tasks.append({"name": m.group(1) if m else title, "after": m.group(2) if m else ""})
        elif sect == "Итог":
            m = re.match(r"^\s*✓\s+(.+?)\s*$", line)
            if m:
                итог.append(m.group(1))
    for t in tasks:
        t["done"] = any(s.startswith(t["name"]) for s in итог)
    if not tasks or all(t["done"] for t in tasks):
        return None
    dm = re.search(r"\d{4}-\d{2}-\d{2}", status)
    eid, _, sid = fm.get("этап", "").partition("-")
    return {"name": path.stem, "epic": eid, "stage": sid or None, "tasks": tasks,
            "goal": goal.replace("`", ""),
            "утверждён": datetime.strptime(dm.group(0), "%Y-%m-%d") if dm else None}


def замок(repo: Path, имя: str, now: datetime, я: str) -> dict | None:
    p = repo / ".claude" / "locks" / f"{имя}.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        since = datetime.strptime(d["с"], "%Y-%m-%d %H:%M")
    except (ValueError, KeyError):
        return None
    кто = d.get("кто", "?")
    return {"кто": "ты" if я and кто == я else кто, "с": since,
            "брошен": now - since > timedelta(hours=БРОШЕН_ЧАСОВ)}


def записи_журнала(repo: Path) -> dict[str, datetime]:
    """Круг → дата последней записи журнала."""
    out = {}
    p = repo / ".claude" / "ledger.jsonl"
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
            out[d["круг"]] = max(out.get(d["круг"], datetime.min), datetime.strptime(d["date"], "%Y-%m-%d"))
        except (ValueError, KeyError, TypeError):
            continue
    return out


def хвосты(repo: Path) -> list[str]:
    files = []
    for line in git(repo, "-c", "core.quotepath=off", "status", "--short", "-uall", сырой=True).splitlines():
        f = line[3:].split(" -> ")[-1].strip().strip('"')
        if f and not f.startswith(".claude/locks/"):
            files.append(f)
    return files


# ---------- модель ----------

def пересечение(a: str, b: str) -> list[str]:
    return sorted((set(a.split("+")) & set(b.split("+"))) - {""})


def собрать(repo: Path, now: datetime) -> dict:
    """Дерево эпиков с узлами и плоский список `узлы` — кандидаты для выбора (kind круг/этап, id, n, warn)."""
    plan = repo / ".claude" / "plan"
    road = (plan / "roadmap.md").read_text(encoding="utf-8")
    known = области_проекта(road)
    я = git(repo, "config", "user.name")
    журнал = записи_журнала(repo)
    круги = [c for c in (круг(p) for p in sorted((repo / "vault" / "круги").glob("*.md"))) if c]
    eps = эпики(repo)
    ids = {e["id"] for e in eps}
    for c in круги:  # круг эпика, которого нет в плане, не теряем
        if c["epic"] and c["epic"] not in ids:
            eps.append({"id": c["epic"], "name": "(нет в плане)", "section": "Потом", "тип": "", "area": "", "plan": None})
            ids.add(c["epic"])
    with_circle = {c["epic"] for c in круги}
    first_next = False
    показ = []
    for e in eps:
        e["этапы"] = этапы(e["plan"], known)
        e["done"], e["total"] = (stages(e["plan"])[:2] if e["plan"] else (None, None))
        take = e["section"] == "Сейчас" or e["id"] in with_circle
        if e["section"] == "Дальше" and not first_next and e["этапы"]:
            take, first_next = True, True
        if take:
            показ.append(e)
    узлы, счёт = [], [0]

    def номер() -> int:
        счёт[0] += 1
        return счёт[0]

    for e in показ:
        by_id = {s["id"]: s for s in e["этапы"]}
        e["узлы"], без_круга = [], 0

        def новый_круг(c: dict) -> dict:
            s = by_id.get(c["stage"]) if c["stage"] else None
            c["area"] = s["area"] if s and s["area"] else e["area"]
            c["lock"] = замок(repo, c["name"], now, я)
            c["n"], c["kind"], c["id"] = номер(), "круг", c["name"]
            c["занят"] = bool(c["lock"] and not c["lock"]["брошен"])
            last = max([d for d in (c["утверждён"], журнал.get(c["name"])) if d], default=None)
            c["сон"] = (now - last).days if last and not c["занят"] and (now - last).days >= СПИТ_ДНЕЙ else None
            узлы.append(c)
            return c

        for c in [c for c in круги if c["epic"] == e["id"] and not c["stage"]]:
            e["узлы"].append({"tag": "круг", "c": новый_круг(c)})
        for s in e["этапы"]:
            cs = [c for c in круги if c["epic"] == e["id"] and c["stage"] == s["id"]]
            ждёт = [d for d in s["after"] if d in by_id and not by_id[d]["done"]]
            if not cs and (s["done"] or без_круга >= МАКС_ЭТАПОВ):
                continue
            if not cs:
                без_круга += 1
            node = {"tag": "этап", "s": s, "ждёт": ждёт, "круги": [новый_круг(c) for c in cs]}
            if not cs and not ждёт:
                s.update(n=номер(), kind="этап", sel=f"{e['id']}-{s['id']}", area=s["area"] or e["area"], занят=False, сон=None)
                узлы.append(s)
            e["узлы"].append(node)
    занятые = [c for c in узлы if c["kind"] == "круг" and c["занят"]]
    for u in узлы:
        u["warn"] = ""
        if u["занят"]:
            continue
        for z in занятые:
            общие = пересечение(u["area"], z["area"])
            if общие:
                u["warn"] = f"⚠ область {'+'.join(общие)}, как у 🔒[{z['n']}]"
                break
    return {"проект": шапка(road).get("проект", repo.name), "показ": показ, "узлы": узлы,
            "занятые": занятые, "файлы": хвосты(repo)}


# ---------- вывод ----------

def метки_круга(c: dict) -> str:
    m = []
    if c["lock"]:
        m.append(f"🔒 {c['lock']['кто']}, с {c['lock']['с']:%H:%M}")
        if c["lock"]["брошен"]:
            m.append("⚠ брошен?")
    if c["warn"]:
        m.append(c["warn"])
    if c["сон"] is not None:
        m.append(f"💤 {c['сон']} дн.")
    return "   ".join(m)


def строки_круга(c: dict, отступ: str, rows: list) -> None:
    done = sum(t["done"] for t in c["tasks"])
    head = f"{отступ}└ [{c['n']}] круг «{c['name']}» — "
    rows.append((head + обрезать(c["goal"], МАКС_КОЛОНКА - len(head)), f"{done}/{len(c['tasks'])}", метки_круга(c)))
    pad = отступ + " " * 7
    shown = c["tasks"]
    if len(shown) > МАКС_ЗАДАЧ:
        rows.append((f"{pad}✓ {done} сделано", "", ""))
        shown = [t for t in shown if not t["done"]]
    done_names = {t["name"] for t in c["tasks"] if t["done"]}
    for t in shown:
        wait = f"⏸ после «{t['after']}»" if not t["done"] and t["after"] and t["after"] not in done_names else ""
        rows.append((f"{pad}{'✓' if t['done'] else '○'} {t['name']}", "", wait))


def строка_ветки(repo: Path) -> str:
    """`ВЕТКА  main` или `ВЕТКА  <имя> · задача <формулировка>` — по lib/ветка_задачи.py где."""
    try:
        строки = ветка_задачи.где(str(repo)).splitlines()
    except Exception:
        return ""
    if not строки or строки[0] == "main":
        return "ВЕТКА  main"
    имя = строки[0].removeprefix("задача ")
    return f"ВЕТКА  {имя} · задача {строки[1]}" if len(строки) > 1 else f"ВЕТКА  {имя}"


def отрисовать(модель: dict, now: datetime, ветка: str, строка_задачи: str = "") -> str:
    rows = []
    for e in модель["показ"]:
        head = f"{e['id']} {e['name']}" + (f" · {e['тип']}" if e["тип"] else "")
        rows.append(("", "", ""))
        rows.append((head, f"{e['done']}/{e['total']}" if e["total"] else "", ""))
        for node in e["узлы"]:
            if node["tag"] == "круг":
                строки_круга(node["c"], " ", rows)
                continue
            s = node["s"]
            marks = []
            if node["ждёт"]:
                marks.append("⏸ ждёт " + ", ".join(node["ждёт"]))
            if s.get("warn"):
                marks.append(s["warn"])
            num = f"[{s['n']}] " if "n" in s else ""
            rows.append((f" └ {num}{s['id']} {s['name']}", "", "   ".join(marks)))
            for c in node["круги"]:
                строки_круга(c, "    ", rows)
    rows = [(обрезать(a, МАКС_КОЛОНКА), b, c) for a, b, c in rows]
    width = max([len(r[0]) for r in rows] + [0])
    out = [f"ПЛАН  {модель['проект']} · {ветка} · {now.day} {МЕСЯЦЫ[now.month - 1]}"]
    if строка_задачи:
        out.append(строка_задачи)
    for left, cnt, marks in rows:
        out.append((left.ljust(width + 2) + cnt.ljust(6) + marks).rstrip())
    return "\n".join(out + хвосты_текст(модель))


def хвосты_текст(модель: dict) -> list[str]:
    files = модель["файлы"]
    if not files:
        return []
    n = len(files)
    слово = ("файл" if n % 10 == 1 and n % 100 != 11
             else "файла" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "файлов")
    shown = ", ".join(files[:5]) + (f" и ещё {n - 5}" if n > 5 else "")
    out = ["", f"ХВОСТЫ  {n} {слово} не закоммичены — {shown}"]
    refs = []
    for z in модель["занятые"]:
        dirs = set()
        for a in z["area"].split("+"):
            dirs |= ПАПКИ_ОБЛАСТИ.get(a, {a})
        if any(f.split("/")[0] in dirs for f in files):
            refs.append(f"🔒[{z['n']}]")
    if refs:
        out.append("        похоже, их правит " + ", ".join(refs))
    return out


# ---------- замок, выбор, передача ----------

def взять(repo: Path, имя: str, now: datetime) -> tuple[int, str]:
    """Пишет замок круга. Чужой свежий замок — код 2; свой и брошенный перезаписываются."""
    я = git(repo, "config", "user.name")
    if not я:
        return 1, "нет git config user.name — замок не на кого записать"
    файл = repo / "vault" / "круги" / f"{имя}.md"
    if not файл.exists():
        return 1, f"нет круга «{имя}» в vault/круги/ (этап без круга замок не берёт)"
    z = замок(repo, имя, now, я)
    if z and z["кто"] != "ты" and not z["брошен"]:
        return 2, f"круг «{имя}» занят: {z['кто']}, с {z['с']:%H:%M}"
    цель = шапка(файл.read_text(encoding="utf-8")).get("этап") or имя
    p = repo / ".claude" / "locks" / f"{имя}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"кто": я, "с": now.strftime("%Y-%m-%d %H:%M"), "цель": цель}, ensure_ascii=False), encoding="utf-8")
    return 0, f"замок на круг «{имя}» взят"


def снять(repo: Path, имя: str, now: datetime) -> tuple[int, str]:
    """Удаляет только свой замок."""
    p = repo / ".claude" / "locks" / f"{имя}.json"
    if not p.exists():
        return 0, f"замка на круг «{имя}» нет"
    z = замок(repo, имя, now, git(repo, "config", "user.name"))
    if not z or z["кто"] != "ты":
        return 2, f"замок на круг «{имя}» не твой" + (f": {z['кто']}" if z else "")
    p.unlink()
    return 0, f"замок на круг «{имя}» снят"


def выбрать(модель: dict, цель: str) -> tuple[int, str]:
    """auto | E<nn> | E<nn>-S<nn> → строка `круг «имя»` / `этап E29-S10`. Занятый круг не выбирается."""
    m = re.fullmatch(r"(E\d+)(?:-(S\d+))?", цель)
    if цель != "auto" and not m:
        return 1, "выбрать: auto, E<nn> или E<nn>-S<nn>"
    свободные = [u for u in модель["узлы"] if not u["занят"]]
    if m and m.group(2):
        sel = f"{m.group(1)}-{m.group(2)}"
        свободные = [u for u in свободные if (u["kind"] == "этап" and u["sel"] == sel)
                     or (u["kind"] == "круг" and u["epic"] == m.group(1) and u["stage"] == m.group(2))]
        ответ = свободные[:1]
    else:
        if m:
            свободные = [u for u in свободные if (u["sel"].split("-")[0] if u["kind"] == "этап" else u["epic"]) == m.group(1)]
        круги = [u for u in свободные if u["kind"] == "круг" and not u["warn"]]
        этапы_ = [u for u in свободные if u["kind"] == "этап" and not u["warn"]]
        ответ = ([max(круги, key=lambda c: sum(t["done"] for t in c["tasks"]) / len(c["tasks"]))] if круги
                 else этапы_[:1] or свободные[:1])
    if not ответ:
        return 2, f"нечего выбрать для «{цель}»: всё занято или нет такого этапа"
    u = ответ[0]
    return 0, f"круг «{u['name']}»" if u["kind"] == "круг" else f"этап {u['sel']}"


def строки_тупиков(repo: Path, имя: str, есть: list[str]) -> list[str]:
    """Строки `тупик: [[имя]]` для эпика круга: без повторов с `есть`, вместе с `есть` не больше МАКС_ТУПИКОВ."""
    файл = repo / "vault" / "круги" / f"{имя}.md"
    if not файл.exists():
        return []
    эпик = шапка(файл.read_text(encoding="utf-8")).get("этап", "").partition("-")[0].strip()
    if not эпик:
        return []
    занято = "\n".join(есть)
    новые = [f"тупик: [[{n}]]" for n in тупики(repo / "vault", эпик) if f"[[{n}]]" not in занято and n not in занято]
    return новые[:max(МАКС_ТУПИКОВ - len(есть), 0)]


def передача(repo: Path, имя: str) -> tuple[int, str]:
    """Передача из vault/передачи/<имя>.md («Ждёт тебя» первым) или, если её нет, «Сделано/Дальше» из файла круга."""
    p = repo / "vault" / "передачи" / f"{имя}.md"
    if p.exists():
        текст = p.read_text(encoding="utf-8")
        if текст.startswith("---"):
            текст = текст.split("---", 2)[-1]
        части, имя_раздела = {}, None
        for line in текст.splitlines():
            if line.startswith("## "):
                имя_раздела = line[3:].strip()
                части[имя_раздела] = []
            elif имя_раздела:
                части[имя_раздела].append(line)
        строки = [x for x in части.get(НЕ_ПОВТОРЯТЬ, []) if x.strip()]
        новые = строки_тупиков(repo, имя, строки)
        if новые:
            if НЕ_ПОВТОРЯТЬ not in части:  # раздел встаёт перед «Первый шаг»/«Продолжить», иначе в конец
                иначе = list(части)
                места = [i for i, k in enumerate(иначе) if k in ("Первый шаг", "Продолжить")]
                иначе.insert(места[0] if места else len(иначе), НЕ_ПОВТОРЯТЬ)
                части = {k: части.get(k, []) for k in иначе}
            части[НЕ_ПОВТОРЯТЬ] = [*строки, *новые]
        порядок = sorted(части, key=lambda k: k != "Ждёт тебя")  # sorted стабилен: остальные в своём порядке
        return 0, "\n\n".join(f"## {k}\n" + "\n".join(части[k]).strip() for k in порядок)
    файл = repo / "vault" / "круги" / f"{имя}.md"
    if not файл.exists():
        return 1, f"нет ни передачи, ни круга «{имя}»"
    sect, задачи, итог = None, [], []
    for line in файл.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            sect = line[3:].strip()
        elif sect == "Задачи" and line.startswith("### "):
            title = line[4:].strip()
            m = ПОСЛЕ.match(title)
            задачи.append({"name": m.group(1) if m else title, "проверка": ""})
        elif sect == "Задачи" and задачи and line.startswith("проверка:"):
            задачи[-1]["проверка"] = line.strip()
        elif sect == "Итог":
            m = re.match(r"^\s*✓\s+(.+?)\s*$", line)
            if m:
                итог.append(m.group(1))
    сделаны = [t for t in задачи if any(s.startswith(t["name"]) for s in итог)]
    дальше = next((t for t in задачи if t not in сделаны), None)
    хвост = ([f"○ {дальше['name']}"] + ([обрезать(дальше["проверка"], 100)] if дальше["проверка"] else [])) if дальше else ["— всё закрыто"]
    место = max(МАКС_ПЕРЕДАЧА - 2 - len(хвост), 1)
    имена = [f"✓ {t['name']}" for t in сделаны] or ["— пока ничего"]
    if len(имена) > место:
        имена = [f"✓ {len(сделаны)} сделано"] + имена[len(имена) - (место - 1):] if место > 1 else [f"✓ {len(сделаны)} сделано"]
    вывод = ["## Сделано", *имена, "## Дальше", *хвост]
    новые = строки_тупиков(repo, имя, [])  # сверх МАКС_ПЕРЕДАЧА: «Сделано/Дальше» не урезаем
    if новые:
        вывод += [f"## {НЕ_ПОВТОРЯТЬ}", *новые]
    return 0, "\n".join(вывод)


# ---------- самопроверка ----------

def самопроверка() -> int:
    now = datetime(2026, 11, 3, 15, 0)
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        plan = repo / ".claude" / "plan"
        (repo / "vault" / "круги").mkdir(parents=True)
        (repo / ".claude" / "locks").mkdir(parents=True)
        plan.mkdir(parents=True)
        (plan / "roadmap.md").write_text(
            "---\nпроект: образец\nтип: развитие\n---\n\nОбласти: `skills` `lib` `docs`\n\n## Сейчас\n\n"
            "- **E01 · Первый эпик** — а · тип: перенос · 1/5 · skills+lib\n\n"
            "## Дальше\n\n- **E02 · Второй эпик** — б · 0/1 · docs\n", encoding="utf-8")
        (plan / "E01-первый.md").write_text(
            "- [x] S01 готовый этап · lib\n- [ ] S02 занятый этап · skills\n- [ ] S03 ждущий этап · lib · после S02\n"
            "- [ ] S04 свободный этап · skills · после S01\n- [ ] S05 второй без круга · lib\n- [ ] S06 третий без круга · lib\n", encoding="utf-8")
        (plan / "E02-второй.md").write_text("- [ ] S01 этап без круга · docs\n", encoding="utf-8")

        def файл_круга(имя, этап, дата, задачи, итог, цель=None):
            t = "".join(f"### {x}\nкому: работник\nпроверка: тест {x.split(' · ')[0]}\n\n" for x in задачи)
            i = "".join(f"  ✓  {x}\n" for x in итог)
            (repo / "vault" / "круги" / f"{имя}.md").write_text(
                f"---\nэтап: {этап}\nстатус: утверждено {дата}\n---\n\n# {имя}\n\nЦель: {цель or 'цель круга ' + имя + '.'}\n\n"
                f"## Задачи\n\n{t}## Итог\n\n```\n{i}```\n", encoding="utf-8")

        файл_круга("занятый круг", "E01-S02", "2026-11-01", ["шаблон", "модуль"], ["шаблон"],
                  "цель `круга` занятый круг, " + "очень длинная часть цели, " * 6)
        файл_круга("свободный круг", "E01-S04", "2026-11-02", ["раз", "два · после «раз»"], [])
        файл_круга("круг без этапа", "E02", "2026-10-04", list("абвгдеж"), ["а", "б"])
        файл_круга("закрытый круг", "E01-S01", "2026-10-30", ["я"], ["я"])
        (repo / "vault" / "круги" / "черновик.md").write_text("---\nэтап: E01\nстатус: черновик\n---\n### т\n", encoding="utf-8")
        (repo / ".claude" / "ledger.jsonl").write_text(
            json.dumps({"круг": "прочий", "date": "2026-10-01"}, ensure_ascii=False) + "\n", encoding="utf-8")
        (repo / ".claude" / "locks" / "занятый круг.json").write_text(
            json.dumps({"кто": "Ваня", "с": "2026-11-03 14:20", "цель": "занятый круг"}, ensure_ascii=False), encoding="utf-8")
        for args in (["init", "-q", "-b", "main"], ["config", "user.name", "Тест"], ["config", "user.email", "t@t"],
                     ["add", "-A"], ["commit", "-qm", "образец"]):
            subprocess.run(["git", *args], cwd=repo, capture_output=True)
        with open(repo / ".claude" / "ledger.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"круг": "прочий", "date": "2026-10-02"}, ensure_ascii=False) + "\n")
        (repo / "skills").mkdir()
        (repo / "skills" / "правка.md").write_text("x", encoding="utf-8")

        text = отрисовать(собрать(repo, now), now, "main", строка_ветки(repo))
        print(text)
        ожидаем = [
            "ПЛАН  образец · main · 3 ноя",
            "ВЕТКА  main",
            "E01 Первый эпик · перенос",
            "└ S02 занятый этап",
            "└ [1] круг «занятый круг» — цель круга занятый",
            "1/2   🔒 Ваня, с 14:20",
            "○ модуль",
            "└ S03 ждущий этап",
            "⏸ ждёт S02",
            "└ [2] круг «свободный круг»",
            "⚠ область skills, как у 🔒[1]",
            "⏸ после «раз»",
            "E02 Второй эпик · развитие",
            "└ [3] S05 второй без круга",
            "└ [4] круг «круг без этапа»",
            "💤 30 дн.",
            "✓ 2 сделано",
            "└ [5] S01 этап без круга",
            "ХВОСТЫ  2 файла не закоммичены — .claude/ledger.jsonl, skills/правка.md",
            "похоже, их правит 🔒[1]",
        ]
        запрещено = [("закрытый круг", "закрытый круг показан"), ("черновик", "черновик показан"),
                     ("S06", "третий этап без круга показан"), ("○ а", "сделанная задача открыта")]
        bad = 0
        for s in ожидаем:
            if s not in text:
                print(f"не ок  нет: {s}")
                bad += 1
        for s, почему in запрещено:
            if s in text:
                print(f"не ок  {почему}")
                bad += 1
        if "`" in text:
            print("не ок  обратные кавычки в цели")
            bad += 1
        for line in text.splitlines():
            места = [line.index(з) for з in ("🔒", "⚠", "💤") if з in line]
            if места and min(места) > МАКС_КОЛОНКА + 2 + 6:
                print(f"не ок  пометка уехала за колонку: {line}")
                bad += 1
        старый = замок(repo, "занятый круг", now.replace(hour=20), "Ваня")
        if not (старый and старый["брошен"] and старый["кто"] == "ты"):
            print("не ок  замок старше 4 ч / «ты»")
            bad += 1
        модель = собрать(repo, now)

        def сверить(что, получено, ожидалось):
            nonlocal bad
            if получено != ожидалось:
                print(f"не ок  {что}: {получено!r}, ждали {ожидалось!r}")
                bad += 1

        # выбор
        сверить("auto", выбрать(модель, "auto"), (0, "круг «круг без этапа»"))
        сверить("эпик со свободным этапом", выбрать(модель, "E01"), (0, "этап E01-S05"))
        сверить("эпик E02", выбрать(модель, "E02"), (0, "круг «круг без этапа»"))
        сверить("этап с занятым кругом", выбрать(модель, "E01-S02")[0], 2)
        сверить("круг этапа (с ⚠ — по прямому выбору)", выбрать(модель, "E01-S04"), (0, "круг «свободный круг»"))
        сверить("сам этап", выбрать(модель, "E02-S01"), (0, "этап E02-S01"))
        сверить("нет эпика", выбрать(модель, "E09")[0], 2)
        сверить("имя через ·", имя_эпика("E19", "E19 · Проводки", " — описание", []), "Проводки")
        сверить("имя после **", имя_эпика("E14", "E14", " Логи для человека — описание · 11/16 · back", []), "Логи для человека")
        сверить("имя из подплана", имя_эпика("E13", "E13", "", [Path("E13-мелочи аудита.md")]), "мелочи аудита")
        сверить("имени нет", имя_эпика("E12", "E12", "", []), "E12")
        сверить("плохой аргумент", выбрать(модель, "что-то")[0], 1)
        круг_ = {"kind": "круг", "name": "x", "занят": False, "warn": "⚠", "epic": "E1", "stage": None, "tasks": [{"done": False}]}
        занят_ = dict(круг_, name="y", занят=True, warn="")
        сверить("первый свободный, хоть с ⚠", выбрать({"узлы": [занят_, круг_]}, "auto"), (0, "круг «x»"))
        сверить("всё занято", выбрать({"узлы": [занят_]}, "auto")[0], 2)
        большая = dict(круг_, name="большая", warn="", tasks=[{"done": True}, {"done": False}])
        малая = dict(круг_, name="малая", warn="", tasks=[{"done": False}, {"done": False}])
        сверить("наибольшая доля сделанного", выбрать({"узлы": [малая, большая]}, "auto"), (0, "круг «большая»"))

        # замок
        замки = repo / ".claude" / "locks"
        сверить("чужой свежий замок", взять(repo, "занятый круг", now)[0], 2)
        сверить("замок остался чужим", "Ваня" in (замки / "занятый круг.json").read_text(encoding="utf-8"), True)
        сверить("взять свободный", взять(repo, "свободный круг", now)[0], 0)
        данные = json.loads((замки / "свободный круг.json").read_text(encoding="utf-8"))
        сверить("содержимое замка", данные, {"кто": "Тест", "с": "2026-11-03 15:00", "цель": "E01-S04"})
        сверить("взять свой повторно", взять(repo, "свободный круг", now.replace(hour=16))[0], 0)
        сверить("время обновлено", json.loads((замки / "свободный круг.json").read_text(encoding="utf-8"))["с"], "2026-11-03 16:00")
        сверить("нет круга — замка нет", взять(repo, "E02-S01", now)[0], 1)
        сверить("снять чужой", снять(repo, "занятый круг", now)[0], 2)
        сверить("чужой остался", (замки / "занятый круг.json").exists(), True)
        сверить("снять свой", снять(repo, "свободный круг", now)[0], 0)
        сверить("свой удалён", (замки / "свободный круг.json").exists(), False)
        сверить("снять без замка", снять(repo, "свободный круг", now)[0], 0)
        (замки / "занятый круг.json").write_text(
            json.dumps({"кто": "Ваня", "с": "2026-11-03 09:00", "цель": "x"}, ensure_ascii=False), encoding="utf-8")
        сверить("брошенный можно взять", взять(repo, "занятый круг", now)[0], 0)
        сверить("брошенный стал моим", json.loads((замки / "занятый круг.json").read_text(encoding="utf-8"))["кто"], "Тест")
        снять(repo, "занятый круг", now)

        # передача
        ветка_задачи.завести(str(repo), "Проверка ветки")
        имя_ветки = ветка_задачи.имя("Проверка ветки")
        text2 = отрисовать(собрать(repo, now), now, имя_ветки, строка_ветки(repo))
        сверить("строка ВЕТКА на ветке задачи", f"ВЕТКА  {имя_ветки} · задача Проверка ветки" in text2, True)
        subprocess.run(["git", "switch", "-q", "main"], cwd=repo, capture_output=True)
        код, текст_ = передача(repo, "занятый круг")
        сверить("передача без файла", текст_, "## Сделано\n✓ шаблон\n## Дальше\n○ модуль\nпроверка: тест модуль")
        (repo / "vault" / "передачи").mkdir()
        (repo / "vault" / "передачи" / "свободный круг.md").write_text(
            "---\nкруг: свободный круг\nкто: Тест\n---\n\n## Сделано\nа\n\n## Остановились на\nб\n\n## Ждёт тебя\nответь\n\n## Первый шаг\nг\n",
            encoding="utf-8")
        код, текст_ = передача(repo, "свободный круг")
        сверить("передача из файла", [x for x in текст_.splitlines() if x.startswith("## ")],
                ["## Ждёт тебя", "## Сделано", "## Остановились на", "## Первый шаг"])
        сверить("передача без шапки", "круг:" in текст_, False)
        код, текст_ = передача(repo, "круг без этапа")
        сверить("передача: не больше 6 строк", len(текст_.splitlines()) <= МАКС_ПЕРЕДАЧА, True)
        сверить("передача: нет круга", передача(repo, "нет такого")[0], 1)

        # тупики на старте
        сверить("нет vault/тупики — раздела нет", НЕ_ПОВТОРЯТЬ in передача(repo, "занятый круг")[1], False)
        (repo / "vault" / "тупики").mkdir()

        def тупик(n, эпик):
            (repo / "vault" / "тупики" / f"{n}.md").write_text(f"---\ntags: [тупики]\nэпик: {эпик}\n---\n# {n}\n", encoding="utf-8")
        for n in "абвгде":
            тупик(f"тупик {n}", "E01")
        тупик("чужой тупик", "E02")
        код, текст_ = передача(repo, "занятый круг")
        сверить("запасной вывод: Сделано/Дальше цел",
                текст_.startswith("## Сделано\n✓ шаблон\n## Дальше\n○ модуль\nпроверка: тест модуль\n## Не повторять\n"), True)
        сверить("запасной вывод: ≤5 тупиков", текст_.count("тупик: [["), МАКС_ТУПИКОВ)
        сверить("чужого эпика нет", "чужой тупик" in текст_, False)
        код, текст_ = передача(repo, "свободный круг")
        сверить("файл передачи: раздел добавлен перед «Первый шаг»",
                [x for x in текст_.splitlines() if x.startswith("## ")],
                ["## Ждёт тебя", "## Сделано", "## Остановились на", "## Не повторять", "## Первый шаг"])
        сверить("файл передачи: ≤5 тупиков", текст_.count("тупик: [["), МАКС_ТУПИКОВ)
        (repo / "vault" / "передачи" / "свободный круг.md").write_text(
            "---\nкруг: свободный круг\n---\n\n## Не повторять\nтупик: [[тупик а]]\nсвоё\n\n## Первый шаг\nг\n", encoding="utf-8")
        текст_ = передача(repo, "свободный круг")[1]
        сверить("без повторов", текст_.count("[[тупик а]]"), 1)
        раздел = текст_.split("## Не повторять\n")[1].split("\n\n")[0].splitlines()
        сверить("свои строки целы, в разделе ровно 5", ("своё" in раздел, len(раздел)), (True, МАКС_ТУПИКОВ))
        сверить("тупик другого эпика виден своему кругу", "[[чужой тупик]]" in передача(repo, "круг без этапа")[1], True)
        (repo / "vault" / "круги" / "пустой эпик.md").write_text(
            "---\nэтап: E09\nстатус: утверждено 2026-11-01\n---\n\n## Задачи\n\n### т\n", encoding="utf-8")
        сверить("у эпика нет тупиков — раздела нет", НЕ_ПОВТОРЯТЬ in передача(repo, "пустой эпик")[1], False)
        print("самопроверка: " + ("не ок" if bad else "ок"))
        return 1 if bad else 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--самопроверка", action="store_true")
    ap.add_argument("--взять", metavar="КРУГ")
    ap.add_argument("--снять", metavar="КРУГ")
    ap.add_argument("--выбрать", metavar="auto|E<nn>|E<nn>-S<nn>")
    ap.add_argument("--передача", metavar="КРУГ")
    args = ap.parse_args()
    if args.самопроверка:
        return самопроверка()
    repo = Path(args.repo).resolve()
    if not (repo / ".claude" / "plan" / "roadmap.md").exists():
        print("нет .claude/plan/roadmap.md — запусти /plexus:init")
        return 1
    now = datetime.now()
    for флаг, действие in ((args.взять, lambda x: взять(repo, x, now)), (args.снять, lambda x: снять(repo, x, now)),
                           (args.передача, lambda x: передача(repo, x)),
                           (args.выбрать, lambda x: выбрать(собрать(repo, now), x))):
        if флаг:
            код, текст = действие(флаг)
            print(текст)
            return код
    print(отрисовать(собрать(repo, now), now, git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "—", строка_ветки(repo)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
