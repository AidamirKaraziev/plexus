// Проверка манифеста собранного пакета (сборка/dsh/): files, dsh.bundle.patch,
// валидные строки патча, пресеты работников. Гоняет `node доставка/собрать.mjs dsh --проверить`.
// Самодостаточна: YAML разбирается крошечным парсером ниже, внешних пакетов не нужно,
// поэтому проверка работает и в чистом профиле, и в чужом репозитории.
import { readFileSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert/strict'

const HERE = dirname(fileURLToPath(import.meta.url))

/**
 * Разобрать тот подвид YAML, который допустим в cordis.patch.yml: список операций,
 * у каждой — `insert`, в нём строки `id`/`name`/`config`; в `config` — вложенные
 * словари, списки и скаляры; `>-` склеивает строки в одну. Всё остальное — ошибка.
 */
function parseYaml(text) {
  const lines = text.split('\n')
  let at = 0
  const пока = () => ({ indent: lines[at].match(/^ */)[0].length, text: lines[at].trim() })
  const значимая = () => {
    while (at < lines.length) {
      const чистый = lines[at].trim()
      if (чистый && !чистый.startsWith('#')) return true
      at++
    }
    return false
  }
  const scalar = (raw) => {
    const s = raw.trim()
    if (s.startsWith('"') || s.startsWith("'")) {
      const quote = s[0]
      if (!s.endsWith(quote) || s.length < 2) throw new Error(`незакрытая кавычка: ${s}`)
      return s.slice(1, -1)
    }
    if (s === '[]') return []
    if (s === '') return null
    return s
  }
  // `>-`: забрать все более отступленные строки и склеить через пробел.
  // `|`: то же, но строки сохраняются как есть (отступ блока срезан).
  const блок = (parentIndent) => {
    const parts = []
    let отступБлока = null
    while (at < lines.length) {
      const line = lines[at]
      if (!line.trim()) { parts.push(''); at++; continue }
      const отступ = line.match(/^ */)[0].length
      if (отступ <= parentIndent) break
      отступБлока ??= отступ
      parts.push(line.slice(отступБлока))
      at++
    }
    while (parts.length && parts[parts.length - 1] === '') parts.pop()
    return parts.join('\n') + '\n'
  }
  const продолжение = (parentIndent) => {
    const parts = []
    while (at < lines.length) {
      const line = lines[at]
      if (!line.trim()) { at++; continue }
      const отступ = line.match(/^ */)[0].length
      if (отступ <= parentIndent) break
      parts.push(line.trim())
      at++
    }
    return parts.join(' ')
  }
  const значение = (rest, parentIndent) => {
    if (rest === '>-' || rest === '>') return продолжение(parentIndent)
    if (rest === '|' || rest === '|-') return блок(parentIndent)
    if (rest === '' && at < lines.length && /^\s*$/.test(lines[at])) {
      const отступ = lines[at].match(/^ */)[0].length
      return отступ > parentIndent ? продолжение(parentIndent) : null
    }
    return scalar(rest)
  }
  // Строка словаря: "ключ: значение" → [ключ, rest].
  const пара = (text, indent) => {
    const match = text.match(/^("[^"]+"|'[^']+'|[^:]+):(\s.*|)$/)
    if (!match) throw new Error(`не ключ: ${text}`)
    return [scalar(match[1]), match[2]]
  }
  const словарь = (indent) => {
    const out = {}
    while (значимая() && пока().indent === indent && !пока().text.startsWith('- ')) {
      const [key, rest] = пара(пока().text, indent)
      at++
      if (rest.trim() !== '') out[key] = значение(rest.trim(), indent)
      else if (значимая() && пока().indent > indent) {
        out[key] = пока().text.startsWith('- ') ? список(пока().indent) : словарь(пока().indent)
      } else out[key] = null
    }
    return out
  }
  const список = (indent) => {
    const out = []
    while (значимая() && пока().indent === indent && пока().text.startsWith('- ')) {
      const rest = пока().text.slice(2)
      const [key, tail] = пара(rest, indent + 2)
      at++
      const row = {}
      if (tail.trim() !== '') row[key] = значение(tail.trim(), indent + 2)
      else if (значимая() && пока().indent > indent + 2) {
        row[key] = пока().text.startsWith('- ') ? список(пока().indent) : словарь(пока().indent)
      } else row[key] = null
      while (значимая() && пока().indent === indent + 2 && !пока().text.startsWith('- ')) {
        const [k2, r2] = пара(пока().text, indent + 2)
        at++
        if (r2.trim() !== '') row[k2] = значение(r2.trim(), indent + 2)
        else if (значимая() && пока().indent > indent + 2) {
          row[k2] = пока().text.startsWith('- ') ? список(пока().indent) : словарь(пока().indent)
        } else row[k2] = null
      }
      out.push(row)
    }
    return out
  }
  if (!значимая()) return []
  const head = пока()
  const parsed = head.text.startsWith('- ') ? список(head.indent) : словарь(head.indent)
  if (значимая()) throw new Error(`не разобрана строка ${at + 1}: ${lines[at]}`)
  return parsed
}

/**
 * Поля плагина, объявленные в его Config без default: схема считает их
 * обязательными, и пресет с пропуском приходит в реестр сломанным.
 */
const REQUIRED_CONFIG = {
  '@deepseek-ai/dsh-tool-fs-search': { sampleOverCapGlobResults: false },
}

const pkg = JSON.parse(readFileSync(join(HERE, 'package.json'), 'utf8'))
const files = Array.isArray(pkg.files) ? pkg.files : Object.keys(pkg.files ?? {})
for (const file of files) assert.ok(existsSync(join(HERE, file)), `файла из files нет: ${file}`)
for (const file of ['index.js', 'cordis.patch.yml']) assert.ok(files.includes(file), `файла нет в files: ${file}`)
assert.equal(pkg.type, 'module')
assert.equal(pkg.dsh?.bundle?.patch, './cordis.patch.yml', 'dsh.bundle.patch не на cordis.patch.yml')

const patch = parseYaml(readFileSync(join(HERE, 'cordis.patch.yml'), 'utf8'))
assert.ok(Array.isArray(patch), 'патч не список операций')
const insert = patch.flatMap((op) => op.insert ?? [])
assert.ok(insert.length >= 3, `строк в патче ${insert.length}`)

const rows = insert.filter((row) => row.name === '@deepseek-ai/dsh-agent-preset')
const ids = rows.map((row) => row.config.id)
for (const wanted of ['plexus-programmer', 'plexus-analyst']) assert.ok(ids.includes(wanted), `нет пресета ${wanted}`)
for (const row of rows) {
  assert.ok(Array.isArray(row.config.plugins) && row.config.plugins.length > 0, `в ${row.config.id} нет строк`)
  for (const plug of row.config.plugins) assert.equal(typeof plug.name, 'string', `строка без name в ${row.config.id}`)
  assert.ok(row.config.plugins.some((plug) => plug.name === '@deepseek-ai/dsh-skill-filesystem'), `в ${row.config.id} нет каталога скиллов`)
  assert.ok(row.config.plugins.some((plug) => plug.name !== '@deepseek-ai/dsh-skill-filesystem'), `в ${row.config.id} нет инструментов`)
  // Поля Config без default обязательны: схема отвергает строку, и пресет приходит сломанным.
  for (const plug of row.config.plugins) {
    for (const [ключ, значение] of Object.entries(REQUIRED_CONFIG[plug.name] ?? {})) {
      // Парсер выше отдаёт скаляры строками, поэтому сверяем через ту же строковую форму.
      assert.equal(plug.config?.[ключ], String(значение), `в ${row.config.id} ${plug.name} без обязательного ${ключ}: ${JSON.stringify(значение)}`)
    }
  }
  const повтор = insert.filter((other) => other !== row && other.id === row.id)
  assert.equal(повтор.length, 0, `строка патча повторяется: ${row.id}`)
}
for (const row of insert) assert.equal(typeof row.name, 'string', 'строка патча без name')
// Реестр скиллов и инструмент загрузки DSH ставит сам: повтор ломает загрузку профиля.
for (const занято of ['@deepseek-ai/dsh-skill', '@deepseek-ai/dsh-tool-skill']) {
  assert.ok(!insert.some((row) => row.name === занято), `патч повторяет строку базового бандла: ${занято}`)
}
const строки = new Set(insert.map((row) => row.id))
assert.equal(строки.size, insert.length, 'id строк патча повторяются')
assert.ok(insert.some((row) => row.name === pkg.name), `патч не вставляет провайдера скиллов ${pkg.name}`)
for (const row of rows) {
  const персона = row.config.plugins.find((plug) => plug.name === '@deepseek-ai/dsh-persona')
  assert.ok(персона && персона.config?.prefix?.length > 200, `в ${row.config.id} нет брифа работника`)
  assert.match(персона.config.prefix, /^# /, `бриф ${row.config.id} не из agents/*.md (нет заголовка)`)
  assert.ok(!персона.config.prefix.startsWith('---'), `бриф ${row.config.id} с фронтматтером`)
}
console.log(`патч: ${insert.length} строк, пресеты ${ids.join(', ')}`)
