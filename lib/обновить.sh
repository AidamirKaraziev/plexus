#!/usr/bin/env bash
# Обновляет маркетплейсы Плексуса (plexus, plexus-beta — какие стоят) и плагин
# в каждой области (user, project). Печатает одну итоговую строку.
# Имена переменных латиницей: кириллица в bash-переменных не работает.
set -u

# Строки "<id>|<область>|<версия>|<projectPath>" для установленного Плексуса
state() {
  claude plugin list --json 2>/dev/null | python3 -c '
import json,sys
for p in json.load(sys.stdin):
    i=p.get("id","")
    if i.split("@")[0]=="plexus":
        print("|".join([i,p.get("scope",""),p.get("version",""),p.get("projectPath","")]))
'
}

markets() {
  claude plugin marketplace list --json 2>/dev/null | python3 -c '
import json,sys
for m in json.load(sys.stdin):
    if m["name"] in ("plexus","plexus-beta"):
        print(m["name"])
'
}

before=$(state)
if [ -z "$before" ]; then
  echo "Плексус не установлен в этом профиле: claude plugin install plexus@plexus" >&2
  exit 1
fi

for m in $(markets); do
  claude plugin marketplace update "$m" >/dev/null 2>&1 || echo "не обновился маркетплейс $m" >&2
done

while IFS='|' read -r pid scope ver ppath; do
  [ -z "$pid" ] && continue
  if [ "$scope" = "project" ] && [ -d "$ppath" ]; then
    (cd "$ppath" && claude plugin update "$pid" --scope project >/dev/null 2>&1) || echo "не обновился $pid ($scope)" >&2
  else
    claude plugin update "$pid" --scope "$scope" >/dev/null 2>&1 || echo "не обновился $pid ($scope)" >&2
  fi
done <<< "$before"

after=$(state)
old=$(echo "$before" | cut -d'|' -f3 | sort -V | head -1)
new=$(echo "$after" | cut -d'|' -f3 | sort -V | tail -1)
if [ "$old" != "$new" ]; then
  echo "Плексус $old → $new, перезапусти Claude"
else
  echo "уже последняя $new"
fi
