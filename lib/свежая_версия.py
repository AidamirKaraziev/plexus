#!/usr/bin/env python3
"""Подсказка о новой версии Плексуса при старте сессии.

Канал релиз (маркетплейс plexus): сверяет с последним тегом vX.Y.Z.
Канал beta (маркетплейс plexus-beta): сверяет с версией в plugin.json ветки beta.
Новее — одна строка; равны, ошибка или сети нет — молчит. Не дольше 3 с.

Переменные: PLEXUS_INSTALLED, PLEXUS_CHANNEL (beta|release), PLEXUS_REPO (владелец/имя, переопределение).
Адрес и ветка берутся из подписки: имя маркетплейса — из пути ${CLAUDE_PLUGIN_ROOT}
(plugins/cache/<имя>/…), источник — $CLAUDE_CONFIG_DIR/plugins/known_marketplaces.json.
Флаг --hook: вывести JSON для SessionStart (systemMessage — видно человеку).
"""
import json, os, re, subprocess, sys, time, urllib.request

ЛИМИТ = 3.0
РАЗБОР = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?$")


def ключ(версия):
    m = РАЗБОР.match(версия.strip())
    if not m:
        return None
    x, y, z, b = m.groups()
    # релиз новее беты того же X.Y.Z
    return (int(x), int(y), int(z), 1, 0) if b is None else (int(x), int(y), int(z), 0, int(b))


def корень():
    return os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def установленная():
    if os.environ.get("PLEXUS_INSTALLED"):
        return os.environ["PLEXUS_INSTALLED"]
    with open(os.path.join(корень(), ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
        return json.load(f)["version"]


def канал():
    if os.environ.get("PLEXUS_CHANNEL"):
        return os.environ["PLEXUS_CHANNEL"]
    try:
        with open(os.path.join(корень(), ".claude-plugin", "marketplace.json"), encoding="utf-8") as f:
            имя = json.load(f).get("name", "")
        return "beta" if имя.endswith("beta") else "release"
    except Exception:
        return "release"


def источник():
    """(владелец/имя, ветка или None) из подписки своего маркетплейса; нет — None."""
    if os.environ.get("PLEXUS_REPO"):
        return os.environ["PLEXUS_REPO"], None
    части = os.path.abspath(корень()).split(os.sep)
    имя = части[части.index("cache") + 1]
    конфиг = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    with open(os.path.join(конфиг, "plugins", "known_marketplaces.json"), encoding="utf-8") as f:
        ист = json.load(f)[имя]["source"]
    if ист.get("source") == "github":
        репо = ист["repo"]
    else:
        m = re.match(r"^(?:https://|git@)github\.com[/:]([^/]+/[^/]+?)(?:\.git)?/?$", ист["url"])
        if not m:
            return None
        репо = m.group(1)
    return репо, ист.get("ref")


def последний_релиз(репо, срок):
    вывод = subprocess.run(
        ["git", "ls-remote", "--tags", f"https://github.com/{репо}.git", "v*"],
        capture_output=True, text=True, timeout=срок,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    ).stdout
    лучший = None
    for строка in вывод.splitlines():
        тег = строка.split("refs/tags/")[-1].removesuffix("^{}")
        if re.fullmatch(r"v\d+\.\d+\.\d+", тег) and (лучший is None or ключ(тег) > ключ(лучший)):
            лучший = тег
    return лучший.lstrip("v") if лучший else None


def версия_беты(репо, ветка, срок):
    url = f"https://raw.githubusercontent.com/{репо}/{ветка or 'beta'}/.claude-plugin/plugin.json"
    with urllib.request.urlopen(url, timeout=срок) as r:
        return json.load(r)["version"]


def подсказка():
    начало = time.monotonic()
    найдено = источник()
    if not найдено:
        return ""
    репо, ветка = найдено
    стоит = установленная()
    if ключ(стоит) is None:
        return ""
    срок = max(0.5, ЛИМИТ - 0.3 - (time.monotonic() - начало))
    if канал() == "beta":
        новая, что = версия_беты(репо, ветка, срок), "бета"
    else:
        новая, что = последний_релиз(репо, срок), "релиз"
    if новая and ключ(новая) and ключ(новая) > ключ(стоит):
        return f"Плексус: есть {что} {новая} (стоит {стоит}) — /plexus:update"
    return ""


def main():
    try:
        текст = подсказка()
    except Exception:
        текст = ""
    if "--hook" in sys.argv:
        if текст:
            print(json.dumps({"systemMessage": текст}, ensure_ascii=False))
    elif текст:
        print(текст)


if __name__ == "__main__":
    main()
