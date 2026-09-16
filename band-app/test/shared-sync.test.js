/**
 * src/common/bells.js and mock.js are generated from shared/. If someone edits
 * shared/bells.json and forgets `npm run gen`, the watch would silently show
 * different times than the server and the ICS feed. This catches that.
 */

import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import bells from '../src/common/bells.js'
import mock from '../src/common/mock.js'

const here = dirname(fileURLToPath(import.meta.url))
const shared = join(here, '..', '..', 'shared')

const read = (name) => JSON.parse(readFileSync(join(shared, name), 'utf8'))

describe('данные синхронны с shared/', () => {
  it('bells.js совпадает с shared/bells.json', () => {
    expect(bells).toEqual(read('bells.json'))
  })

  it('mock.js совпадает с shared/example.json', () => {
    expect(mock).toEqual(read('example.json'))
  })
})

describe('пример подчиняется контракту', () => {
  it('версия формата та, которую понимает приложение', () => {
    expect(mock.v).toBe(1)
  })

  it('дни отсортированы и непустые', () => {
    const dates = mock.days.map((d) => d.d)
    expect(dates).toEqual([...dates].sort())
    expect(mock.days.every((d) => d.l.length > 0)).toBe(true)
  })

  it('пары внутри дня отсортированы', () => {
    for (const day of mock.days) {
      const pairs = day.l.map((x) => x.p)
      expect(pairs).toEqual([...pairs].sort((a, b) => a - b))
    }
  })

  it('названия влезают в 32 символа', () => {
    for (const day of mock.days) {
      for (const lesson of day.l) {
        expect(lesson.n.length).toBeLessThanOrEqual(32)
      }
    }
  })

  it('каждая пара есть в сетке звонков', () => {
    const known = new Set(bells.pairs.map((p) => p.p))
    for (const day of mock.days) {
      for (const lesson of day.l) {
        expect(known.has(lesson.p)).toBe(true)
      }
    }
  })
})
