#!/usr/bin/env python3
"""Замер capability ЯЗЫК: уточнения, переделки и токены на круг за окно дат.

Круг — сессия, где человек вызвал /plexus:task или /plexus:start.
Печатает только числа, текст реплик не выводит никогда.

    python3 lib/замер_языка.py --с 2026-09-30 --по 2026-11-22 [--json]
    python3 lib/замер_языка.py --самопроверка
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import аналитика as ан  # noqa: E402

КОМАНДЫ_КРУГА = {"plexus:task", "plexus:start"}
ТИПЫ_ПЕРЕДЕЛКИ = {"возражение", "правка-вслед"}


def читать_записи(файл: Path) -> list[tuple[int, dict]]:
    записи = []
    with файл.open(encoding="utf-8") as f:
        for i, строка in enumerate(f):
            строка = строка.strip()
            if not строка:
                continue
            try:
                з = json.loads(строка)
            except json.JSONDecodeError:
                continue
            if isinstance(з, dict):
                записи.append((i, з))
    return записи


def токены_записей(записи: list[tuple[int, dict]], видели: set) -> tuple[int, int]:
    """(input+output+cache_creation, cache_read) по записям ассистента.
    usage считается один раз на message.id (видели — общий набор сессии);
    записи без message.id считаются каждая отдельно."""
    сумма = чтение = 0
    for _, з in записи:
        if з.get("type") != "assistant":
            continue
        сообщение = з.get("message") or {}
        mid = сообщение.get("id")
        if mid:
            if mid in видели:
                continue
            видели.add(mid)
        u = сообщение.get("usage") or {}
        сумма += sum(int(u.get(k) or 0) for k in
                     ("input_tokens", "output_tokens", "cache_creation_input_tokens"))
        чтение += int(u.get("cache_read_input_tokens") or 0)
    return сумма, чтение


def вопрос_ии(з: dict) -> bool:
    if з.get("type") != "assistant":
        return False
    if any(б.get("name") == "AskUserQuestion" for б in ан.вызовы_инструментов(з)):
        return True
    return ан.текст_реплики(з).rstrip().endswith("?")


def число_уточнений(записи: list[tuple[int, dict]]) -> int:
    """Ответы человека, идущие сразу за вопросом ИИ (каждый ответ считается раз)."""
    отвеченные = set()
    for idx, (_, з) in enumerate(записи):
        if not вопрос_ии(з):
            continue
        for j in range(idx + 1, len(записи)):
            if ан.реплика_человека(записи[j][1]):
                отвеченные.add(j)
                break
    return len(отвеченные)


def число_переделок(записи: list[tuple[int, dict]]) -> int:
    сигналы = ан.разобрать_сессию(записи, "", "", True)
    return len({с["смещение"] for с in сигналы if с["тип"] in ТИПЫ_ПЕРЕДЕЛКИ})


def круг_ли(записи: list[tuple[int, dict]]) -> bool:
    for _, з in записи:
        if ан.реплика_человека(з):
            имена = {и.lstrip("/") for и in ан.скиллы_в_реплике(ан.текст_реплики(з))}
            if имена & КОМАНДЫ_КРУГА:
                return True
    return False


def в_окне(записи, с: str, по: str) -> bool:
    for _, з in записи:
        ts = з.get("timestamp")
        if isinstance(ts, str) and ts:
            return с <= ts[:10] <= по
    return False


def замерить(корень: Path, с: str, по: str) -> list[dict]:
    сессии = []
    if not корень.exists():
        return сессии
    for файл in sorted(корень.glob("*/*.jsonl")):
        записи = читать_записи(файл)
        if not круг_ли(записи) or not в_окне(записи, с, по):
            continue
        видели: set = set()
        токены, чтение = токены_записей(записи, видели)
        for суб in sorted((файл.parent / файл.stem / "subagents").glob("*.jsonl")):
            т, ч = токены_записей(читать_записи(суб), видели)
            токены += т
            чтение += ч
        сессии.append({
            "id": файл.stem, "проект": файл.parent.name,
            "уточнений": число_уточнений(записи),
            "переделок": число_переделок(записи),
            "токенов": токены, "чтение_кэша": чтение,
        })
    return сессии


def итог(сессии: list[dict]) -> dict:
    n = len(сессии)
    def на_круг(ключ):
        return sum(с[ключ] for с in сессии) / n if n else 0.0
    return {
        "кругов": n,
        "уточнений_на_круг": round(на_круг("уточнений"), 2),
        "переделок_на_круг": round(на_круг("переделок"), 2),
        "токенов_на_круг": int(на_круг("токенов")),
        "чтение_кэша_на_круг": int(на_круг("чтение_кэша")),
    }


def строка_итога(и: dict) -> str:
    return (f"кругов: {и['кругов']}; уточнений на круг: {и['уточнений_на_круг']:.2f}; "
            f"переделок на круг: {и['переделок_на_круг']:.2f}; "
            f"токенов на круг: {и['токенов_на_круг']} (чтение кэша: {и['чтение_кэша_на_круг']})")


# ---------- самопроверка ----------

def _ас(текст=None, блоки=None, токены=(0, 0, 0, 0), ts="2026-10-01T10:00:00Z", id_=None) -> dict:
    содержимое = блоки if блоки is not None else [{"type": "text", "text": текст}]
    i, o, cc, cr = токены
    return {"type": "assistant", "timestamp": ts, "message": {
        **({"id": id_} if id_ else {}),
        "role": "assistant", "content": содержимое,
        "usage": {"input_tokens": i, "output_tokens": o,
                  "cache_creation_input_tokens": cc, "cache_read_input_tokens": cr}}}


def _чел(текст, ts="2026-10-01T10:00:00Z") -> dict:
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": текст}}


def _писать(путь: Path, записи: list[dict]) -> None:
    путь.parent.mkdir(parents=True, exist_ok=True)
    with путь.open("w", encoding="utf-8") as f:
        for з in записи:
            f.write(json.dumps(з, ensure_ascii=False) + "\n")


def самопроверка() -> int:
    беды = []
    with tempfile.TemporaryDirectory() as t:
        корень = Path(t)
        # круг А: 2 уточнения (текст «?» и AskUserQuestion), 1 переделка, токены 15+27+41+67, кэш 5
        _писать(корень / "proj" / "a.jsonl", [
            _чел("<command-name>/plexus:task</command-name>"),
            _ас("Что делаем?", токены=(10, 2, 3, 5)),
            _чел("делаем замер"),
            _ас(блоки=[{"type": "tool_use", "id": "q", "name": "AskUserQuestion", "input": {}}],
                токены=(20, 3, 4, 0)),
            {"type": "user", "timestamp": "2026-10-01T10:00:00Z", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "q", "content": "ок"}]}},
            _чел("не то, переделай"),
            _ас("Готово.", токены=(30, 5, 6, 0)),
        ])
        _писать(корень / "proj" / "a" / "subagents" / "s1.jsonl", [
            _ас("работа", токены=(40, 10, 17, 7)),
        ])
        # круг Б: без вопросов и возражений, токены 1+1+1 (две записи с одним message.id считаются раз)
        _писать(корень / "proj" / "b.jsonl", [
            _чел("<command-name>/plexus:start</command-name>", ts="2026-11-01T09:00:00Z"),
            _ас("Ок.", токены=(1, 1, 1, 0), ts="2026-11-01T09:00:00Z", id_="m1"),
            _ас(блоки=[{"type": "tool_use", "id": "t", "name": "Read", "input": {}}],
                токены=(1, 1, 1, 0), ts="2026-11-01T09:00:00Z", id_="m1"),
        ])
        # не круг и вне окна: не должны попасть
        _писать(корень / "proj" / "c.jsonl", [_чел("привет"), _ас("Привет?")])
        _писать(корень / "proj" / "d.jsonl", [
            _чел("<command-name>/plexus:task</command-name>", ts="2026-08-01T09:00:00Z")])

        сессии = замерить(корень, "2026-09-30", "2026-11-22")
        по_id = {с["id"]: с for с in сессии}
        if set(по_id) != {"a", "b"}:
            беды.append(f"состав кругов: {sorted(по_id)}, ждали ['a', 'b']")
        else:
            a, b = по_id["a"], по_id["b"]
            if (a["уточнений"], a["переделок"]) != (2, 1):
                беды.append(f"круг a: уточнений/переделок {a['уточнений']}/{a['переделок']}, ждали 2/1")
            if a["токенов"] != 150 or a["чтение_кэша"] != 12:
                беды.append(f"круг a: токены {a['токенов']} (кэш {a['чтение_кэша']}), ждали 150 (12)")
            if (b["уточнений"], b["переделок"], b["токенов"]) != (0, 0, 3):
                беды.append(f"круг b: {b['уточнений']}/{b['переделок']}/{b['токенов']}, ждали 0/0/3")
        и = итог(сессии)
        ждали = ("кругов: 2; уточнений на круг: 1.00; переделок на круг: 0.50; "
                 "токенов на круг: 76 (чтение кэша: 6)")
        if строка_итога(и) != ждали:
            беды.append(f"строка итога: {строка_итога(и)!r}, ждали {ждали!r}")
    if беды:
        for б in беды:
            print(f"✗ {б}")
        print(f"самопроверка: {len(беды)} случаев не сошлись")
        return 1
    print("ок")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--с", dest="с", help="первая дата окна YYYY-MM-DD")
    ap.add_argument("--по", dest="по", help="последняя дата окна YYYY-MM-DD")
    ap.add_argument("--транскрипты", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--самопроверка", action="store_true")
    a = ap.parse_args()
    if a.самопроверка:
        return самопроверка()
    if not (a.с and a.по):
        ap.error("нужны --с и --по (или --самопроверка)")
    корень = a.транскрипты or ан.путь_транскриптов_по_умолчанию()
    сессии = замерить(корень, a.с, a.по)
    и = итог(сессии)
    if a.json:
        print(json.dumps({**и, "сессии": сессии}, ensure_ascii=False, indent=2))
    else:
        print(строка_итога(и))
    return 0


if __name__ == "__main__":
    sys.exit(main())
