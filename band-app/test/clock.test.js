/**
 * describeNow: what the watch says at a given minute.
 *
 * Times come from the real bell schedule:
 *   pair 1  08:45-10:20  (525-620), halves 525-570 / 575-620
 *   pair 2  10:30-12:05  (630-725), halves 630-675 / 680-725
 *   big break            (725-765)
 *   pair 3  12:45-14:20  (765-860), halves 765-810 / 815-860
 *   pair 4  14:30-16:05  (870-965)
 */

import { describe, expect, it } from 'vitest'

import bells from '../src/common/bells.js'
import { STATE, currentBellPair, describeNow, inBigBreak, toSlots } from '../src/common/clock.js'

const lesson = (p, n) => ({ p, n: n || ('Пара ' + p), t: 'Лек', r: '4-101', tc: 'Иванов И. И.', sg: null })

const at = (h, m) => h * 60 + m

describe('нет пар', () => {
  it('пустой день', () => {
    expect(describeNow([], bells, at(12, 0)).state).toBe(STATE.NO_LESSONS)
  })

  it('пары есть, но их номеров нет в звонках', () => {
    expect(describeNow([{ p: 99 }], bells, at(12, 0)).state).toBe(STATE.NO_LESSONS)
  })
})

describe('до начала занятий', () => {
  it('утро перед первой парой', () => {
    const info = describeNow([lesson(1)], bells, at(8, 0))
    expect(info.state).toBe(STATE.BEFORE)
    expect(info.minutesToNext).toBe(45)
    expect(info.next.pair).toBe(1)
  })

  it('первая пара у студента — третья по сетке', () => {
    const info = describeNow([lesson(3)], bells, at(8, 0))
    expect(info.state).toBe(STATE.BEFORE)
    expect(info.next.pair).toBe(3)
  })
})

describe('идёт пара', () => {
  it('первая половина', () => {
    const info = describeNow([lesson(1)], bells, at(9, 0))
    expect(info.state).toBe(STATE.LESSON)
    expect(info.current.pair).toBe(1)
    expect(info.half).toBe(1)
    expect(info.inHalfBreak).toBe(false)
    expect(info.minutesToHalfEnd).toBe(30) // до 09:30
  })

  it('перерыв внутри пары', () => {
    const info = describeNow([lesson(1)], bells, at(9, 32))
    expect(info.state).toBe(STATE.LESSON)
    expect(info.half).toBe(2)
    expect(info.inHalfBreak).toBe(true)
    expect(info.halfStart).toBe(at(9, 35))
  })

  it('вторая половина', () => {
    const info = describeNow([lesson(1)], bells, at(10, 0))
    expect(info.half).toBe(2)
    expect(info.inHalfBreak).toBe(false)
    expect(info.minutesToEnd).toBe(20) // до 10:20
  })

  it('границы включительно слева, исключительно справа', () => {
    expect(describeNow([lesson(1)], bells, at(8, 45)).state).toBe(STATE.LESSON)
    expect(describeNow([lesson(1)], bells, at(10, 20)).state).toBe(STATE.AFTER)
  })

  it('пара без деления на половины (7-я)', () => {
    const info = describeNow([lesson(7)], bells, at(20, 0))
    expect(info.state).toBe(STATE.LESSON)
    expect(info.half).toBe(0)
  })
})

describe('перемена', () => {
  it('между соседними парами', () => {
    const info = describeNow([lesson(1), lesson(2)], bells, at(10, 25))
    expect(info.state).toBe(STATE.BREAK)
    expect(info.isBigBreak).toBe(false)
    expect(info.minutesToNext).toBe(5)
    expect(info.next.pair).toBe(2)
  })

  it('большой перерыв распознаётся отдельно', () => {
    const info = describeNow([lesson(2), lesson(3)], bells, at(12, 20))
    expect(info.state).toBe(STATE.BREAK)
    expect(info.isBigBreak).toBe(true)
    expect(info.minutesToNext).toBe(25)
  })

  it('окно между 1 и 4 парой — не большой перерыв', () => {
    // Пары 1 и 4: окно с 10:20 до 14:30 покрывает большой перерыв,
    // но предыдущая пара кончилась задолго до него.
    const info = describeNow([lesson(1), lesson(4)], bells, at(13, 0))
    expect(info.state).toBe(STATE.BREAK)
    expect(info.isBigBreak).toBe(false)
    expect(info.next.pair).toBe(4)
  })
})

describe('после занятий', () => {
  it('сразу после последней пары', () => {
    expect(describeNow([lesson(1)], bells, at(10, 20)).state).toBe(STATE.AFTER)
  })

  it('поздно вечером', () => {
    expect(describeNow([lesson(1), lesson(2)], bells, at(23, 0)).state).toBe(STATE.AFTER)
  })
})

describe('toSlots', () => {
  it('сортирует по времени начала', () => {
    const slots = toSlots([lesson(4), lesson(1), lesson(2)], bells)
    expect(slots.map((s) => s.pair)).toEqual([1, 2, 4])
  })

  it('отбрасывает пары без времени', () => {
    expect(toSlots([lesson(1), { p: 42 }], bells).map((s) => s.pair)).toEqual([1])
  })

  it('сохраняет обе подгруппы на одной паре', () => {
    const slots = toSlots([{ p: 3, sg: 1 }, { p: 3, sg: 2 }], bells)
    expect(slots).toHaveLength(2)
  })

  it('пустой вход', () => {
    expect(toSlots(null, bells)).toEqual([])
    expect(toSlots([], bells)).toEqual([])
  })
})

describe('вспомогательное', () => {
  it('inBigBreak', () => {
    expect(inBigBreak(bells, at(12, 30))).toBe(true)
    expect(inBigBreak(bells, at(12, 5))).toBe(true)
    expect(inBigBreak(bells, at(12, 45))).toBe(false)
    expect(inBigBreak(bells, at(9, 0))).toBe(false)
  })

  it('currentBellPair', () => {
    expect(currentBellPair(bells, at(9, 0))).toBe(1)
    expect(currentBellPair(bells, at(12, 30))).toBe(null)
    expect(currentBellPair(bells, at(3, 0))).toBe(null)
  })
})
