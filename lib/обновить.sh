#!/usr/bin/env bash
# Обновляет маркетплейсы Плексуса (plexus, plexus-beta — какие стоят) и плагин
# в каждой области (user, project). Печатает одну итоговую строку.
# Имена переменных латиницей: кириллица в bash-переменных не работает.
set -u

# Разбор claude plugin list --json (stdin).
#   rows — установки Плексуса, которые можно обновить: "<id>|<область>|<версия>|<projectPath>";
#          записи с несуществующим projectPath пропускаются молча.
#   eff  — версия, действующая в текущей папке: user + local/project этой папки
#          (папка внутри projectPath); из них включённые, если такие есть.
#          Версии сравниваются по semver: X.Y.Z-beta.N < X.Y.Z.
parse() {
  python3 -c '
import json,sys,os
mode=sys.argv[1]; cwd=os.getcwd()
def key(v):
    core,_,pre=v.partition("-")
    c=tuple(int(x) if x.isdigit() else 0 for x in core.split("."))
    pr=(1,) if not pre else (0,)+tuple((0,int(x),"") if x.isdigit() else (1,0,x) for x in pre.split("."))
    return (c,pr)
items=[p for p in json.load(sys.stdin) if p.get("id","").split("@")[0]=="plexus"]
if mode=="rows":
    for p in items:
        pp=p.get("projectPath","")
        if p.get("scope")!="user" and not os.path.isdir(pp): continue
        print("|".join([p["id"],p.get("scope",""),p.get("version",""),pp]))
else:
    ap=[p for p in items if p.get("scope")=="user" or (p.get("projectPath") and (cwd==p["projectPath"] or cwd.startswith(p["projectPath"].rstrip("/")+"/")))]
    en=[p for p in ap if p.get("enabled")]
    ap=en or ap
    if ap: print(max((p.get("version","") for p in ap), key=key))
' "$1"
}

plist() { claude plugin list --json 2>/dev/null; }

markets() {
  claude plugin marketplace list --json 2>/dev/null | python3 -c '
import json,sys
for m in json.load(sys.stdin):
    if m["name"] in ("plexus","plexus-beta"):
        print(m["name"])
'
}

before=$(plist | parse rows)
old=$(plist | parse eff)
if [ -z "$before" ]; then
  echo "Плексус не установлен в этом профиле: claude plugin install plexus@plexus" >&2
  exit 1
fi

for m in $(markets); do
  claude plugin marketplace update "$m" >/dev/null 2>&1 || echo "не обновился маркетплейс $m" >&2
done

while IFS='|' read -r pid scope ver ppath; do
  [ -z "$pid" ] && continue
  if [ "$scope" != "user" ]; then
    (cd "$ppath" && claude plugin update "$pid" --scope "$scope" >/dev/null 2>&1) || echo "не обновился $pid ($scope)" >&2
  else
    claude plugin update "$pid" --scope "$scope" >/dev/null 2>&1 || echo "не обновился $pid ($scope)" >&2
  fi
done <<< "$before"

new=$(plist | parse eff)
if [ "$old" != "$new" ]; then
  echo "Плексус $old → $new, перезапусти Claude"
else
  echo "уже последняя $new"
fi
