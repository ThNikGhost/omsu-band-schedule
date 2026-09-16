/**
 * The exact strings the screens show, driven by the real sample payload
 * (shared/example.json, group 5028). Its first day 2026-09-16 has pairs 1-4.
 */

import { describe, expect, it } from 'vitest'

import bells from '../src/common/bells.js'
import mock from '../src/common/mock.js'
import { STATE } from '../src/common/clock.js'
import {
  bellsView,
  dayRows,
  nextDayView,
  nextIso,
  nowView,
  todayView
} from '../src/common/viewmodel.js'

const TODAY = '2026-09-16'
const at = (h, m) => h * 60 + m

// На экране 212 px в строку влезает около 15 знаков жирным кеглем 22, а перенос
// на устройстве посимвольный: длинный заголовок рвётся посреди слова.
const HEADLINE_LIMIT = 15

describe('экран «Сейчас»', () => {
  it('идёт пара, первая половина', () => {
    const view = nowView(mock, bells, TODAY, at(9, 0))
    expect(view.state).toBe(STATE.LESSON)
    expect(view.headline).toBe('Идёт 1 пара')
    expect(view.detail).toBe('1-я половина · до перемены 30 мин')
    expect(view.card.label).toBe('Сейчас')
    expect(view.card.name).toBe('Методы вычислений')
    expect(view.card.room).toBe('4-303')
  })

  it('перерыв внутри пары', () => {
    const view = nowView(mock, bells, TODAY, at(9, 32))
    expect(view.headline).toBe('Идёт 1 пара')
    expect(view.detail).toBe('перерыв · 2-я половина в 09:35')
  })

  it('вторая половина', () => {
    const view = nowView(mock, bells, TODAY, at(10, 0))
    expect(view.headline).toBe('Идёт 1 пара')
    expect(view.detail).toBe('2-я половина · до конца 20 мин')
  })

  it('обычная перемена', () => {
    const view = nowView(mock, bells, TODAY, at(10, 25))
    expect(view.headline).toBe('Перемена')
    expect(view.detail).toBe('до 10:30 · 2 пара через 5 мин')
    expect(view.card.label).toBe('Дальше')
  })

  it('большой перерыв назван по-своему', () => {
    const view = nowView(mock, bells, TODAY, at(12, 20))
    expect(view.headline).toBe('Большой перерыв')
    expect(view.detail).toBe('до 12:45 · 3 пара через 25 мин')
  })

  it('до начала занятий', () => {
    const view = nowView(mock, bells, TODAY, at(7, 0))
    expect(view.state).toBe(STATE.BEFORE)
    expect(view.detail).toBe('1 пара через 1 час 45 мин')
    expect(view.card.label).toBe('Первая пара')
  })

  it('заголовок всегда помещается в строку', () => {
    // Перебираем сутки по пять минут: любой заголовок, который длиннее строки,
    // на устройстве переносится посреди слова — так «Пары закончились»
    // оставляли одинокий мягкий знак на второй строке.
    const seen = []
    for (let m = 0; m < 24 * 60; m += 5) {
      const view = nowView(mock, bells, TODAY, m)
      if (seen.indexOf(view.headline) < 0) {
        seen.push(view.headline)
      }
      expect(view.headline.length, view.headline).toBeLessThanOrEqual(HEADLINE_LIMIT)
    }
    // Заодно убеждаемся, что перебор действительно прошёл по разным состояниям.
    expect(seen.length).toBeGreaterThan(2)
  })

  it('пары закончились', () => {
    const view = nowView(mock, bells, TODAY, at(20, 0))
    expect(view.headline).toBe('Пар больше нет')
    expect(view.card).toBe(null)
  })

  it('день без пар', () => {
    const view = nowView(mock, bells, '2026-09-20', at(12, 0))
    expect(view.headline).toBe('Сегодня пар нет')
    expect(view.card).toBe(null)
  })

  it('нет кэша вообще', () => {
    const view = nowView(null, bells, TODAY, at(12, 0))
    expect(view.headline).toBe('Сегодня пар нет')
  })
})

describe('экран «Сегодня»', () => {
  it('строки по парам, текущая подсвечена, прошедшие приглушены', () => {
    const view = todayView(mock, bells, TODAY, at(12, 50))
    expect(view.rows).toHaveLength(4)
    expect(view.rows.map((r) => r.pair)).toEqual([1, 2, 3, 4])

    expect(view.rows[0].past).toBe(true)
    expect(view.rows[1].past).toBe(true)
    expect(view.rows[2].current).toBe(true)
    expect(view.rows[2].past).toBe(false)
    expect(view.rows[3].current).toBe(false)
    expect(view.rows[3].past).toBe(false)
  })

  it('подзаголовок — дата, а не слово «Сегодня»: оно уже в шапке', () => {
    expect(todayView(mock, bells, TODAY, null).subtitle).toBe('ср, 16 сентября')
  })

  it('время берётся из звонков, а не из сервера', () => {
    const view = todayView(mock, bells, TODAY, at(9, 0))
    expect(view.rows[0].time).toBe('08:45 – 10:20')
  })

  it('пустой день', () => {
    const view = todayView(mock, bells, '2026-09-20', at(12, 0))
    expect(view.empty).toBe(true)
    expect(view.rows).toEqual([])
  })

  it('ключи строк уникальны при двух подгруппах на одной паре', () => {
    const rows = dayRows([{ p: 3, n: 'A', sg: 1 }, { p: 3, n: 'B', sg: 2 }], bells, null)
    expect(new Set(rows.map((r) => r.key)).size).toBe(2)
  })
})

describe('экран «Завтра»', () => {
  it('17 сентября действительно завтра', () => {
    const view = nextDayView(mock, bells, TODAY)
    expect(view.date).toBe('2026-09-17')
    expect(view.title).toBe('Завтра')
    expect(view.rows.length).toBeGreaterThan(0)
  })

  it('если завтра пусто — показывает ближайший день с парами', () => {
    // 18.09 в выборке нет; от 17-го числа следующий учебный день — 19-е.
    const view = nextDayView(mock, bells, '2026-09-17')
    expect(view.date).toBe('2026-09-19')
    expect(view.title).toBe('Дальше')
    expect(view.subtitle).toBe('сб, 19 сентября')
  })

  it('впереди ничего нет', () => {
    const view = nextDayView(mock, bells, '2030-01-01')
    expect(view.empty).toBe(true)
    expect(view.emptyText).toBe('Впереди пар нет')
  })

  it('nextIso переходит через границу месяца и года', () => {
    expect(nextIso('2026-09-16')).toBe('2026-09-17')
    expect(nextIso('2026-09-30')).toBe('2026-10-01')
    expect(nextIso('2026-12-31')).toBe('2027-01-01')
    expect(nextIso('2028-02-28')).toBe('2028-02-29')
  })
})

describe('экран «Звонки»', () => {
  const pairsOf = (view) => view.rows.filter((r) => r.kind === 'pair').map((r) => r.pair)

  it('показывает пары 1-6, седьмую и восьмую прячет', () => {
    expect(pairsOf(bellsView(bells, at(9, 0), []))).toEqual([1, 2, 3, 4, 5, 6])
  })

  it('седьмая пара появляется, если она есть в расписании', () => {
    const view = bellsView(bells, at(9, 0), [{ p: 7 }])
    expect(pairsOf(view)).toContain(7)
    expect(view.rows.find((r) => r.pair === 7).halves).toEqual([])
  })

  it('подсвечивает текущую пару', () => {
    const view = bellsView(bells, at(9, 0), [])
    expect(view.rows.find((r) => r.pair === 1).current).toBe(true)
    expect(view.rows.find((r) => r.pair === 2).current).toBe(false)
  })

  it('отмечает пары, которые есть у студента', () => {
    const view = bellsView(bells, at(9, 0), [{ p: 2 }])
    expect(view.rows.find((r) => r.pair === 2).scheduled).toBe(true)
    expect(view.rows.find((r) => r.pair === 1).scheduled).toBe(false)
  })

  it('большой перерыв стоит между 2-й и 3-й парой', () => {
    const view = bellsView(bells, at(12, 20), [])
    const kinds = view.rows.map((r) => r.kind)
    const breakAt = kinds.indexOf('break')
    expect(view.rows[breakAt - 1].pair).toBe(2)
    expect(view.rows[breakAt + 1].pair).toBe(3)
    expect(view.rows[breakAt].time).toBe('12:05 – 12:45')
    expect(view.rows[breakAt].current).toBe(true)
  })

  it('ключи строк уникальны — список рисуется по tid', () => {
    const view = bellsView(bells, at(9, 0), [{ p: 7 }, { p: 8 }])
    expect(new Set(view.rows.map((r) => r.key)).size).toBe(view.rows.length)
  })

  it('половины пары показаны', () => {
    const view = bellsView(bells, null, [])
    expect(view.rows[0].halves).toEqual(['08:45 – 09:30', '09:35 – 10:20'])
  })
})
