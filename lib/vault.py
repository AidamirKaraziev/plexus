#!/usr/bin/env python3
"""Сторож базы знаний.

Отдаёт скиллу путь к vault текущего проекта и карту его папок — либо
отказывает. Смысл: модель не рассуждает о том, куда писать, и не может
записать в базу чужого проекта. Один сторож на входе вместо проверки
в каждом скилле.

    python3 lib/vault.py           путь, проект и карта папок
    python3 lib/vault.py --path    только путь
    python3 lib/vault.py --check   только проверка, одна строка

Код возврата 1 — писать нельзя, причина в stderr.
"""

import os
import re
import subprocess
import sys

INDEX = "проект.md"
MAP = "карта.md"
SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}
MAX_DEPTH = 3

LINE = re.compile(r"^\s*[-*]\s+`?([^`—]+?)`?\s*—\s*(.+?)\s*$")


def fail(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def repo_root():
    """Корень репозитория. Выше него сторож не смотрит никогда."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return os.getcwd()


def project_name(root):
    """Имя проекта — по main-checkout'у: первая строка `git worktree list`.
    Из дорожки .claude/worktrees/E0N иначе получилось бы «E0N»."""
    try:
        out = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=root, capture_output=True, text=True, timeout=5,
        )
        first = out.stdout.splitlines()[0] if out.returncode == 0 and out.stdout else ""
        if first.startswith("worktree "):
            return os.path.basename(first[len("worktree "):])
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.basename(root)


def frontmatter(path):
    """Пары ключ: значение из первого блока --- ... ---."""
    data = {}
    try:
        with open(path, encoding="utf-8") as f:
            if f.readline().strip() != "---":
                return data
            for line in f:
                if line.strip() == "---":
                    break
                if ":" in line:
                    k, v = line.split(":", 1)
                    data[k.strip()] = v.strip()
    except OSError:
        pass
    return data


def find_vaults(root):
    """Все базы знаний внутри репо. Наружу не выходим — ни ~, ни ../"""
    found = []
    for cur, dirs, _ in os.walk(root):
        depth = cur[len(root):].count(os.sep)
        if depth >= MAX_DEPTH:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
        if all(os.path.isfile(os.path.join(cur, f)) for f in (INDEX, MAP)):
            found.append(cur)
            dirs[:] = []
    return found


def read_map(vault):
    """Карта папок из контракта: [(папка, что туда класть)]."""
    path = os.path.join(vault, MAP)
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = LINE.match(line)
            if m:
                rows.append((m.group(1).strip().rstrip("/"), m.group(2)))
    if not rows:
        fail(f"{MAP} есть, но ни одной папки в нём не описано")
    return rows


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    root = repo_root()

    vaults = find_vaults(root)
    if not vaults:
        fail("нет базы знаний в этом репозитории — запусти /aid-project-init")
    if len(vaults) > 1:
        names = ", ".join(os.path.relpath(v, root) for v in vaults)
        fail(f"нашлось несколько баз ({names}) — спроси человека, в какую писать")
    vault = vaults[0]

    project = project_name(root)
    declared = frontmatter(os.path.join(vault, INDEX)).get("проект", "")
    if declared and declared != project:
        fail(
            f"база принадлежит проекту «{declared}», а мы в «{project}» — не пишу.\n"
            f"переименовали репозиторий — поправь «проект:» в {INDEX}"
        )

    rel = os.path.relpath(vault, os.getcwd())
    if mode == "--path":
        print(rel)
        return

    rows = read_map(vault)
    missing = [d for d, _ in rows if not os.path.isdir(os.path.join(vault, d))]
    if missing:
        fail(
            "карта расходится с реальностью, нет папок: " + ", ".join(missing)
            + "\nсоздай их или убери из карты"
        )

    known = {d for d, _ in rows}
    extra = sorted(
        d for d in os.listdir(vault)
        if os.path.isdir(os.path.join(vault, d)) and d not in known
        and not d.startswith(".")
    )

    if mode == "--check":
        print(f"ок · {rel} · проект {project} · папок {len(rows)}")
        return

    print(f"vault: {rel}")
    print(f"проект: {project}")
    print("папки:")
    for d, what in rows:
        n = len([f for f in os.listdir(os.path.join(vault, d)) if f.endswith(".md")])
        print(f"  {d}/ ({n}) — {what}")
    if extra:
        print("вне карты: " + ", ".join(extra))


if __name__ == "__main__":
    main()
