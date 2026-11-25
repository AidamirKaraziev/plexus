#!/usr/bin/env node
// Сборщик слоя доставки: из общей логики Плексуса (skills/, agents/) и
// адаптера хоста (доставка/<хост>/) собирает готовый пакет в сборка/<хост>/.
//
//   node доставка/собрать.mjs dsh              — пакет @plexus-dsh/plexus в сборка/dsh/
//   node доставка/собрать.mjs dsh --проверить  — то же и проверки по собранной папке
//   node доставка/собрать.mjs версия           — записать версию из VERSION во все манифесты
//   node доставка/собрать.mjs версия --проверить — только сверить; расхождение — код 1 и список файлов
//
// Повторный запуск чистит папку сборки; остаётся только node_modules (зависимости
// для проверок, в пакет не идут). Папка сборка/ в .gitignore.
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const КОРЕНЬ = join(dirname(fileURLToPath(import.meta.url)), '..')
const ИСХОДНИК = join(КОРЕНЬ, 'доставка', 'dsh')
const СБОРКА = join(КОРЕНЬ, 'сборка', 'dsh')
/** Работники Плексуса, которые идут пресетами DSH: имя файла в agents/ и порядок в списке. */
const РАБОТНИКИ = [
  ['programmer', 10],
  ['analyst', 20],
]
/** Файлы адаптера, которые кладутся в сборку как есть. */
const ФАЙЛЫ = ['index.js', 'README.md', 'check-patch.mjs', 'test-provider.mjs']
const МУСОР = new Set(['__pycache__', '.DS_Store', 'node_modules'])

const стоп = (текст) => {
  console.error(`сборка ОСТАНОВЛЕНА: ${текст}`)
  process.exit(1)
}

/** Файлы с полем version, которые держим равными VERSION. OpenCode берёт версию из корневого package.json. */
const МАНИФЕСТЫ = ['.claude-plugin/plugin.json', '.codex-plugin/plugin.json', 'package.json']

function прочестьВерсию() {
  const в = readFileSync(join(КОРЕНЬ, 'VERSION'), 'utf8').trim()
  if (!/^\d+\.\d+\.\d+(-beta\.\d+)?$/.test(в)) стоп(`в VERSION «${в}» не вида X.Y.Z или X.Y.Z-beta.N`)
  return в
}

/** Версия из VERSION во все манифесты; с --проверить только сверяет. */
function версияМанифестов(проверять) {
  const версия = прочестьВерсию()
  const разошлись = []
  for (const путь of МАНИФЕСТЫ) {
    const файл = join(КОРЕНЬ, путь)
    const текст = readFileSync(файл, 'utf8')
    const м = текст.match(/("version"\s*:\s*")([^"]*)(")/)
    if (!м) стоп(`нет поля version в ${путь}`)
    if (м[2] === версия) continue
    разошлись.push(`${путь}: ${м[2]} ≠ ${версия}`)
    if (!проверять) writeFileSync(файл, текст.replace(м[0], м[1] + версия + м[3]))
  }
  if (проверять) {
    if (разошлись.length) стоп(`версия расходится с VERSION (${версия}):\n  ${разошлись.join('\n  ')}`)
    console.log(`версия ${версия}: все манифесты совпадают (${МАНИФЕСТЫ.join(', ')})`)
  } else {
    console.log(`версия ${версия}: записана${разошлись.length ? ', исправлено: ' + разошлись.map((x) => x.split(':')[0]).join(', ') : ', менять нечего'}`)
  }
}

/** Фронтматтер и тело markdown-файла агента. */
function агент(имя) {
  const текст = readFileSync(join(КОРЕНЬ, 'agents', `${имя}.md`), 'utf8')
  const м = текст.match(/^---\n([\s\S]*?)\n---\n+/)
  if (!м) стоп(`agents/${имя}.md без фронтматтера`)
  const поля = {}
  for (const строка of м[1].split('\n')) {
    const at = строка.indexOf(':')
    if (at > 0) поля[строка.slice(0, at).trim()] = строка.slice(at + 1).trim()
  }
  if (!поля.description) стоп(`agents/${имя}.md без description`)
  return { описание: поля.description, тело: текст.slice(м[0].length).replace(/\s+$/, '') + '\n' }
}

function собратьDsh() {
  // 1. чистая папка (node_modules оставляем: это зависимости проверок, не пакет)
  mkdirSync(СБОРКА, { recursive: true })
  for (const e of readdirSync(СБОРКА)) if (e !== 'node_modules') rmSync(join(СБОРКА, e), { recursive: true, force: true })

  // 2. код адаптера
  for (const f of ФАЙЛЫ) cpSync(join(ИСХОДНИК, f), join(СБОРКА, f))

  // 3. package.json: версия пакета = версия Плексуса из VERSION
  const версия = прочестьВерсию()
  const pkg = JSON.parse(readFileSync(join(ИСХОДНИК, 'package.json'), 'utf8'))
  pkg.version = версия
  writeFileSync(join(СБОРКА, 'package.json'), JSON.stringify(pkg, null, 2) + '\n')

  // 4. копия skills/ без мусора
  cpSync(join(КОРЕНЬ, 'skills'), join(СБОРКА, 'skills'), {
    recursive: true,
    filter: (путь) => !МУСОР.has(путь.split('/').pop()),
  })

  // 5. cordis.patch.yml: строка провайдера + пресет на каждого работника из agents/
  const шаблон = readFileSync(join(ИСХОДНИК, 'пресет.yml'), 'utf8')
  const пресеты = РАБОТНИКИ.map(([имя, порядок]) => {
    const { описание, тело } = агент(имя)
    const бриф = тело
      .split('\n')
      .map((строка) => (строка ? ' '.repeat(16) + строка : ''))
      .join('\n')
      .replace(/\n+$/, '')
    return шаблон
      .replaceAll('{{id}}', `plexus-${имя}`)
      .replace('{{order}}', String(порядок))
      .replace('{{description}}', JSON.stringify(описание))
      .replace('{{бриф}}', () => бриф)
      .replace(/\n+$/, '')
  }).join('\n')
  const патч = readFileSync(join(ИСХОДНИК, 'cordis.patch.yml'), 'utf8')
  if (!патч.includes('{{пресеты}}')) стоп('в доставка/dsh/cordis.patch.yml нет места {{пресеты}}')
  writeFileSync(join(СБОРКА, 'cordis.patch.yml'), патч.replace('{{пресеты}}', () => пресеты))

  const скиллов = readdirSync(join(СБОРКА, 'skills'), { withFileTypes: true }).filter((e) => e.isDirectory()).length
  console.log(`собрано: сборка/dsh — ${pkg.name}@${версия}, скиллов ${скиллов}, пресеты ${РАБОТНИКИ.map(([и]) => `plexus-${и}`).join(', ')}`)
}

/** Проверки по собранной папке: патч и провайдер скиллов. */
function проверитьDsh() {
  const запуск = (команда, аргументы) => {
    const r = spawnSync(команда, аргументы, { cwd: СБОРКА, stdio: 'inherit' })
    if (r.status !== 0) стоп(`не прошла проверка: ${команда} ${аргументы.join(' ')}`)
  }
  // провайдеру нужна @deepseek-ai/schemastery (dependencies пакета)
  if (!existsSync(join(СБОРКА, 'node_modules', '@deepseek-ai', 'schemastery'))) {
    запуск('npm', ['install', '--prefer-offline', '--omit=peer', '--no-package-lock', '--no-audit', '--no-fund'])
  }
  запуск('node', ['check-patch.mjs'])
  запуск('node', ['--test', 'test-provider.mjs'])
  console.log('проверка: зелёная')
}

const [хост, ...флаги] = process.argv.slice(2)
if (хост === 'версия') {
  for (const ф of флаги) if (ф !== '--проверить') стоп(`неизвестный флаг «${ф}»`)
  версияМанифестов(флаги.includes('--проверить'))
  process.exit(0)
}
if (хост !== 'dsh') стоп(`хост «${хост ?? ''}» неизвестен. Нужно: node доставка/собрать.mjs dsh|версия [--проверить]`)
for (const ф of флаги) if (ф !== '--проверить') стоп(`неизвестный флаг «${ф}»`)
собратьDsh()
if (флаги.includes('--проверить')) проверитьDsh()
