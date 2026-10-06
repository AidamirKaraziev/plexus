#!/usr/bin/env python3
"""Хук SessionStart: в Codex сообщает модели корень плагина.

Codex не раскрывает ${CLAUDE_PLUGIN_ROOT} в тексте SKILL.md, а для команды хука задаёт
PLUGIN_ROOT (в Claude Code этой переменной нет). Поэтому: PLUGIN_ROOT есть — это Codex,
печатаем additionalContext со строкой «корень Плексуса: <путь>»; нет — молчим, как в Claude.
"""
import json
import os

root = os.environ.get("PLUGIN_ROOT")
if root:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": f"корень Плексуса: {root}",
    }}, ensure_ascii=False))
