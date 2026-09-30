# Плексус

Плагин для Claude Code: человек утверждает задание, менеджер раздаёт задачи работникам, отчёты сходятся обратно. Плюс база знаний проекта и план работ.

## Поставить

В сессии Claude Code одной строкой:

```
/plugin marketplace add AidamirKaraziev/plexus
```

затем `/plugin install plexus@plexus`. Вход в работу — `/plexus:start`, шпаргалка — `/plexus:aid`.

## Подключить в проект

Чтобы у всей команды Плексус появлялся сам, положите в `.claude/settings.json` репозитория (готовый файл — `templates/settings.json`):

```json
{
  "extraKnownMarketplaces": {
    "plexus": {
      "source": { "source": "github", "repo": "AidamirKaraziev/plexus" },
      "autoUpdate": true
    }
  },
  "enabledPlugins": {
    "plexus@plexus": true
  }
}
```

Закоммитьте файл. При следующем запуске в этой папке Claude Code спросит доверие к папке, зарегистрирует маркетплейс и включит плагин.

## Как приходят обновления

С `autoUpdate: true` Claude Code сам подтягивает новую версию в фоне при запуске; новая версия подхватывается, когда в плагине меняется `version`.

Если автообновление не сработало (в документации поле описано для управляемых настроек, для проектных не подтверждено), обновитесь вручную:

```
/plugin marketplace update plexus
```

Либо включите **Enable auto-update** в `/plugin` → Marketplaces → plexus. Изменения смотрите в `CHANGELOG.md`.

## Лицензия

MIT, см. `LICENSE`.
