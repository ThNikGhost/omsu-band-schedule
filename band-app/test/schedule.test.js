import { describe, expect, it } from 'vitest'

import mock from '../src/common/mock.js'
import {
  ageHours,
  countLessons,
  isStale,
  isValidPayload,
  lessonsFor,
  nextDayWithLessons,
  pruneBefore
} from '../src/common/schedule.js'

const HOUR = 3600000
const SRC_MS = Date.parse(mock.src)

describe('isValidPayload', () => {
  it('принимает реальный ответ сервера', () => {
    expect(isValidPayload(mock)).toBe(true)
  })

  it.each([
    ['null', null],
    ['строка', 'что-то'],
    ['число', 42],
    ['пустой объект', {}],
    ['чужая версия', { v: 2, days: [] }],
    ['days не массив', { v: 1, days: {} }],
    ['день без даты', { v: 1, days: [{ l: [] }] }],
    ['день без списка', { v: 1, days: [{ d: '2026-09-16' }] }]
  ])('отвергает: %s', (_label, value) => {
    expect(isValidPayload(value)).toBe(false)
  })

  it('пустой days — валидно: вуз публикует неглубоко', () => {
    expect(isValidPayload({ v: 1, days: [] })).toBe(true)
  })
})

describe('lessonsFor', () => {
  it('находит день', () => {
    expect(lessonsFor(mock, '2026-09-16')).toHaveLength(4)
  })

  it('день без пар отсутствует в выборке — это пустой список, не ошибка', () => {
    expect(lessonsFor(mock, '2026-09-20')).toEqual([])
  })

  it('битый кэш не роняет экран', () => {
    expect(lessonsFor(null, '2026-09-16')).toEqual([])
    expect(lessonsFor({ v: 9 }, '2026-09-16')).toEqual([])
  })
})

describe('nextDayWithLessons', () => {
  it('берёт самый ранний день начиная с указанного', () => {
    expect(nextDayWithLessons(mock, '2026-09-16').d).toBe('2026-09-16')
    expect(nextDayWithLessons(mock, '2026-09-17').d).toBe('2026-09-17')
    expect(nextDayWithLessons(mock, '2026-09-18').d).toBe('2026-09-19')
  })

  it('прошлое игнорируется', () => {
    expect(nextDayWithLessons(mock, '2020-01-01').d).toBe(mock.days[0].d)
  })

  it('впереди пусто', () => {
    expect(nextDayWithLessons(mock, '2030-01-01')).toBe(null)
  })
})

describe('возраст данных', () => {
  it('ageHours', () => {
    expect(ageHours(mock, SRC_MS)).toBeCloseTo(0, 5)
    expect(ageHours(mock, SRC_MS + 5 * HOUR)).toBeCloseTo(5, 5)
    expect(ageHours({ src: 'мусор' }, SRC_MS)).toBe(null)
    expect(ageHours({}, SRC_MS)).toBe(null)
  })

  it('свежие данные не считаются устаревшими', () => {
    expect(isStale(mock, SRC_MS + HOUR, 24)).toBe(false)
  })

  it('старше суток — устарели', () => {
    expect(isStale(mock, SRC_MS + 25 * HOUR, 24)).toBe(true)
  })

  it('сервер сам сказал stale — верим ему', () => {
    const stale = Object.assign({}, mock, { stale: true })
    expect(isStale(stale, SRC_MS, 24)).toBe(true)
  })

  it('кэша нет — считаем устаревшим', () => {
    expect(isStale(null, SRC_MS, 24)).toBe(true)
  })
})

describe('обслуживание кэша', () => {
  it('countLessons', () => {
    expect(countLessons(mock)).toBe(34)
    expect(countLessons(null)).toBe(0)
  })

  it('pruneBefore выбрасывает прошедшие дни, остальное сохраняет', () => {
    const pruned = pruneBefore(mock, '2026-09-19')
    expect(pruned.days.every((d) => d.d >= '2026-09-19')).toBe(true)
    expect(pruned.days.length).toBeLessThan(mock.days.length)
    expect(pruned.h).toBe(mock.h)
    expect(pruned.gid).toBe(mock.gid)
  })

  it('pruneBefore не мутирует исходный объект', () => {
    const before = mock.days.length
    pruneBefore(mock, '2026-09-19')
    expect(mock.days.length).toBe(before)
  })
})
