/**
 * Reading the payload the server produced. Pure.
 *
 * Wire format (see shared/schema.json):
 *   {v, gid, g, gen, src, stale, h, days: [{d, l: [{p, n, t, r, tc, sg}]}]}
 *
 * The server already filtered by subgroup and sorted everything, so this module
 * only has to look things up and answer "is this still worth showing".
 */

import { daysBetween } from './format.js'

export const WIRE_VERSION = 1

/** Structural check. A half-written cache must never crash the watch. */
export function isValidPayload(payload) {
  if (!payload || typeof payload !== 'object') {
    return false
  }
  if (payload.v !== WIRE_VERSION) {
    return false
  }
  if (!payload.days || Object.prototype.toString.call(payload.days) !== '[object Array]') {
    return false
  }
  for (let i = 0; i < payload.days.length; i += 1) {
    const day = payload.days[i]
    if (!day || typeof day.d !== 'string') {
      return false
    }
    if (Object.prototype.toString.call(day.l) !== '[object Array]') {
      return false
    }
  }
  return true
}

/** Lessons for one date, or [] when that day is absent (which means no lessons). */
export function lessonsFor(payload, iso) {
  if (!isValidPayload(payload)) {
    return []
  }
  for (let i = 0; i < payload.days.length; i += 1) {
    if (payload.days[i].d === iso) {
      return payload.days[i].l || []
    }
  }
  return []
}

/**
 * The next day at or after `fromIso` that actually has lessons.
 * Returns {d, l} or null. Used by the "Завтра" screen, which shows the nearest
 * teaching day rather than a literal tomorrow that is often empty.
 */
export function nextDayWithLessons(payload, fromIso) {
  if (!isValidPayload(payload)) {
    return null
  }
  let best = null
  for (let i = 0; i < payload.days.length; i += 1) {
    const day = payload.days[i]
    if (!day.l || day.l.length === 0) {
      continue
    }
    const diff = daysBetween(fromIso, day.d)
    if (diff === null || diff < 0) {
      continue
    }
    if (best === null || day.d < best.d) {
      best = day
    }
  }
  return best
}

/** How old the data is, in hours. null when unknown. */
export function ageHours(payload, nowMs) {
  if (!payload || typeof payload.src !== 'string') {
    return null
  }
  const stamp = Date.parse(payload.src)
  if (isNaN(stamp)) {
    return null
  }
  return (nowMs - stamp) / 3600000
}

/**
 * Should the user be warned the data is old?
 * Either the server said so, or the snapshot is more than a day behind.
 */
export function isStale(payload, nowMs, maxAgeHours) {
  if (!payload) {
    return true
  }
  if (payload.stale === true) {
    return true
  }
  const age = ageHours(payload, nowMs)
  if (age === null) {
    return false
  }
  return age > (maxAgeHours || 24)
}

/** Total lessons in the payload; used for the status screen. */
export function countLessons(payload) {
  if (!isValidPayload(payload)) {
    return 0
  }
  let total = 0
  for (let i = 0; i < payload.days.length; i += 1) {
    total += (payload.days[i].l || []).length
  }
  return total
}

/** Drop days that are already in the past, so the cache does not grow forever. */
export function pruneBefore(payload, iso) {
  if (!isValidPayload(payload)) {
    return payload
  }
  const kept = []
  for (let i = 0; i < payload.days.length; i += 1) {
    const day = payload.days[i]
    const diff = daysBetween(iso, day.d)
    if (diff !== null && diff >= 0) {
      kept.push(day)
    }
  }
  const copy = {}
  for (const key in payload) {
    if (Object.prototype.hasOwnProperty.call(payload, key)) {
      copy[key] = payload[key]
    }
  }
  copy.days = kept
  return copy
}
