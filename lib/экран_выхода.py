#!/usr/bin/env python3
"""Экран выхода: чек-лист двух уровней, передача, закрытие круга, строка журнала.

Круг читает как экран_старта.py (шапка, эпики, этапы — импортом), но и закрытый:
задача сделана, если в «Итоге» файла круга есть строка `✓  <имя задачи>`.

    python3 ${CLAUDE_PLUGIN_ROOT}/lib/экран_выхода.py --чеклист <круг> [--repo .]
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/экран_выхода.py --передача <круг> --из <черновик.md>
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/экран_выхода.py --закрыть <круг>
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/экран_выхода.py --журнал <круг> --статус закрыт|пауза
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/экран_выхода.py --вливание <круг> [--да]
    python3 ${CLAUDE_PLUGIN_ROOT}/lib/экран_выхода.py --самопроверка

--вливание: где мы и спрашивать ли про main. Первая строка — `main` (задачи нет, как раньше),
`вопрос` (ветка задачи, круг закрыт: спросить «влить в main?»), `пауза` (ветка задачи, круг
не закрыт: коммит в ветку, вопроса нет). С --да при `вопрос` зовёт `ветка_задачи.py влить`;
конфликт → одна строка с причиной, код 2, ветка не тронута. Последняя строка — `остался: main`
или `остался: ветка <имя>`.
--чеклист: `КРУГ «имя»  n/m` и задачи ✓/○; `ЭПИК E32 название  n/m` и этапы ✓/○
(этап этого круга — `← этот круг`); последняя строка `продолжить: /plexus:start <id>`
(<id> — `этап` из шапки круга, иначе имя круга) или `круг закрыт`.
--передача: переписывает vault/передачи/<круг>.md целиком; разделы только из списка,
в порядке списка, пустые не пишутся, в разделе не больше 5 строк.
--закрыть: только когда все задачи ✓; удаляет передачу, переносит круг в vault/круги/архив/.
--журнал: строка в .claude/ledger.jsonl (кто — git config user.name).

Коды: 0 — готово; 1 — неверный вызов; 2 — отказ с причиной (ничего не тронуто).
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from экран_старта import ПОСЛЕ, git, области_проекта, шапка, эпики, этапы  # noqa: E402
from имя_файла import проверить  # noqa: E402

РАЗДЕЛЫ_ПЕРЕДАЧИ = ["Сделано", "Остановились на", "Ждёт тебя", "Читать только", "Проверка",
                    "Рабочая копия", "Не повторять", "Первый шаг", "Продолжить"]
МАКС_СТРОК = 5


# ---------- чтение ----------

def найти_круг(repo: Path, имя: str) -> Path | None:
    for папка in (repo / "vault" / "круги", repo / "vault" / "круги" / "архив"):
        p = папка / f"{имя}.md"
        if p.is_file():
            return p
    return None


def прочитать_круг(path: Path) -> dict:
    """Круг файла, в том числе закрытый: имя, шапка, задачи с done."""
    text = path.read_text(encoding="utf-8")
    sect, tasks, итог = None, [], []
    for line in text.splitlines():
        if line.startswith("## "):
            sect = line[3:].strip()
        elif sect == "Задачи" and line.startswith("### "):
            title = line[4:].strip()
            m = ПОСЛЕ.match(title)
            tasks.append({"name": m.group(1) if m else title})
        elif sect == "Итог":
            m = re.match(r"^\s*✓\s+(.+?)\s*$", line)
            if m:
                итог.append(m.group(1))
    for t in tasks:
        t["done"] = any(s.startswith(t["name"]) for s in итог)
    fm = шапка(text)
    этап = fm.get("этап", "")
    eid, _, sid = этап.partition("-")
    return {"name": path.stem, "этап": этап, "epic": eid, "stage": sid, "tasks": tasks}


def проверка_имени(имя: str) -> str | None:
    причина = проверить(f"{имя}.md")
    return f"имя круга «{имя}» не годится для файла: {причина}" if причина else None


def открыть(repo: Path, имя: str) -> tuple[dict | None, Path | None, str]:
    """(круг, путь, причина отказа)."""
    причина = проверка_имени(имя)
    if причина:
        return None, None, причина
    p = найти_круг(repo, имя)
    if not p:
        return None, None, f"нет круга «{имя}» в vault/круги/"
    return прочитать_круг(p), p, ""


def кто(repo: Path) -> str:
    return git(repo, "config", "user.name") or "—"


# ---------- команды ----------

def чеклист(repo: Path, имя: str) -> tuple[int, str]:
    c, _, why = открыть(repo, имя)
    if not c:
        return 2, why
    сделано = sum(t["done"] for t in c["tasks"])
    rows = [f"КРУГ «{c['name']}»  {сделано}/{len(c['tasks'])}"]
    rows += [f"  {'✓' if t['done'] else '○'} {t['name']}" for t in c["tasks"]]
    эпик = next((e for e in эпики(repo) if e["id"] == c["epic"]), None)
    if эпик:
        road = (repo / ".claude" / "plan" / "roadmap.md").read_text(encoding="utf-8")
        st = этапы(эпик["plan"], области_проекта(road))
        rows.append(f"ЭПИК {эпик['id']} {эпик['name']}  {sum(s['done'] for s in st)}/{len(st)}")
        for s in st:
            метка = "  ← этот круг" if s["id"] == c["stage"] else ""
            rows.append(f"  {'✓' if s['done'] else '○'} {s['id']} {s['name']}{метка}")
    else:
        rows.append(f"ЭПИК {c['epic'] or '—'} не найден в плане")
    rows.append("круг закрыт" if сделано == len(c["tasks"]) and c["tasks"]
                else f"продолжить: /plexus:start {c['этап'] or c['name']}")
    return 0, "\n".join(rows)


def разобрать_черновик(текст: str) -> tuple[dict | None, str]:
    """({раздел: [строки]}, причина). Шапка черновика, если есть, снимается."""
    if текст.startswith("---"):
        текст = текст.split("---", 2)[-1]
    части, текущий = {}, None
    for line in текст.splitlines():
        if line.startswith("## "):
            текущий = line[3:].strip()
            if текущий not in РАЗДЕЛЫ_ПЕРЕДАЧИ:
                return None, f"раздел «{текущий}» вне списка ({', '.join(РАЗДЕЛЫ_ПЕРЕДАЧИ)})"
            if текущий in части:
                return None, f"раздел «{текущий}» повторён"
            части[текущий] = []
        elif line.strip():
            if текущий is None:
                return None, "текст до первого раздела"
            части[текущий].append(line.rstrip())
    for k, v in части.items():
        if len(v) > МАКС_СТРОК:
            return None, f"в разделе «{k}» {len(v)} строк, можно не больше {МАКС_СТРОК}"
    return {k: v for k, v in части.items() if v}, ""


def передача(repo: Path, имя: str, черновик: Path) -> tuple[int, str]:
    c, _, why = открыть(repo, имя)
    if not c:
        return 2, why
    if not черновик.is_file():
        return 1, f"нет черновика {черновик}"
    части, why = разобрать_черновик(черновик.read_text(encoding="utf-8"))
    if части is None:
        return 2, f"черновик не принят: {why}"
    if not части:
        return 2, "черновик не принят: нет ни одного непустого раздела"
    out = ["---", f"круг: {имя}", f"этап: {c['этап']}", f"кто: {кто(repo)}",
           f"дата: {date.today().isoformat()}", "---", ""]
    for k in РАЗДЕЛЫ_ПЕРЕДАЧИ:
        if k in части:
            out += [f"## {k}", *части[k], ""]
    цель = repo / "vault" / "передачи" / f"{имя}.md"
    цель.parent.mkdir(parents=True, exist_ok=True)
    цель.write_text("\n".join(out), encoding="utf-8")
    return 0, f"передача: vault/передачи/{имя}.md ({len(части)} разд.)"


def закрыть(repo: Path, имя: str) -> tuple[int, str]:
    c, p, why = открыть(repo, имя)
    if not c:
        return 2, why
    открытые = [t["name"] for t in c["tasks"] if not t["done"]]
    if not c["tasks"]:
        return 2, "в круге нет задач"
    if открытые:
        return 2, "не закрыто:\n" + "\n".join(f"○ {n}" for n in открытые)
    архив = repo / "vault" / "круги" / "архив"
    if p.parent == архив:
        return 2, f"круг «{имя}» уже в архиве"
    if (архив / p.name).exists():
        return 2, f"в архиве уже есть «{p.name}»"
    архив.mkdir(parents=True, exist_ok=True)
    shutil.move(str(p), str(архив / p.name))
    пер = repo / "vault" / "передачи" / f"{имя}.md"
    if пер.exists():
        пер.unlink()
    return 0, f"круг «{имя}» закрыт: в vault/круги/архив/, передача удалена"


def журнал(repo: Path, имя: str, статус: str) -> tuple[int, str]:
    c, _, why = открыть(repo, имя)
    if not c:
        return 2, why
    эпик = next((e for e in эпики(repo) if e["id"] == c["epic"]), None)
    area = ""
    if эпик:
        road = (repo / ".claude" / "plan" / "roadmap.md").read_text(encoding="utf-8")
        st = next((s for s in этапы(эпик["plan"], области_проекта(road)) if s["id"] == c["stage"]), None)
        area = (st or {}).get("area") or эпик["area"]
    строка = {"date": date.today().isoformat(), "круг": имя, "epic": c["epic"], "area": area,
              "status": статус, "branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "—",
              "задач": len(c["tasks"]), "ok": sum(t["done"] for t in c["tasks"]),
              "кто": кто(repo), "commits": []}
    путь = repo / ".claude" / "ledger.jsonl"
    путь.parent.mkdir(parents=True, exist_ok=True)
    with open(путь, "a", encoding="utf-8") as f:
        f.write(json.dumps(строка, ensure_ascii=False) + "\n")
    return 0, f"журнал: «{имя}» — {статус}"


def вливание(repo: Path, имя: str, да: bool) -> tuple[int, str]:
    c, _, why = открыть(repo, имя)
    if not c:
        return 2, why
    скрипт = str(Path(__file__).resolve().parent / "ветка_задачи.py")

    def зов(*a):
        return subprocess.run([sys.executable, скрипт, "--repo", str(repo), *a],
                              capture_output=True, text=True, encoding="utf-8")

    р = зов("где")
    строки = р.stdout.strip().splitlines()
    if р.returncode or not строки:
        return 2, "не смог узнать ветку: " + (р.stdout.strip() or р.stderr.strip())
    if строки[0] == "main":
        return 0, "main\nостался: main"
    ветка = строки[0].removeprefix("задача ")
    закрыт = bool(c["tasks"]) and all(t["done"] for t in c["tasks"])
    if not закрыт:
        return 0, f"пауза\nостался: ветка {ветка}"
    if not да:
        return 0, f"вопрос\nвлить в main?\nостался: ветка {ветка}"
    р = зов("влить")
    итог = р.stdout.strip()
    if р.returncode:
        return 2, f"{итог}\nостался: ветка {ветка}"
    return 0, f"влито\n{итог}\nостался: main"


# ---------- самопроверка ----------

def самопроверка() -> int:
    bad = 0

    def сверить(что, получено, ожидалось):
        nonlocal bad
        if получено != ожидалось:
            print(f"не ок  {что}: {получено!r}, ждали {ожидалось!r}")
            bad += 1

    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        plan = repo / ".claude" / "plan"
        plan.mkdir(parents=True)
        (repo / "vault" / "круги").mkdir(parents=True)
        (plan / "roadmap.md").write_text(
            "---\nпроект: образец\nтип: развитие\n---\n\nОбласти: `skills` `lib`\n\n## Сейчас\n\n"
            "- **E01 · Первый эпик** — а · 1/2 · skills+lib\n", encoding="utf-8")
        (plan / "E01-первый.md").write_text(
            "- [x] S01 первый этап · lib\n- [ ] S02 второй этап · skills\n", encoding="utf-8")

        def файл_круга(имя, этап, задачи, итог):
            t = "".join(f"### {x}\nкому: работник\nпроверка: тест\n\n" for x in задачи)
            i = "".join(f"  ✓  {x}\n" for x in итог)
            (repo / "vault" / "круги" / f"{имя}.md").write_text(
                f"---\nэтап: {этап}\nстатус: утверждено 2026-11-01\n---\n\n# {имя}\n\nЦель: х.\n\n"
                f"## Задачи\n\n{t}## Итог\n\n```\n{i}```\n", encoding="utf-8")

        файл_круга("рабочий", "E01-S02", ["раз", "два · после «раз»"], ["раз"])
        файл_круга("без этапа", "", ["один"], ["один"])
        файл_круга("плохо:имя", "E01-S02", ["раз"], [])
        for args in (["init", "-q", "-b", "main"], ["config", "user.name", "Тест"],
                     ["config", "user.email", "t@t"], ["add", "-A"], ["commit", "-qm", "образец"]):
            subprocess.run(["git", *args], cwd=repo, capture_output=True)

        # чеклист
        код, текст = чеклист(repo, "рабочий")
        сверить("чеклист: код", код, 0)
        сверить("чеклист: вывод", текст.splitlines(), [
            "КРУГ «рабочий»  1/2", "  ✓ раз", "  ○ два",
            "ЭПИК E01 Первый эпик  1/2", "  ✓ S01 первый этап", "  ○ S02 второй этап  ← этот круг",
            "продолжить: /plexus:start E01-S02"])
        код, текст = чеклист(repo, "без этапа")
        сверить("чеклист закрытого: последняя строка", текст.splitlines()[-1], "круг закрыт")
        сверить("чеклист без этапа: эпик назван", "не найден в плане" in текст, True)
        сверить("чеклист: нет круга", чеклист(repo, "нет такого")[0], 2)
        сверить("чеклист: плохое имя", чеклист(repo, "плохо:имя")[0], 2)

        # передача
        черн = repo / "черновик.md"
        черн.write_text(
            "## Проверка\n`тест` → ок\n\n## Сделано\nа\nб\n\n## Ждёт тебя\n\n## Первый шаг\nг\n\n"
            "## Продолжить\n`/plexus:start E01-S02`\n", encoding="utf-8")
        пер = repo / "vault" / "передачи" / "рабочий.md"
        код, текст = передача(repo, "рабочий", черн)
        сверить("передача: код", код, 0)
        строки = пер.read_text(encoding="utf-8").splitlines()
        сверить("передача: шапка", [x.split(":")[0] for x in строки[1:5]], ["круг", "этап", "кто", "дата"])
        сверить("передача: кто", строки[3], "кто: Тест")
        сверить("передача: порядок и пустые", [x for x in строки if x.startswith("## ")],
                ["## Сделано", "## Проверка", "## Первый шаг", "## Продолжить"])
        import экран_старта
        сверить("передача читается экраном старта", "## Сделано" in экран_старта.передача(repo, "рабочий")[1], True)
        before = пер.read_text(encoding="utf-8")
        черн.write_text("## Сделано\n" + "\n".join("с" * (i + 1) for i in range(6)) + "\n", encoding="utf-8")
        сверить("передача: 6 строк", передача(repo, "рабочий", черн)[0], 2)
        черн.write_text("## Сделано\nа\n\n## Выдумка\nб\n", encoding="utf-8")
        сверить("передача: чужой раздел", передача(repo, "рабочий", черн)[0], 2)
        сверить("отказ не тронул файл", пер.read_text(encoding="utf-8"), before)
        черн.write_text("## Сделано\nа\n", encoding="utf-8")
        сверить("передача: плохое имя", передача(repo, "плохо:имя", черн)[0], 2)
        сверить("плохое имя: файла нет", (repo / "vault" / "передачи" / "плохо:имя.md").exists(), False)
        сверить("передача: нет черновика", передача(repo, "рабочий", repo / "нет.md")[0], 1)

        # журнал
        код, _ = журнал(repo, "рабочий", "пауза")
        сверить("журнал: код", код, 0)
        z = json.loads((repo / ".claude" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        сверить("журнал: строка", {k: z[k] for k in ("круг", "epic", "area", "status", "задач", "ok", "кто", "commits")},
                {"круг": "рабочий", "epic": "E01", "area": "skills", "status": "пауза",
                 "задач": 2, "ok": 1, "кто": "Тест", "commits": []})
        сверить("журнал: ветка и дата", (z["branch"], z["date"]), ("main", date.today().isoformat()))

        # закрыть
        код, текст = закрыть(repo, "рабочий")
        сверить("закрыть неготовый", (код, текст), (2, "не закрыто:\n○ два"))
        сверить("неготовый остался", (repo / "vault" / "круги" / "рабочий.md").exists(), True)
        сверить("передача осталась", пер.exists(), True)
        файл_круга("рабочий", "E01-S02", ["раз", "два · после «раз»"], ["раз", "два"])
        сверить("закрыть готовый", закрыть(repo, "рабочий")[0], 0)
        сверить("круг в архиве", (repo / "vault" / "круги" / "архив" / "рабочий.md").exists(), True)
        сверить("круга на старом месте нет", (repo / "vault" / "круги" / "рабочий.md").exists(), False)
        сверить("передача удалена", пер.exists(), False)

        # вливание: main, пауза, закрыт, да
        сверить("вливание на main", вливание(repo, "без этапа", False), (0, "main\nостался: main"))
        бр = Path(__file__).resolve().parent / "ветка_задачи.py"
        subprocess.run([sys.executable, str(бр), "--repo", str(repo), "завести", "проба вливания"],
                       capture_output=True, text=True, encoding="utf-8")
        файл_круга("пауза", "E01-S02", ["раз", "два"], ["раз"])
        файл_круга("готов", "E01-S02", ["раз"], ["раз"])
        для_ветки = subprocess.run(["git", "branch", "--show-current"], cwd=repo,
                                   capture_output=True, text=True).stdout.strip()
        сверить("вливание: мы на ветке задачи", для_ветки != "main", True)
        к, т = вливание(repo, "пауза", True)
        сверить("вливание пауза даже с --да", (к, т.splitlines()[0]), (0, "пауза"))
        сверить("вливание пауза: остался", т.splitlines()[-1], f"остался: ветка {для_ветки}")
        к, т = вливание(repo, "готов", False)
        сверить("вливание закрыт: вопрос", (к, т.splitlines()[:2]), (0, ["вопрос", "влить в main?"]))
        (repo / "новое.txt").write_text("х", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "работа"], cwd=repo, capture_output=True)
        к, т = вливание(repo, "готов", True)
        сверить("вливание закрыт: да", (к, т.splitlines()[0], т.splitlines()[-1]), (0, "влито", "остался: main"))
        сверить("вливание: ветки нет", subprocess.run(["git", "branch", "--list", для_ветки], cwd=repo,
                capture_output=True, text=True).stdout.strip(), "")
        сверить("вливание: файл в main", (repo / "новое.txt").exists(), True)

        # вызов из командной строки
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--repo", str(repo), "--чеклист", "рабочий"],
                           capture_output=True, text=True, encoding="utf-8")
        сверить("cli: код и последняя строка", (r.returncode, r.stdout.strip().splitlines()[-1]), (0, "круг закрыт"))
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--repo", str(repo)],
                           capture_output=True, text=True, encoding="utf-8")
        сверить("cli: без команды", r.returncode, 1)
    print("самопроверка: " + ("не ок" if bad else "ок"))
    return 1 if bad else 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--самопроверка", action="store_true")
    ap.add_argument("--чеклист", metavar="КРУГ")
    ap.add_argument("--передача", metavar="КРУГ")
    ap.add_argument("--из", dest="из", metavar="ЧЕРНОВИК.md")
    ap.add_argument("--закрыть", metavar="КРУГ")
    ap.add_argument("--журнал", metavar="КРУГ")
    ap.add_argument("--вливание", metavar="КРУГ")
    ap.add_argument("--да", action="store_true")
    ap.add_argument("--статус", choices=["закрыт", "пауза"])
    try:
        args = ap.parse_args()
    except SystemExit as e:
        return 1 if e.code else 0
    if args.самопроверка:
        return самопроверка()
    repo = Path(args.repo).resolve()
    команды = [x for x in (args.чеклист, args.передача, args.закрыть, args.журнал, args.вливание) if x]
    if len(команды) != 1:
        print("нужна ровно одна команда: --чеклист | --передача --из | --закрыть | --журнал --статус | --вливание")
        return 1
    if args.передача and not args.из:
        print("--передача требует --из <черновик.md>")
        return 1
    if args.журнал and not args.статус:
        print("--журнал требует --статус закрыт|пауза")
        return 1
    if not (repo / ".claude" / "plan" / "roadmap.md").exists():
        print("нет .claude/plan/roadmap.md — запусти /plexus:init")
        return 1
    if args.чеклист:
        код, текст = чеклист(repo, args.чеклист)
    elif args.передача:
        код, текст = передача(repo, args.передача, Path(args.из))
    elif args.закрыть:
        код, текст = закрыть(repo, args.закрыть)
    elif args.вливание:
        код, текст = вливание(repo, args.вливание, args.да)
    else:
        код, текст = журнал(repo, args.журнал, args.статус)
    print(текст)
    return код


if __name__ == "__main__":
    sys.exit(main())
