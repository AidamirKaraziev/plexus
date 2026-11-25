// Тест провайдера скиллов Плексуса по собранному пакету (сборка/dsh/):
// каталог, фронтматтер, тело, отсутствие скилла. Гоняет `node доставка/собрать.mjs dsh --проверить`.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { apply, parseFrontmatter, readSkills } from './index.js'

const ROOT = fileURLToPath(new URL('./skills/', import.meta.url))

test('фронтматтер срезан, тело начинается с заголовка', () => {
  const { fields, content } = parseFrontmatter('---\nname: x\ndescription: d\n---\n\n# Заголовок\nтело\n')
  assert.equal(fields.description, 'd')
  assert.equal(content, '# Заголовок\nтело\n')
})

test('без фронтматтера текст остаётся целым', () => {
  const { fields, content } = parseFrontmatter('# Только тело\n')
  assert.deepEqual(fields, {})
  assert.equal(content, '# Только тело\n')
})

test('каталог: скиллы идут с plexus- и описанием', async () => {
  const skills = await readSkills(ROOT)
  assert.ok(skills.length >= 10, `скиллов ${skills.length}`)
  const start = skills.find((s) => s.name === 'plexus-start')
  assert.ok(start, 'нет plexus-start')
  assert.match(start.description, /вход/)
  assert.ok(!start.content.startsWith('---'), 'фронтматтер не срезан')
  assert.match(start.content, /^# /)
})

test('каталог: каждый скилл пакета в каталоге', async () => {
  const папки = readdirSync(ROOT, { withFileTypes: true }).filter((e) => e.isDirectory()).map((e) => `plexus-${e.name}`).sort()
  const skills = await readSkills(ROOT)
  assert.deepEqual(skills.map((s) => s.name), папки)
  console.log(`скиллов в пакете: ${skills.length}`)
})

test('провайдер отдаёт каталог и тело', async () => {
  const провайдер = []
  const ctx = { skills: { registerProvider: (f) => провайдер.push(f({ signal: new AbortController().signal, invalidate() {} })) }, effect() {} }
  apply(ctx)
  const [p] = провайдер
  assert.equal(p.name, 'plexus')
  const { candidates, complete } = await p.list({})
  assert.equal(complete, true)
  const start = candidates.find((c) => c.name === 'plexus-start')
  assert.equal(start.source, 'bundled')
  assert.equal(start.provider, 'plexus')
  assert.ok(start.resourceBase.path.endsWith('/skills/start'))
  const тело = await p.get(start, {})
  assert.equal(тело.name, 'plexus-start')
  assert.match(тело.content, /^# /)
  assert.deepEqual(тело.invocation, { modelInvocable: true, userInvocable: true })
  assert.equal(await p.get({ ...start, locator: 'plexus-нет' }, {}), undefined)
})
