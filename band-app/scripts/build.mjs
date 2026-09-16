/**
 * Wrapper around `aiot build`.
 *
 * The toolkit swallows build exceptions and still exits 0
 * (node_modules/aiot-toolkit/lib/bin.js: `catch (error) { ColorConsole.error(...) }`
 * with no process.exit), so a failed build looks exactly like a good one and
 * leaves the previous .rpk sitting in dist/. That cost us an evening once.
 *
 * This checks what actually happened: the success line is present, no error
 * line is, and the package on disk is newer than when we started.
 */

import { spawnSync } from 'node:child_process'
import { readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const DIST = new URL('../dist/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')

function packages() {
  try {
    return readdirSync(DIST)
      .filter((name) => name.endsWith('.rpk'))
      .map((name) => ({ name, mtime: statSync(join(DIST, name)).mtimeMs }))
  } catch (err) {
    return []
  }
}

const startedAt = Date.now()
const before = packages()

// One command string rather than an args array: `aiot` is a .cmd shim on
// Windows and needs a shell, and Node deprecates combining shell with args.
const command = ['aiot', 'build', ...process.argv.slice(2)].join(' ')
const run = spawnSync(command, {
  stdio: ['inherit', 'pipe', 'pipe'],
  shell: true,
  encoding: 'utf8'
})

const output = (run.stdout || '') + (run.stderr || '')
process.stdout.write(output)

const problems = []

if (run.status !== 0) {
  problems.push(`aiot build завершился с кодом ${run.status}`)
}
if (/Build Error/i.test(output)) {
  problems.push('в выводе есть «Build Error» — сборка упала, но код возврата это скрыл')
}
if (!/build success/i.test(output)) {
  problems.push('в выводе нет «build success»')
}

// Warnings do not fail the build, but they are the only signal the compiler
// gives for an unknown component, attribute, event or style value.
const warnings = output.split('\n').filter((line) => /unsupport|Unknown element|missing attributes/i.test(line))
for (const line of warnings) {
  problems.push('предупреждение компилятора: ' + line.trim())
}

const after = packages()
const fresh = after.filter((pkg) => pkg.mtime >= startedAt)
if (fresh.length === 0) {
  problems.push(
    after.length === 0
      ? 'в dist/ нет ни одного .rpk'
      : 'пакет в dist/ не пересобран — там лежит прежний файл: ' + after.map((p) => p.name).join(', ')
  )
}

if (problems.length > 0) {
  console.error('\n🔴 Сборка не подтверждена:')
  for (const problem of problems) {
    console.error('   - ' + problem)
  }
  process.exit(1)
}

const stale = before.filter((pkg) => !fresh.some((item) => item.name === pkg.name))
if (stale.length > 0) {
  console.warn('\n🟠 В dist/ остались пакеты от прошлых сборок: ' + stale.map((p) => p.name).join(', '))
}

console.log('\n✅ Пакет собран и проверен: ' + fresh.map((p) => p.name).join(', '))
