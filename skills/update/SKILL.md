---
name: update
description: Update Plexus to the latest version — both marketplaces (plexus, plexus-beta) that are installed and the plugin in every scope. Use when the user invokes /plexus:update, or says «обнови Плексус», «есть новая версия», "update plexus".
version: 1.0.0
---

# Update Plexus

Run exactly one command and print its last line as the answer:

```
bash ${CLAUDE_PLUGIN_ROOT}/lib/обновить.sh
```

Nothing else: no other files, no advice, no offers. If the script exits with a
non-zero code, show its message as is.
