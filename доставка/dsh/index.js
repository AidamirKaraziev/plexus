/**
 * Плексус для DSH (пакет @plexus-dsh/plexus): провайдер реестра скиллов.
 *
 * Исходник живёт в доставка/dsh/ репозитория Плексуса; пакет собирает
 * `node доставка/собрать.mjs dsh` в сборка/dsh/ и кладёт рядом копию skills/
 * Плексуса — пакет самодостаточный, вне репозитория ему ничего не нужно.
 *
 * Скиллы. Образец — @deepseek-ai/dsh-skill-office: провайдер отдаёт каталог
 * (`list`) и полное тело по выбранному скиллу (`get`), а не копирует SKILL.md
 * в профиль. Имя скилла — `<префикс><папка>`, по умолчанию `plexus-start`:
 * реестр DSH принимает только `kebab-case` без точки и косой черты, поэтому
 * команда в DSH читается как `plexus-start`, а не `/plexus:start` — об этом
 * сказано в README.
 *
 * Тело скилла — SKILL.md без фронтматтера; описание и версия из фронтматтера
 * уходят в каталог, относительные ресурсы находятся от папки скилла.
 *
 * Пресеты работников (`plexus-programmer`, `plexus-analyst`) — строки
 * `@deepseek-ai/dsh-agent-preset` в cordis.patch.yml этого же пакета; сборщик
 * пишет их из agents/*.md.
 *
 * Расход, кэш промпта, обрезку чтений и разведчика пакет не делает — это
 * плагины plexus-dsh; здесь только скиллы и пресеты.
 */
import { readdir, readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import z from '@deepseek-ai/schemastery'

export const name = '@plexus-dsh/plexus'
export const inject = ['skills']

/** Провайдер скиллов: `<префикс><папка>` из каталога скиллов Плексуса. */
const PROVIDER = 'plexus'
/** Префикс по умолчанию: имя скилла DSH — только `kebab-case`, без `:` и `/`. */
const DEFAULT_PREFIX = 'plexus-'
/** Имя скилла по правилу реестра DSH. */
const SKILL_NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/
/** Ранг: как у прочих пакетных провайдеров скиллов (BUNDLED_SKILL_RANK). */
const RANK = 600
/** Каталог скиллов по умолчанию: `skills/` внутри пакета (кладёт сборщик). */
const DEFAULT_ROOT = fileURLToPath(new URL('./skills/', import.meta.url))

/** Схема конфига — schemastery: Cordis ждёт `Config['~standard'].validate`. */
export const Config = z.object({
  root: z
    .string()
    .default('')
    .description('Каталог скиллов; пусто — skills/ внутри пакета.'),
  prefix: z
    .string()
    .default(DEFAULT_PREFIX)
    .description('Префикс имени скилла, только kebab-case.'),
})

/** Разобрать фронтматтер SKILL.md: `key: value` верхнего уровня, без вложенности. */
export function parseFrontmatter(text) {
  if (!text.startsWith('---')) return { fields: {}, content: text }
  const end = text.indexOf('\n---', 3)
  if (end === -1) return { fields: {}, content: text }
  const fields = {}
  for (const line of text.slice(3, end).split('\n')) {
    const at = line.indexOf(':')
    if (at <= 0 || line.trimStart().startsWith('#')) continue
    fields[line.slice(0, at).trim()] = line.slice(at + 1).trim()
  }
  const content = text.slice(text.indexOf('\n', end + 1) + 1)
  return { fields, content: content.replace(/^\n+/, '') }
}

/** Прочитать все скиллы каталога: папки с SKILL.md, у которых есть описание. */
export async function readSkills(root, prefix = DEFAULT_PREFIX) {
  let entries
  try {
    entries = await readdir(root, { withFileTypes: true })
  } catch {
    return []
  }
  const skills = []
  for (const entry of entries) {
    if (!entry.isDirectory()) continue
    const dir = join(root, entry.name)
    let text
    try {
      text = await readFile(join(dir, 'SKILL.md'), 'utf8')
    } catch {
      continue
    }
    const { fields, content } = parseFrontmatter(text)
    if (fields.description === undefined || fields.description === '') continue
    const local = fields.name ?? entry.name
    const name = `${prefix}${local}`
    if (!SKILL_NAME.test(name)) continue
    skills.push({
      name,
      local,
      description: fields.description,
      version: fields.version,
      dir,
      content,
    })
  }
  return skills.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))
}

/** Тело скилла и его метаданные для реестра DSH. */
function definition(skill, provider) {
  return {
    name: skill.name,
    description: skill.description,
    source: 'bundled',
    provider,
    resourceBase: { kind: 'directory', path: skill.dir },
    invocation: { modelInvocable: true, userInvocable: true },
    content: skill.content,
  }
}

/** Плагин: регистрирует провайдер скиллов Плексуса в реестре DSH. */
export function apply(ctx, config = {}) {
  const root = config.root || DEFAULT_ROOT
  const prefix = config.prefix || DEFAULT_PREFIX
  let cache
  const catalog = async () => (cache ??= await readSkills(root, prefix))
  ctx.skills.registerProvider((control) => ({
    name: PROVIDER,
    async list() {
      if (control.signal.aborted) return { candidates: [], complete: false }
      const skills = await catalog()
      return {
        candidates: skills.map((skill) => ({
          name: skill.name,
          description: skill.description,
          source: 'bundled',
          provider: PROVIDER,
          rank: RANK,
          resourceBase: { kind: 'directory', path: skill.dir },
          invocation: { modelInvocable: true, userInvocable: true },
          locator: skill.name,
        })),
        complete: true,
      }
    },
    async get(candidate) {
      const skills = await catalog()
      const skill = skills.find((s) => s.name === candidate.locator)
      return skill === undefined ? undefined : definition(skill, PROVIDER)
    },
  }))
  ctx.effect(() => () => {
    cache = undefined
  })
}
