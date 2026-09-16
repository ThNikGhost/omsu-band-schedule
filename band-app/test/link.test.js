/**
 * Receiving side of the interconnect protocol.
 *
 * The frames here are byte-for-byte what astrobox-plugin/core/src/protocol.rs
 * produces; if the two ever drift apart, these tests are where it shows.
 */

import { describe, expect, it } from 'vitest'

import mock from '../src/common/mock.js'
import {
  ASSEMBLY_TIMEOUT_MS,
  PHASE,
  ack,
  createReceiver,
  done,
  failed,
  hasTimedOut,
  step,
  syncRequest,
  unwrap,
  utf8Length,
  validate
} from '../src/common/link.js'

const HASH = mock.h
const T0 = 1_000_000

const full = (payload = mock, hash = HASH) =>
  JSON.stringify({ type: 'sync_full', v: 1, h: hash, d: payload })

/** Same framing the plugin uses for oversized payloads. */
function chunkedFrames(payload, hash, chunkChars) {
  const text = JSON.stringify(payload)
  const chunks = []
  for (let i = 0; i < text.length; i += chunkChars) {
    chunks.push(text.slice(i, i + chunkChars))
  }
  return {
    begin: JSON.stringify({
      type: 'sync_begin',
      v: 1,
      h: hash,
      parts: chunks.length,
      size: utf8Length(text)
    }),
    parts: chunks.map((chunk, i) => JSON.stringify({ type: 'sync_part', v: 1, i, d: chunk })),
    end: JSON.stringify({ type: 'sync_end', v: 1, h: hash })
  }
}

describe('разбор обёрток рантайма', () => {
  it('принимает обычную строку JSON', () => {
    expect(unwrap('{"type":"ack","i":1}').type).toBe('ack')
  });

  it('снимает обёртку {data: ...}', () => {
    // Именно в таком виде сообщение приходит в onmessage.
    expect(unwrap({ data: '{"type":"ack","i":1}' }).type).toBe('ack')
  })

  it('снимает несколько обёрток подряд', () => {
    const nested = { data: JSON.stringify({ data: '{"type":"ack","i":2}' }) }
    expect(unwrap(nested).i).toBe(2)
  })

  it('не зацикливается на мусоре', () => {
    for (const bad of ['', 'не json', null, undefined, 42, [], {}, { data: {} }]) {
      expect(unwrap(bad)).toBe(null)
    }
  })
})

describe('одно сообщение целиком', () => {
  it('принимает расписание и отвечает done', () => {
    const out = step(createReceiver(), full(), T0)

    expect(out.status).toBe('applied')
    expect(out.apply.gid).toBe(5028)
    expect(out.apply.days.length).toBe(9)
    expect(out.send).toHaveLength(1)
    expect(JSON.parse(out.send[0])).toEqual({ type: 'done', v: 1, h: HASH })
    expect(out.state.phase).toBe(PHASE.IDLE)
  })

  it('отвергает расписание с чужим хэшем', () => {
    const out = step(createReceiver(), full(mock, 'deadbeef1234'), T0)

    expect(out.status).toBe('error')
    expect(out.error).toContain('хэш')
    expect(out.apply).toBe(null)
    expect(JSON.parse(out.send[0]).type).toBe('failed')
  })

  it('отвергает чужую версию формата', () => {
    const wrong = Object.assign({}, mock, { v: 2 })
    const out = step(createReceiver(), full(wrong, wrong.h), T0)
    expect(out.status).toBe('error')
    expect(out.apply).toBe(null)
  })

  it('отвергает мусор вместо расписания', () => {
    const out = step(createReceiver(), JSON.stringify({ type: 'sync_full', v: 1, h: 'x', d: 5 }), T0)
    expect(out.status).toBe('error')
  })
})

describe('сборка из частей', () => {
  it('собирает расписание и подтверждает каждую часть', () => {
    const frames = chunkedFrames(mock, HASH, 500)
    expect(frames.parts.length).toBeGreaterThan(5)

    let state = createReceiver()
    let out = step(state, frames.begin, T0)
    expect(out.state.phase).toBe(PHASE.RECEIVING)
    state = out.state

    frames.parts.forEach((frame, index) => {
      out = step(state, frame, T0 + index)
      state = out.state
      // Подтверждение на каждый кадр — иначе у отправителя переполнится окно.
      expect(JSON.parse(out.send[0])).toEqual({ type: 'ack', v: 1, i: index })
    })

    out = step(state, frames.end, T0 + 100)
    expect(out.status).toBe('applied')
    expect(out.apply).toEqual(mock)
    expect(JSON.parse(out.send[0]).type).toBe('done')
    expect(out.state.phase).toBe(PHASE.IDLE)
  })

  it('замечает потерянную часть', () => {
    const frames = chunkedFrames(mock, HASH, 500)
    let state = step(createReceiver(), frames.begin, T0).state

    frames.parts.slice(0, -1).forEach((frame, index) => {
      state = step(state, frame, T0 + index).state
    })

    const out = step(state, frames.end, T0 + 100)
    expect(out.status).toBe('error')
    expect(out.error).toContain('частей')
    expect(out.apply).toBe(null)
  })

  it('дубликат части не считается новой', () => {
    const frames = chunkedFrames(mock, HASH, 500)
    let state = step(createReceiver(), frames.begin, T0).state

    state = step(state, frames.parts[0], T0).state
    state = step(state, frames.parts[0], T0).state
    expect(state.received).toBe(1)
  })

  it('порядок частей не важен', () => {
    const frames = chunkedFrames(mock, HASH, 800)
    let state = step(createReceiver(), frames.begin, T0).state

    const shuffled = frames.parts.map((f, i) => [f, i]).reverse()
    for (const [frame] of shuffled) {
      state = step(state, frame, T0).state
    }

    const out = step(state, frames.end, T0)
    expect(out.status).toBe('applied')
    expect(out.apply).toEqual(mock)
  })

  it('часть с номером вне диапазона игнорируется', () => {
    const frames = chunkedFrames(mock, HASH, 800)
    let state = step(createReceiver(), frames.begin, T0).state
    const out = step(state, JSON.stringify({ type: 'sync_part', v: 1, i: 999, d: 'x' }), T0)
    expect(out.send).toEqual([])
    expect(out.state.received).toBe(0)
  })

  it('часть без начала передачи игнорируется', () => {
    const out = step(createReceiver(), JSON.stringify({ type: 'sync_part', v: 1, i: 0, d: 'x' }), T0)
    expect(out.send).toEqual([])
    expect(out.apply).toBe(null)
  })

  it('не сходится размер — данные отвергаются', () => {
    const text = JSON.stringify(mock)
    const begin = JSON.stringify({ type: 'sync_begin', v: 1, h: HASH, parts: 1, size: text.length + 99 })
    let state = step(createReceiver(), begin, T0).state
    state = step(state, JSON.stringify({ type: 'sync_part', v: 1, i: 0, d: text }), T0).state

    const out = step(state, JSON.stringify({ type: 'sync_end', v: 1, h: HASH }), T0)
    expect(out.status).toBe('error')
    expect(out.error).toContain('размер')
  })

  it('битая склейка не роняет приложение', () => {
    const begin = JSON.stringify({ type: 'sync_begin', v: 1, h: HASH, parts: 1, size: 0 })
    let state = step(createReceiver(), begin, T0).state
    state = step(state, JSON.stringify({ type: 'sync_part', v: 1, i: 0, d: '{обрыв' }), T0).state

    const out = step(state, JSON.stringify({ type: 'sync_end', v: 1, h: HASH }), T0)
    expect(out.status).toBe('error')
    expect(out.apply).toBe(null)
  })
})

describe('прочие сообщения', () => {
  it('up_to_date', () => {
    const out = step(createReceiver(), JSON.stringify({ type: 'up_to_date', v: 1, h: HASH }), T0)
    expect(out.status).toBe('up_to_date')
    expect(out.apply).toBe(null)
    expect(out.send).toEqual([])
  })

  it('error от телефона', () => {
    const out = step(createReceiver(), JSON.stringify({ type: 'error', v: 1, msg: 'нет сети' }), T0)
    expect(out.status).toBe('error')
    expect(out.error).toBe('нет сети')
  })

  it('неизвестный тип не ломает состояние', () => {
    const state = createReceiver()
    const out = step(state, JSON.stringify({ type: 'из_будущего' }), T0)
    expect(out.state).toBe(state)
    expect(out.apply).toBe(null)
  })
})

describe('таймаут сборки', () => {
  it('простаивающая передача признаётся протухшей', () => {
    const frames = chunkedFrames(mock, HASH, 500)
    const state = step(createReceiver(), frames.begin, T0).state

    expect(hasTimedOut(state, T0 + ASSEMBLY_TIMEOUT_MS - 1)).toBe(false)
    expect(hasTimedOut(state, T0 + ASSEMBLY_TIMEOUT_MS + 1)).toBe(true)
  })

  it('каждая часть продлевает срок', () => {
    const frames = chunkedFrames(mock, HASH, 500)
    let state = step(createReceiver(), frames.begin, T0).state
    state = step(state, frames.parts[0], T0 + 20000).state

    expect(hasTimedOut(state, T0 + 40000)).toBe(false)
  })

  it('в покое таймаут не срабатывает', () => {
    expect(hasTimedOut(createReceiver(), T0 + 10 * ASSEMBLY_TIMEOUT_MS)).toBe(false)
  })
})

describe('исходящие сообщения', () => {
  it('sync_req с известным хэшем и без', () => {
    expect(JSON.parse(syncRequest(HASH))).toEqual({ type: 'sync_req', v: 1, have: HASH })
    expect(JSON.parse(syncRequest(null)).have).toBe(null)
    expect(JSON.parse(syncRequest('')).have).toBe(null)
  })

  it('ack, done, failed', () => {
    expect(JSON.parse(ack(3)).i).toBe(3)
    expect(JSON.parse(done(HASH)).h).toBe(HASH)
    expect(JSON.parse(failed('беда')).msg).toBe('беда')
  })
})

describe('utf8Length', () => {
  it('считает так же, как байты на стороне плагина', () => {
    expect(utf8Length('abc')).toBe(3)
    expect(utf8Length('щи')).toBe(4)
    expect(utf8Length('日')).toBe(3)
    expect(utf8Length('😀')).toBe(4)
    expect(utf8Length('')).toBe(0)
    // Реальное расписание целиком.
    const text = JSON.stringify(mock)
    expect(utf8Length(text)).toBe(Buffer.byteLength(text, 'utf8'))
  })
})

describe('validate', () => {
  it('пропускает настоящий ответ сервера', () => {
    expect(validate(mock, mock.h)).toBe(null)
  })

  it('без объявленного хэша проверяется только формат', () => {
    expect(validate(mock, null)).toBe(null)
  })

  it('ловит подмену', () => {
    expect(validate(mock, 'нетакой')).toContain('хэш')
    expect(validate({ v: 1 }, null)).toContain('формат')
  })
})
