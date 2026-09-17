import { describe, expect, it } from 'vitest'

import baked from '../src/common/baked.js'
import { isApproximate, offlinePayload, parityOf, WINDOW_DAYS } from '../src/common/offline.js'
import { lessonsFor } from '../src/common/schedule.js'

const ANCHOR = baked.anchor

function iso(date) {
  return date.toISOString().slice(0, 10)
}

function plusDays(base, days) {
  const ms = Date.parse(base + 'T00:00:00Z') + days * 86400000
  return iso(new Date(ms))
}

describe('чётность недели', () => {
  it('якорная неделя чётная, следующая нечётная', () => {
    expect(parityOf(ANCHOR, ANCHOR)).toBe(0)
    expect(parityOf(ANCHOR, plusDays(ANCHOR, 6))).toBe(0)
    expect(parityOf(ANCHOR, plusDays(ANCHOR, 7))).toBe(1)
    expect(parityOf(ANCHOR, plusDays(ANCHOR, 13))).toBe(1)
    expect(parityOf(ANCHOR, plusDays(ANCHOR, 14))).toBe(0)
  })

  it('до якоря считается так же, а не уходит в минус', () => {
    // Отрицательный остаток от деления дал бы ключ вида «0--1», которого
    // в цикле нет, и день молча пропал бы с экрана.
    expect(parityOf(ANCHOR, plusDays(ANCHOR, -7))).toBe(1)
    expect(parityOf(ANCHOR, plusDays(ANCHOR, -14))).toBe(0)
    expect(parityOf(ANCHOR, plusDays(ANCHOR, -1))).toBe(1)
  })
})

describe('расписание без телефона', () => {
  it('отдаёт payload той же формы, что сервер', () => {
    const payload = offlinePayload(baked, baked.days[0].d)
    expect(payload.gid).toBe(baked.gid)
    expect(payload.g).toBe(baked.g)
    expect(Array.isArray(payload.days)).toBe(true)
    expect(payload.days.length).toBeGreaterThan(0)

    for (const day of payload.days) {
      expect(day.d).toMatch(/^\d{4}-\d{2}-\d{2}$/)
      expect(day.l.length).toBeGreaterThan(0)
      for (const lesson of day.l) {
        expect(typeof lesson.p).toBe('number')
        expect(typeof lesson.n).toBe('string')
      }
    }
  })

  it('опубликованные дни берутся как есть, без пометки', () => {
    const first = baked.days[0]
    const payload = offlinePayload(baked, first.d)
    const day = payload.days.find((d) => d.d === first.d)
    expect(day.l).toEqual(first.l)
    expect(day.a).toBeUndefined()
    expect(isApproximate(payload, first.d)).toBe(false)
  })

  it('дни за пределом публикации берутся из шаблона и помечены', () => {
    const start = baked.days[0].d
    const payload = offlinePayload(baked, start, WINDOW_DAYS)
    const publishedDates = new Set(baked.days.map((d) => d.d))
    const guessed = payload.days.filter((d) => !publishedDates.has(d.d))

    expect(guessed.length).toBeGreaterThan(0)
    for (const day of guessed) {
      expect(day.a).toBe(1)
      expect(isApproximate(payload, day.d)).toBe(true)
    }
  })

  it('пустой опубликованный день не подменяется шаблоном', () => {
    // Вуз сказал «пар нет» — это факт. Подставить сюда шаблон значило бы
    // позвать человека на пару, которой не будет.
    const start = baked.days[0].d
    const withHole = {
      ...baked,
      days: [{ d: start, l: [] }, ...baked.days.slice(1)]
    }
    const payload = offlinePayload(withHole, start)
    expect(payload.days.find((d) => d.d === start)).toBeUndefined()
  })

  it('работает с обычным поиском дня', () => {
    const payload = offlinePayload(baked, baked.days[0].d)
    const day = payload.days[0]
    expect(lessonsFor(payload, day.d)).toEqual(day.l)
  })

  it('без данных возвращает null, а не падает', () => {
    expect(offlinePayload(null, '2026-09-17')).toBe(null)
    expect(offlinePayload({}, '2026-09-17')).toBe(null)
  })

  it('окно не уходит дальше запрошенного', () => {
    const start = baked.days[0].d
    const payload = offlinePayload(baked, start, 7)
    const last = plusDays(start, 6)
    for (const day of payload.days) {
      expect(day.d >= start).toBe(true)
      expect(day.d <= last).toBe(true)
    }
  })
})

describe('точность шаблона на реальных данных', () => {
  it('шаблон воспроизводит опубликованные дни', () => {
    // Дни, которые вуз уже опубликовал, сравниваются с тем, что предсказал бы
    // шаблон. Это и есть честная оценка: расхождения тут — те же расхождения,
    // которые человек увидит на экране.
    let checked = 0
    let matched = 0

    for (const day of baked.days) {
      const slot =
        ((new Date(day.d + 'T00:00:00Z').getUTCDay() + 6) % 7) +
        '-' +
        parityOf(baked.anchor, day.d)
      const guess = baked.cycle[slot]
      if (!guess) {
        continue
      }
      checked += 1
      const shape = (list) =>
        list
          .map((l) => l.p + '|' + l.n)
          .sort()
          .join(';')
      if (shape(guess) === shape(day.l)) {
        matched += 1
      }
    }

    expect(checked).toBeGreaterThan(0)
    // Порог намеренно низкий: тест сторожит развал шаблона, а не гарантирует
    // точность. Реальная точность на двух семестрах — 85–90%.
    expect(matched / checked).toBeGreaterThan(0.5)
  })
})
