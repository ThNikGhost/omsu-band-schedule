import { describe, expect, it } from 'vitest'

import {
  dateLabel,
  dayOfWeek,
  daysBetween,
  hhmm,
  minutesLabel,
  orDash,
  parseISO,
  plural,
  range,
  relativeDateLabel,
  timestampLabel,
  toEpochDay
} from '../src/common/format.js'

describe('hhmm', () => {
  it.each([
    [525, '08:45'],
    [0, '00:00'],
    [1439, '23:59'],
    [725, '12:05'],
    [60, '01:00']
  ])('%i -> %s', (minutes, expected) => {
    expect(hhmm(minutes)).toBe(expected)
  })

  it('мусор не роняет экран', () => {
    expect(hhmm(null)).toBe('--:--')
    expect(hhmm(undefined)).toBe('--:--')
    expect(hhmm(NaN)).toBe('--:--')
  })

  it('range', () => {
    expect(range(525, 620)).toBe('08:45 – 10:20')
  })
})

describe('склонения', () => {
  it.each([
    [1, 'минута'],
    [2, 'минуты'],
    [4, 'минуты'],
    [5, 'минут'],
    [11, 'минут'],
    [14, 'минут'],
    [21, 'минута'],
    [22, 'минуты'],
    [25, 'минут'],
    [101, 'минута'],
    [111, 'минут'],
    [0, 'минут']
  ])('%i -> %s', (n, expected) => {
    expect(plural(n, 'минута', 'минуты', 'минут')).toBe(expected)
  })
})

describe('minutesLabel', () => {
  it.each([
    [12, '12 мин'],
    [1, '1 мин'],
    [59, '59 мин'],
    [60, '1 час'],
    [90, '1 час 30 мин'],
    [120, '2 часа'],
    [300, '5 часов']
  ])('%i -> %s', (n, expected) => {
    expect(minutesLabel(n)).toBe(expected)
  })

  it('меньше минуты', () => {
    expect(minutesLabel(0)).toBe('меньше минуты')
    expect(minutesLabel(-5)).toBe('меньше минуты')
  })

  it('округляет вверх: 11.2 минуты это ещё 12', () => {
    expect(minutesLabel(11.2)).toBe('12 мин')
  })
})

describe('даты', () => {
  it('parseISO', () => {
    expect(parseISO('2026-09-16')).toEqual({ y: 2026, m: 9, d: 16 })
    expect(parseISO('плохо')).toBe(null)
    expect(parseISO(null)).toBe(null)
    expect(parseISO('2026-13-01')).toBe(null)
  })

  it('toEpochDay совпадает с Date.UTC', () => {
    const cases = ['1970-01-01', '2000-02-29', '2026-09-16', '2027-03-01', '2024-12-31']
    for (const iso of cases) {
      const expected = Date.UTC(...iso.split('-').map(Number).map((v, i) => (i === 1 ? v - 1 : v))) / 86400000
      expect(toEpochDay(parseISO(iso))).toBe(expected)
    }
  })

  it('dayOfWeek: 16.09.2026 — среда', () => {
    expect(dayOfWeek(parseISO('2026-09-16'))).toBe(3)
    expect(dayOfWeek(parseISO('2026-09-20'))).toBe(0) // воскресенье
  })

  it('daysBetween', () => {
    expect(daysBetween('2026-09-16', '2026-09-17')).toBe(1)
    expect(daysBetween('2026-09-16', '2026-09-16')).toBe(0)
    expect(daysBetween('2026-09-17', '2026-09-16')).toBe(-1)
    expect(daysBetween('2026-02-28', '2026-03-01')).toBe(1) // 2026 не високосный
    expect(daysBetween('плохо', '2026-09-16')).toBe(null)
  })

  it('dateLabel', () => {
    expect(dateLabel('2026-09-16')).toBe('ср, 16 сентября')
    expect(dateLabel('2026-01-01')).toBe('чт, 1 января')
  })

  it('relativeDateLabel', () => {
    expect(relativeDateLabel('2026-09-16', '2026-09-16')).toBe('Сегодня')
    expect(relativeDateLabel('2026-09-17', '2026-09-16')).toBe('Завтра')
    expect(relativeDateLabel('2026-09-19', '2026-09-16')).toBe('сб, 19 сентября')
  })

  it('timestampLabel', () => {
    expect(timestampLabel('2026-09-16T14:05:44+06:00')).toBe('16 сентября, 14:05')
    expect(timestampLabel('')).toBe('—')
    expect(timestampLabel(null)).toBe('—')
  })
})

describe('orDash', () => {
  it('прочерк вместо пустоты', () => {
    expect(orDash(null)).toBe('—')
    expect(orDash('')).toBe('—')
    expect(orDash('   ')).toBe('—')
    // Апстрим ОмГУ отдаёт "-" вместо преподавателя.
    expect(orDash('-')).toBe('—')
  })

  it('нормальные значения не трогает', () => {
    expect(orDash('4-101')).toBe('4-101')
    expect(orDash('Гусс С. В.')).toBe('Гусс С. В.')
  })
})
