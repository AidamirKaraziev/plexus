# Плексус

Плагин для Claude Code: человек утверждает задание, менеджер раздаёт задачи работникам, отчёты сходятся обратно. Плюс база знаний проекта и план работ.

## Поставить

В сессии Claude Code одной строкой:

```
/plugin marketplace add AidamirKaraziev/plexus
```

затем `/plugin install plexus@plexus`. Вход в работу — `/plexus:start`, шпаргалка — `/plexus:aid`.

## Подключить в проект

Запись в `.claude/settings.json` репозитория (готовый файл — `templates/settings.json`) плагин **не скачивает**: `enabledPlugins` только включает его для тех, у кого он уже стоит. Каждый участник ставит Плексус один раз сам, из папки проекта:

```
claude plugin marketplace add AidamirKaraziev/plexus
claude plugin install plexus@plexus --scope project
```

Поставьте одну область, иначе в `claude plugin list` будет две записи (user и project), и обновлять придётся каждую. Для команды — `--scope project`.

Запись в проекте нужна, чтобы плагин был включён у всех и работал `autoUpdate`:

```json
{
  "extraKnownMarketplaces": {
    "plexus": {
      "source": { "source": "github", "repo": "AidamirKaraziev/plexus" },
      "autoUpdate": true
    }
  },
  "enabledPlugins": { "plexus@plexus": true }
}
```

Закоммитьте файл. Команда `claude plugin` этот файл не читает: сама она плагин по записи не поставит.

## Как приходят обновления

`autoUpdate: true` обновляет только уже **установленный** плагин, только в интерактивной сессии (после первого сообщения, с задержкой до 10 минут). Сессия остаётся на старой версии: появится подсказка `Plugin updated`, новая версия — после `/reload-plugins` или перезапуска. `claude -p` и команды `claude plugin` фоновое обновление не запускают.

Нужна версия сейчас — руками:

```
claude plugin marketplace update plexus
claude plugin update plexus@plexus --scope project
```

Первая команда обновляет только список, вторая — плагин. Если «already at the latest version» — новой версии ещё не выпущено: новые коммиты без поднятого `version` обновлением не считаются. Изменения — в `CHANGELOG.md`.

## Лицензия

MIT, см. `LICENSE`.
