/**
 * Turns state into the exact strings the screens render.
 *
 * Kept out of the .ux on purpose: this is where all the wording and edge cases
 * live, and it is the part worth unit-testing. The page component only assigns
 * the result to its data model.
 */

import { STATE, describeNow, toSlots } from './clock.js'
import { dateLabel, hhmm, minutesLabel, orDash, range, relativeDateLabel } from './format.js'
import { lessonsFor, nextDayWithLessons } from './schedule.js'

/**
 * The "Сейчас" screen.
 *
 * @param {Object} payload  cached server payload (may be null)
 * @param {Object} bells    bells.json
 * @param {string} todayIso "YYYY-MM-DD" in device local time
 * @param {number} minutes  minutes from midnight
 */
export function nowView(payload, bells, todayIso, minutes) {
  const lessons = lessonsFor(payload, todayIso)
  const info = describeNow(lessons, bells, minutes)

  if (info.state === STATE.NO_LESSONS) {
    return {
      state: info.state,
      headline: 'Сегодня пар нет',
      detail: '',
      card: null
    }
  }

  if (info.state === STATE.AFTER) {
    return {
      state: info.state,
      headline: 'Пары закончились',
      detail: '',
      card: null
    }
  }

  if (info.state === STATE.BEFORE) {
    return {
      state: info.state,
      headline: 'Занятия ещё не начались',
      detail: info.next.pair + ' пара через ' + minutesLabel(info.minutesToNext),
      card: lessonCard(info.next, 'Первая пара')
    }
  }

  if (info.state === STATE.BREAK) {
    const headline = info.isBigBreak ? 'Большой перерыв' : 'Перемена';
    return {
      state: info.state,
      headline: headline + ' до ' + hhmm(info.next.start),
      detail: info.next.pair + ' пара через ' + minutesLabel(info.minutesToNext),
      card: lessonCard(info.next, 'Дальше')
    }
  }

  return lessonNow(info)
}

function lessonNow(info) {
  const slot = info.current
  const parts = ['Идёт ' + slot.pair + ' пара']
  let detail

  if (info.half === 1 && !info.inHalfBreak) {
    parts.push('1-я половина')
    detail = 'до перемены ' + minutesLabel(info.minutesToHalfEnd)
  } else if (info.half === 2 && info.inHalfBreak) {
    // The 5-minute gap in the middle of a pair.
    parts.push('перерыв')
    detail = '2-я половина в ' + hhmm(info.halfStart)
  } else if (info.half === 2) {
    parts.push('2-я половина')
    detail = 'до конца ' + minutesLabel(info.minutesToEnd)
  } else {
    detail = 'до конца ' + minutesLabel(info.minutesToEnd)
  }

  return {
    state: STATE.LESSON,
    headline: parts.join(' · '),
    detail: detail,
    card: lessonCard(slot, 'Сейчас')
  }
}

function lessonCard(slot, label) {
  if (!slot) {
    return null
  }
  const lesson = slot.lesson
  return {
    label: label,
    pair: slot.pair,
    time: range(slot.start, slot.end),
    name: orDash(lesson.n),
    type: lesson.t || '',
    room: orDash(lesson.r),
    teacher: orDash(lesson.tc),
    subgroup: lesson.sg || null
  }
}

/**
 * A day's lessons as rows, with the current one marked and past ones dimmed.
 * `minutes` may be null when the day being shown is not today.
 */
export function dayRows(lessons, bells, minutes) {
  const slots = toSlots(lessons, bells)
  const rows = []

  for (let i = 0; i < slots.length; i += 1) {
    const slot = slots[i]
    const lesson = slot.lesson
    const isCurrent = minutes !== null && minutes >= slot.start && minutes < slot.end
    const isPast = minutes !== null && minutes >= slot.end

    rows.push({
      key: slot.pair + '-' + i,
      pair: slot.pair,
      time: range(slot.start, slot.end),
      start: hhmm(slot.start),
      name: orDash(lesson.n),
      type: lesson.t || '',
      room: orDash(lesson.r),
      teacher: orDash(lesson.tc),
      subgroup: lesson.sg || null,
      current: isCurrent,
      past: isPast
    })
  }
  return rows
}

/** The "Сегодня" screen. */
export function todayView(payload, bells, todayIso, minutes) {
  const lessons = lessonsFor(payload, todayIso)
  return {
    title: 'Сегодня',
    // Заголовок экрана уже говорит «Сегодня», поэтому здесь полезнее дата.
    subtitle: dateLabel(todayIso),
    date: todayIso,
    rows: dayRows(lessons, bells, minutes),
    empty: lessons.length === 0
  }
}

/**
 * The "Завтра" screen. Shows the nearest day that has lessons, not a literal
 * tomorrow, because an empty tomorrow is common and useless to look at.
 */
export function nextDayView(payload, bells, todayIso) {
  const day = nextDayWithLessons(payload, nextIso(todayIso))
  if (!day) {
    return {
      title: 'Дальше',
      subtitle: '',
      date: null,
      rows: [],
      empty: true,
      emptyText: 'Впереди пар нет'
    }
  }
  return {
    title: relativeDateLabel(day.d, todayIso) === 'Завтра' ? 'Завтра' : 'Дальше',
    subtitle: relativeDateLabel(day.d, todayIso),
    date: day.d,
    rows: dayRows(day.l, bells, null),
    empty: false,
    emptyText: ''
  }
}

/** "2026-09-16" -> "2026-09-17", via plain calendar arithmetic. */
export function nextIso(iso) {
  const date = new Date(iso + 'T00:00:00Z')
  if (isNaN(date.getTime())) {
    return iso
  }
  date.setUTCDate(date.getUTCDate() + 1)
  return date.toISOString().slice(0, 10)
}

/**
 * The "Звонки" screen: the bell grid with the running pair highlighted.
 * The big break is returned as a row of its own, in its place in the sequence,
 * so the screen can render everything as one uniform scrollable list.
 */
export function bellsView(bells, minutes, lessons) {
  const pairs = (bells && bells.pairs) || []
  const big = (bells && bells.big_break) || null
  const scheduled = {}
  const list = lessons || []
  for (let i = 0; i < list.length; i += 1) {
    scheduled[list[i].p] = true
  }

  const rows = []
  for (let i = 0; i < pairs.length; i += 1) {
    const pair = pairs[i]
    // Pairs 7-8 are absent from the official sheet; show them only when used.
    if (pair.halves.length === 0 && !scheduled[pair.p]) {
      continue
    }
    rows.push({
      key: 'p' + pair.p,
      kind: 'pair',
      pair: pair.p,
      time: range(pair.start, pair.end),
      halves: pair.halves.map(function (half) {
        return range(half.start, half.end)
      }),
      current: minutes !== null && minutes >= pair.start && minutes < pair.end,
      scheduled: !!scheduled[pair.p]
    })

    if (big && big.after_pair === pair.p) {
      rows.push({
        key: 'big',
        kind: 'break',
        pair: 0,
        time: range(big.start, big.end),
        halves: [],
        title: 'Большой перерыв',
        current: minutes !== null && minutes >= big.start && minutes < big.end,
        scheduled: false
      })
    }
  }

  return { title: 'Звонки', rows: rows }
}
