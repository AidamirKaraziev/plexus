#!/usr/bin/env python3
"""Дописать хеш коммита в последнюю строку ledger.jsonl, где commits пуст.

Запускается git-хуком post-commit. Токенов не тратит, пользователь не замечает.

    python3 ${CLAUDE_PLUGIN_ROOT}/lib/ledger_commit.py <короткий-хеш> [--repo .]
"""
import json
import sys
from pathlib import Path

def main() -> int:
    if len(sys.argv) < 2:
        return 0
    h = sys.argv[1]
    repo = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else Path.cwd()
    path = repo / ".claude" / "ledger.jsonl"
    if not path.exists():
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    for i in range(len(lines) - 1, -1, -1):
        if not lines[i].strip():
            continue
        try:
            row = json.loads(lines[i])
        except json.JSONDecodeError:
            return 0
        if row.get("commits"):          # последний этап уже связан с коммитом
            return 0
        row.setdefault("commits", []).append(h)
        lines[i] = json.dumps(row, ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 0
    return 0

if __name__ == "__main__":
    sys.exit(main())
