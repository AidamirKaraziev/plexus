#!/bin/bash
# Проверка доставки Плексуса в три хоста: Claude Code, Codex, DeepSeek Harness (DSH).
# Всё во временных профилях; реальные ~/.claude и ~/.codex не меняются (сверка в конце).
#   bash проверить-доставку.sh            — проверка; нет CLI хоста → ПРОПУСК и проверка по упаковке
#   bash проверить-доставку.sh --строго   — ПРОПУСК считается провалом (для CI)
# Корень репозитория можно подменить: PLEXUS_ROOT=<копия> bash проверить-доставку.sh
# Сеть нужна только npm install / pnpm зависимостей пакета DSH. dsh ищется: DSH_BIN, PATH, DeepSeek Harness.app.
# Выход: 0 — нет провалов; 1 — есть провал; 2 — скрипт не смог начать.
ROOT="${PLEXUS_ROOT:-$(cd "$(dirname "$0")" && pwd -P)}" || exit 2
ROOT="$(cd "$ROOT" && pwd -P)" || exit 2
STRICT=0; [ "$1" = "--строго" ] && STRICT=1
command -v node >/dev/null && command -v npm >/dev/null && command -v python3 >/dev/null || { echo "✘ нужны node, npm, python3"; exit 2; }

TMP="$(mktemp -d)" || exit 2
[ -n "$TMP" ] && [ -d "$TMP" ] || exit 2
trap 'rm -rf "$TMP"' EXIT

# --- что должно быть по исходнику
SKILLS=(); for d in "$ROOT"/skills/*/; do [ -f "$d/SKILL.md" ] && SKILLS+=("$(basename "$d")"); done
AGENTS=(); for f in "$ROOT"/agents/*.md; do AGENTS+=("$(basename "$f" .md)"); done
NS=${#SKILLS[@]}; NA=${#AGENTS[@]}
[ "$NS" -eq 14 ] || echo "! в skills/ $NS скиллов, ожидалось 14"
AGLIST="${AGENTS[*]}"

# bash 3.2 (macOS) без ассоциативных массивов: RES_<хост>, WHY_<хост>
fail() { eval "RES_$1=провал"; eval "WHY_$1=\$2";  echo "✘ $1: $2"; }
okh()  { eval "RES_$1=ок"; eval "WHY_$1=\$2";  echo "✔ $1: $2"; }
skip() { eval "RES_$1=пропуск"; eval "WHY_$1=\$2";  echo "ПРОПУСК $1: $2"; }

# есть ли в каталоге $1 все скиллы и работники; печатает недостающее
missing() { # $1 — корень скиллов/агентов (кэш плагина или собранная упаковка)
  local m="" s a
  for s in "${SKILLS[@]}"; do [ -f "$1/skills/$s/SKILL.md" ] || m="$m skills/$s"; done
  [ "${2:-agents}" = noagents ] || for a in "${AGENTS[@]}"; do [ -f "$1/agents/$a.md" ] || m="$m agents/$a"; done
  echo "${m# }"
}
count_skills() { local n=0 d; for d in "$1"/skills/*/; do [ -f "$d/SKILL.md" ] && n=$((n+1)); done; echo $n; }

DSH_APP_BIN="/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh"
# --- отпечаток реальных профилей (до)
fp() {
  for f in "$HOME/.claude/plugins/installed_plugins.json" "$HOME/.claude/plugins/known_marketplaces.json" "$HOME/.codex/config.toml"; do
    [ -f "$f" ] && shasum "$f" || echo "нет $f"; done
  [ -d "$HOME/.dsh/profiles" ] && find "$HOME/.dsh/profiles" -maxdepth 2 \( -name package.json -o -name 'cordis*.yml' \) -exec shasum {} + 2>/dev/null | sort
  [ -d "$HOME/.dsh/profiles" ] && ls "$HOME/.dsh/profiles" | sort
  for d in "$HOME/.claude/plugins" "$HOME/.codex/plugins"; do
    [ -d "$d" ] && find "$d" -maxdepth 2 -exec stat -f '%N %m' {} + 2>/dev/null | sort || echo "нет $d"; done
}
DSH_BIN="${DSH_BIN:-$(command -v dsh)}"
[ -z "$DSH_BIN" ] && [ -x "$DSH_APP_BIN" ] && DSH_BIN="$DSH_APP_BIN"
[ -n "$DSH_BIN" ] && [ -x "$DSH_BIN" ] || DSH_BIN=""
LIVE_BEFORE="$(fp)"

# ================= Claude Code =================
if command -v claude >/dev/null; then
  CFG="$TMP/claude"; mkdir -p "$CFG"
  cc() { ( cd "$TMP" && CLAUDE_CONFIG_DIR="$CFG" claude "$@" 2>&1 ); }
  out=$(cc plugin marketplace add "$ROOT") || { fail claude "marketplace add: $(echo "$out" | tail -1)"; }
  if [ -z "$RES_claude" ]; then
    out=$(cc plugin install plexus@plexus) || fail claude "plugin install: $(echo "$out" | tail -1)"
  fi
  if [ -z "$RES_claude" ]; then
    CACHE=$(ls -d "$CFG"/plugins/cache/plexus/plexus/*/ 2>/dev/null | head -1)
    lst=$(cc plugin list)
    if [ -z "$CACHE" ]; then fail claude "плагина нет в кэше профиля"
    elif ! echo "$lst" | grep -q 'plexus@plexus' || ! echo "$lst" | grep -q 'enabled'; then fail claude "plugin list не показывает включённый plexus@plexus"
    else
      m=$(missing "$CACHE"); n=$(count_skills "$CACHE")
      if [ -n "$m" ]; then fail claude "в установленной копии нет: $m"
      elif [ "$n" -ne 14 ]; then fail claude "скиллов в установленной копии $n, нужно 14"
      else okh claude "14 скиллов, работники $AGLIST (установленный кэш, plugin list: включён)"; fi
    fi
  fi
else
  skip claude "нет CLI"
  m=$(missing "$ROOT")
  [ -z "$m" ] && echo "  по упаковке: 14 скиллов и работники на месте (не установка)" || fail claude "по упаковке нет: $m"
fi

# ================= Codex =================
if command -v codex >/dev/null; then
  export CODEX_HOME="$TMP/codex-home"; mkdir -p "$CODEX_HOME"
  out=$(codex plugin marketplace add "$ROOT" 2>&1) || fail codex "marketplace add: $(echo "$out" | tail -1)"
  [ -z "$RES_codex" ] && { out=$(codex plugin add plexus@plexus 2>&1) || fail codex "plugin add: $(echo "$out" | tail -1)"; }
  if [ -z "$RES_codex" ]; then
    CACHE=$(ls -d "$CODEX_HOME"/plugins/cache/plexus/plexus/*/ 2>/dev/null | head -1)
    if [ -z "$CACHE" ]; then fail codex "плагина нет в кэше Codex"
    else
      m=$(missing "$CACHE"); n=$(count_skills "$CACHE")
      if [ -n "$m" ]; then fail codex "в установленной копии нет: $m"
      elif [ "$n" -ne 14 ]; then fail codex "скиллов в установленной копии $n, нужно 14"
      else okh codex "14 скиллов, работники $AGLIST — файлами agents/*.md (отдельных агентов Codex плагин не заводит, §7 передаёт их текст субагенту)"; fi
    fi
  fi
  unset CODEX_HOME
else
  skip codex "нет CLI"
  m=$(missing "$ROOT")
  [ -z "$m" ] && echo "  по упаковке: 14 скиллов и agents/*.md на месте (не установка)" || fail codex "по упаковке нет: $m"
fi

# ================= DSH =================
PKG="$TMP/пакет"; mkdir -p "$PKG"
out=$(cd "$ROOT" && node доставка/собрать.mjs dsh 2>&1) || fail dsh "сборка пакета: $(echo "$out" | tail -1)"
if [ -z "$RES_dsh" ]; then
  # сборщик пишет в сборка/dsh/ корня; пакуем оттуда во временную папку
  out=$(cd "$ROOT/сборка/dsh" && npm pack --pack-destination "$PKG" --silent 2>&1) || fail dsh "npm pack: $(echo "$out" | tail -1)"
fi
if [ -z "$RES_dsh" ]; then
  TGZ=$(ls "$PKG"/*.tgz 2>/dev/null | head -1)
  INST="$TMP/dsh-установка"; mkdir -p "$INST"
  echo '{"name":"dsh-profile","private":true,"type":"module"}' > "$INST/package.json"
  out=$(cd "$INST" && npm install --no-audit --no-fund --silent "$TGZ" 2>&1) || fail dsh "npm install tarball: $(echo "$out" | tail -2 | tr '\n' ' ')"
fi
if [ -z "$RES_dsh" ]; then
  P="$INST/node_modules/@plexus-dsh/plexus"
  res=$(cd "$INST" && node --input-type=module - "$P" "${SKILLS[*]}" <<'JS' 2>&1
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
const [p, want] = [process.argv[2], process.argv[3].split(' ').map((s) => `plexus-${s}`).sort()]
const mod = await import(pathToFileURL(`${p}/index.js`).href)
let provider
const ctx = { skills: { registerProvider: (f) => { provider = f({ signal: new AbortController().signal }) } }, effect: () => {} }
mod.apply(ctx, {})
const { candidates } = await provider.list()
const got = candidates.map((c) => c.name).sort()
const bad = []
if (JSON.stringify(got) !== JSON.stringify(want)) bad.push(`команды: ${got.join(',')} ≠ ${want.join(',')}`)
for (const c of candidates) { const d = await provider.get(c); if (!d || !d.content) bad.push(`нет тела ${c.name}`) }
const yml = readFileSync(`${p}/cordis.patch.yml`, 'utf8')
const presets = ['plexus-programmer', 'plexus-analyst'].filter((n) => !new RegExp(`(^|[^\\w-])${n}([^\\w-]|$)`, 'm').test(yml))
if (presets.length) bad.push(`нет пресетов: ${presets.join(',')}`)
if (bad.length) { console.log('BAD ' + bad.join('; ')); process.exit(1) }
console.log(`OK ${got.length}`)
JS
  ) || fail dsh "провайдер из установленного пакета: ${res#BAD }"
  if [ -z "$RES_dsh" ]; then
    N=${res#OK }
    DETAIL="$N команд plexus-*, пресеты plexus-programmer, plexus-analyst (tarball установлен в временную папку, провайдер вызван)"
    if [ "$N" -ne 14 ]; then fail dsh "команд $N, нужно 14"
    elif [ -n "$DSH_BIN" ]; then
      # живая установка: профиль web (dsh-base + dsh-web-app: сервис пресетов agentPresets только там)
      export DSH_HOME="$TMP/dsh-home"; mkdir -p "$DSH_HOME"
      out=$("$DSH_BIN" --profile проба --from-default-profile web --dump-config 2>&1 >/dev/null) || fail dsh "создание профиля: $(echo "$out" | tail -1)"
      [ -z "$RES_dsh" ] && { out=$("$DSH_BIN" plugin --profile проба add "file:$TGZ" 2>&1) || fail dsh "dsh plugin add: $(echo "$out" | tail -2 | tr '\n' ' ')"; }
      if [ -z "$RES_dsh" ]; then
        dump=$("$DSH_BIN" --profile проба --dump-config 2>&1) || fail dsh "dsh --dump-config: $(echo "$dump" | tail -1)"
        for id in plexus-skills preset-plexus-programmer preset-plexus-analyst; do
          [ -z "$RES_dsh" ] && { echo "$dump" | grep -q "^- id: $id\$" || fail dsh "в составе профиля нет $id"; }
        done
      fi
      if [ -z "$RES_dsh" ]; then
        PP="$DSH_HOME/profiles/проба/node_modules/@plexus-dsh/plexus"
        [ -f "$PP/index.js" ] || fail dsh "пакета нет в node_modules профиля"
      fi
      if [ -z "$RES_dsh" ]; then
        res2=$(cd "$DSH_HOME/profiles/проба" && node --input-type=module - "$PP" "${SKILLS[*]}" <<'JS' 2>&1
import { pathToFileURL } from 'node:url'
const [p, want] = [process.argv[2], process.argv[3].split(' ').map((s) => `plexus-${s}`).sort()]
const mod = await import(pathToFileURL(`${p}/index.js`).href)
let provider
mod.apply({ skills: { registerProvider: (f) => { provider = f({ signal: new AbortController().signal }) } }, effect: () => {} }, {})
const got = (await provider.list()).candidates.map((c) => c.name).sort()
if (JSON.stringify(got) !== JSON.stringify(want)) { console.log('BAD ' + got.join(',')); process.exit(1) }
console.log('OK ' + got.length)
JS
        ) || fail dsh "провайдер из профиля: ${res2#BAD }"
        [ -z "$RES_dsh" ] && okh dsh "14 скиллов plexus-*, работники plexus-programmer, plexus-analyst (dsh plugin add во временный DSH_HOME, dsh $("$DSH_BIN" --version 2>&1 | head -1); --dump-config: plexus-skills и оба пресета)"
      fi
      unset DSH_HOME
    else
      skip dsh "нет CLI dsh (искал PATH и /Applications/DeepSeek Harness.app); упаковка проверена: $DETAIL"
    fi
  fi
fi

# ================= сверка реальных профилей и сводка =================
LIVE_AFTER="$(fp)"
if [ "$LIVE_BEFORE" = "$LIVE_AFTER" ]; then echo "✔ реальные ~/.claude/plugins, ~/.codex и ~/.dsh/profiles не изменены"
else echo "✘ реальные профили изменились:"; diff <(echo "$LIVE_BEFORE") <(echo "$LIVE_AFTER") | head -6; LIVE_BAD=1; fi

echo "--- сводка"
BAD=0
for h in claude codex dsh; do
  eval "r=\${RES_$h:-провал}"
  [ "$r" = пропуск ] && [ $STRICT -eq 1 ] && { r="провал (строго: пропуск)"; }
  case "$r" in провал*) BAD=1;; esac
  echo "$h: $r — $(eval "echo \"\${WHY_$h:-не проверен}\"")"
done
[ -n "$LIVE_BAD" ] && BAD=1
if [ $BAD -eq 0 ]; then echo "ИТОГ: зелёный"; exit 0; else echo "ИТОГ: красный"; exit 1; fi
