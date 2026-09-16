/**
 * What is happening right now, given the bell schedule and today's lessons.
 *
 * Pure: no @system.* imports, no Date. Every function takes the current moment
 * as minutes from midnight, so the whole thing is testable on Node.
 *
 * Breaks are derived from the lessons the student actually has, not from the
 * bell grid. Someone with pair 1 and pair 4 is not "on a break" for three
 * hours in any useful sense, but they do want to know when pair 4 starts.
 */

export const STATE = {
  NO_LESSONS: 'no_lessons',
  BEFORE: 'before',
  LESSON: 'lesson',
  BREAK: 'break',
  AFTER: 'after'
}

/**
 * @param {Array} lessons  today's lessons, wire format ({p, n, t, r, tc, sg})
 * @param {Object} bells   shared/bells.json
 * @param {number} minutes minutes from midnight
 * @returns {Object} state descriptor
 */
export function describeNow(lessons, bells, minutes) {
  const slots = toSlots(lessons, bells)

  if (slots.length === 0) {
    return { state: STATE.NO_LESSONS, current: null, next: null }
  }

  const first = slots[0]
  const last = slots[slots.length - 1]

  if (minutes < first.start) {
    return {
      state: STATE.BEFORE,
      current: null,
      next: first,
      minutesToNext: first.start - minutes
    }
  }

  if (minutes >= last.end) {
    return { state: STATE.AFTER, current: null, next: null }
  }

  for (let i = 0; i < slots.length; i += 1) {
    const slot = slots[i]

    if (minutes >= slot.start && minutes < slot.end) {
      return describeLesson(slot, slots[i + 1] || null, minutes)
    }

    if (minutes < slot.start) {
      return {
        state: STATE.BREAK,
        current: null,
        next: slot,
        minutesToNext: slot.start - minutes,
        // The 12:05-12:45 window has its own name on the timetable. Decided by
        // the current moment, not by the shape of the gap: with pairs 1 and 4
        // the gap spans it, but at 13:00 the big break is long over.
        isBigBreak: inBigBreak(bells, minutes)
      }
    }
  }

  // Unreachable while slots are sorted and minutes < last.end.
  return { state: STATE.AFTER, current: null, next: null }
}

function describeLesson(slot, next, minutes) {
  const half = halfOf(slot, minutes)
  const base = {
    state: STATE.LESSON,
    current: slot,
    next: next,
    minutesToEnd: slot.end - minutes
  }

  if (!half) {
    base.half = 0
    base.minutesToHalfEnd = slot.end - minutes
    return base
  }

  if (half.index > 0) {
    // Inside the short gap between the two halves of one pair.
    base.half = half.index
    base.inHalfBreak = half.inGap
    base.minutesToHalfEnd = half.end - minutes
    base.halfStart = half.start
    base.halfEnd = half.end
  }

  return base
}

/**
 * Which half of the pair we are in.
 * Returns {index: 1|2, start, end, inGap} or null when the pair has no halves.
 * During the 5-minute gap between halves, reports the upcoming half with inGap.
 */
function halfOf(slot, minutes) {
  const halves = slot.halves
  if (!halves || halves.length === 0) {
    return null
  }

  for (let i = 0; i < halves.length; i += 1) {
    const half = halves[i]
    if (minutes >= half.start && minutes < half.end) {
      return { index: i + 1, start: half.start, end: half.end, inGap: false }
    }
    if (minutes < half.start) {
      return { index: i + 1, start: half.start, end: half.end, inGap: true }
    }
  }

  const lastHalf = halves[halves.length - 1]
  return { index: halves.length, start: lastHalf.start, end: lastHalf.end, inGap: false }
}

/**
 * Join lessons with their bell times. Lessons whose pair number is missing
 * from bells.json are dropped: without a time they cannot be placed.
 */
export function toSlots(lessons, bells) {
  if (!lessons || lessons.length === 0) {
    return []
  }
  const byPair = pairIndex(bells)
  const slots = []

  for (let i = 0; i < lessons.length; i += 1) {
    const lesson = lessons[i]
    const times = byPair[lesson.p]
    if (!times) {
      continue
    }
    slots.push({
      pair: lesson.p,
      start: times.start,
      end: times.end,
      halves: times.halves || [],
      lesson: lesson
    })
  }

  slots.sort(function (a, b) {
    return a.start - b.start || a.pair - b.pair
  })
  return slots
}

export function pairIndex(bells) {
  const index = {}
  const pairs = (bells && bells.pairs) || []
  for (let i = 0; i < pairs.length; i += 1) {
    index[pairs[i].p] = pairs[i]
  }
  return index
}

/** Is `minutes` inside the big break window? Used to highlight the bells table. */
export function inBigBreak(bells, minutes) {
  const big = bells && bells.big_break
  if (!big) {
    return false
  }
  return minutes >= big.start && minutes < big.end
}

/** Pair number currently running per the bell grid, ignoring lessons. */
export function currentBellPair(bells, minutes) {
  const pairs = (bells && bells.pairs) || []
  for (let i = 0; i < pairs.length; i += 1) {
    if (minutes >= pairs[i].start && minutes < pairs[i].end) {
      return pairs[i].p
    }
  }
  return null
}
