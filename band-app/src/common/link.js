/**
 * Talking to the AstroBox plugin over interconnect.
 *
 * Pure: takes a raw message and the current time, returns the next state plus
 * the actions to perform. The @system.* wrappers in src/device/ do the actual
 * sending and storing, so the whole protocol is testable on Node.
 *
 * Integrity of a reassembled payload is checked without hashing anything on
 * the watch: the payload carries its own `h` field, so a corrupt reassembly
 * either fails JSON.parse or disagrees with the hash announced in sync_begin.
 * That catches lost, duplicated and reordered chunks, which are the failures
 * that actually happen. It is not an authenticity check - BLE pairing and the
 * plugin already bound that.
 */

import { isValidPayload } from './schedule.js'

export const PROTOCOL_VERSION = 1

/** Give up on a half-received transfer after this long without a chunk. */
export const ASSEMBLY_TIMEOUT_MS = 30000

export const PHASE = {
  IDLE: 'idle',
  RECEIVING: 'receiving'
}

/** Runtime wrappers seen in practice; peel until a protocol message appears. */
const MAX_UNWRAP_DEPTH = 6

export function createReceiver() {
  return {
    phase: PHASE.IDLE,
    hash: null,
    parts: 0,
    size: 0,
    chunks: [],
    received: 0,
    startedAt: 0,
    lastPartAt: 0
  }
}

// -------------------------------------------------------------- outgoing

/** Ask the plugin for a schedule. `have` lets it answer "nothing changed". */
export function syncRequest(have) {
  return JSON.stringify({
    type: 'sync_req',
    v: PROTOCOL_VERSION,
    have: have || null
  })
}

export function ack(index) {
  return JSON.stringify({ type: 'ack', v: PROTOCOL_VERSION, i: index })
}

export function done(hash) {
  return JSON.stringify({ type: 'done', v: PROTOCOL_VERSION, h: hash })
}

export function failed(message) {
  return JSON.stringify({ type: 'failed', v: PROTOCOL_VERSION, msg: String(message) })
}

// -------------------------------------------------------------- incoming

/**
 * Peel runtime wrappers off an incoming message.
 *
 * The quick app runtime may hand over the payload as a string, as `{data: ...}`,
 * or as several of those nested; the working reference app unwraps up to six
 * levels, so this does the same. Returns a protocol object or null.
 */
export function unwrap(raw) {
  let candidate = raw

  for (let depth = 0; depth < MAX_UNWRAP_DEPTH; depth += 1) {
    if (typeof candidate === 'string') {
      const parsed = tryParse(candidate)
      if (parsed === candidate) {
        return null
      }
      candidate = parsed
      continue
    }

    if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) {
      return null
    }

    if (typeof candidate.type === 'string') {
      return candidate
    }

    if (candidate.data !== undefined) {
      candidate = candidate.data
      continue
    }

    return null
  }

  return null
}

function tryParse(text) {
  try {
    return JSON.parse(text)
  } catch (err) {
    return text
  }
}

/**
 * Advance the receiver by one message.
 *
 * @returns {Object} `{state, send, apply, status, error, log}` where `send` is
 * a list of strings to hand to interconnect and `apply` is a payload to store.
 */
export function step(state, raw, nowMs) {
  const message = unwrap(raw)
  if (!message) {
    return result(state, { log: 'не удалось разобрать сообщение' })
  }

  switch (message.type) {
    case 'sync_full':
      return applyFull(state, message)
    case 'sync_begin':
      return beginTransfer(state, message, nowMs)
    case 'sync_part':
      return acceptPart(state, message, nowMs)
    case 'sync_end':
      return finishTransfer(state, message)
    case 'up_to_date':
      return result(createReceiver(), {
        status: 'up_to_date',
        log: 'расписание не менялось'
      })
    case 'error':
      return result(createReceiver(), {
        status: 'error',
        error: String(message.msg || 'ошибка на телефоне'),
        log: 'телефон сообщил об ошибке'
      })
    default:
      return result(state, { log: 'неизвестный тип сообщения: ' + message.type })
  }
}

function applyFull(state, message) {
  const payload = message.d
  const problem = validate(payload, message.h)
  if (problem) {
    return result(createReceiver(), {
      send: [failed(problem)],
      status: 'error',
      error: problem,
      log: 'данные отклонены: ' + problem
    })
  }
  return result(createReceiver(), {
    apply: payload,
    send: [done(payload.h)],
    status: 'applied',
    log: 'расписание принято одним сообщением'
  })
}

function beginTransfer(state, message, nowMs) {
  const parts = Number(message.parts)
  if (!parts || parts < 1) {
    return result(createReceiver(), {
      send: [failed('некорректное число частей')],
      status: 'error',
      error: 'некорректное число частей'
    })
  }

  const next = createReceiver()
  next.phase = PHASE.RECEIVING
  next.hash = message.h || null
  next.parts = parts
  next.size = Number(message.size) || 0
  next.chunks = new Array(parts).fill(null)
  next.startedAt = nowMs
  next.lastPartAt = nowMs

  return result(next, { status: 'receiving', log: 'приём: частей ' + parts })
}

function acceptPart(state, message, nowMs) {
  if (state.phase !== PHASE.RECEIVING) {
    // A stray chunk with no sync_begin: ignore rather than guess.
    return result(state, { log: 'часть пришла вне передачи' })
  }

  const index = Number(message.i)
  if (!(index >= 0 && index < state.parts)) {
    return result(state, { log: 'часть с номером вне диапазона: ' + message.i })
  }

  const next = copy(state)
  // A duplicate must not inflate the counter, or sync_end would fire early.
  if (next.chunks[index] === null) {
    next.received += 1
  }
  next.chunks[index] = String(message.d === undefined ? '' : message.d)
  next.lastPartAt = nowMs

  return result(next, { send: [ack(index)], status: 'receiving' })
}

function finishTransfer(state, message) {
  if (state.phase !== PHASE.RECEIVING) {
    return result(state, { log: 'конец передачи без начала' })
  }

  if (state.received !== state.parts) {
    const problem = 'получено ' + state.received + ' частей из ' + state.parts
    return result(createReceiver(), {
      send: [failed(problem)],
      status: 'error',
      error: problem,
      log: problem
    })
  }

  const text = state.chunks.join('')
  if (state.size && utf8Length(text) !== state.size) {
    const problem = 'размер не совпал'
    return result(createReceiver(), {
      send: [failed(problem)],
      status: 'error',
      error: problem,
      log: problem
    })
  }

  let payload = null
  try {
    payload = JSON.parse(text)
  } catch (err) {
    return result(createReceiver(), {
      send: [failed('собранные данные не разбираются')],
      status: 'error',
      error: 'собранные данные не разбираются',
      log: 'JSON.parse не смог разобрать склеенные части'
    })
  }

  const announced = message.h || state.hash
  const problem = validate(payload, announced)
  if (problem) {
    return result(createReceiver(), {
      send: [failed(problem)],
      status: 'error',
      error: problem,
      log: 'данные отклонены: ' + problem
    })
  }

  return result(createReceiver(), {
    apply: payload,
    send: [done(payload.h)],
    status: 'applied',
    log: 'расписание собрано из ' + state.parts + ' частей'
  })
}

/** Returns a problem description, or null when the payload is good. */
export function validate(payload, announcedHash) {
  if (!isValidPayload(payload)) {
    return 'формат данных не подходит'
  }
  if (announcedHash && payload.h !== announcedHash) {
    return 'хэш не совпал'
  }
  return null
}

/** Has a half-finished transfer gone quiet for too long? */
export function hasTimedOut(state, nowMs) {
  return state.phase === PHASE.RECEIVING && nowMs - state.lastPartAt > ASSEMBLY_TIMEOUT_MS
}

/** Bytes this string would occupy as UTF-8; the plugin counts in bytes. */
export function utf8Length(text) {
  let bytes = 0
  for (let i = 0; i < text.length; i += 1) {
    const code = text.charCodeAt(i)
    if (code < 0x80) {
      bytes += 1
    } else if (code < 0x800) {
      bytes += 2
    } else if (code >= 0xd800 && code <= 0xdbff) {
      // Surrogate pair: four bytes, and the low half is consumed here.
      bytes += 4
      i += 1
    } else {
      bytes += 3
    }
  }
  return bytes
}

function copy(state) {
  return {
    phase: state.phase,
    hash: state.hash,
    parts: state.parts,
    size: state.size,
    chunks: state.chunks.slice(),
    received: state.received,
    startedAt: state.startedAt,
    lastPartAt: state.lastPartAt
  }
}

function result(state, extra) {
  return {
    state: state,
    send: (extra && extra.send) || [],
    apply: (extra && extra.apply) || null,
    status: (extra && extra.status) || null,
    error: (extra && extra.error) || null,
    log: (extra && extra.log) || null
  }
}
