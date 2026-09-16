/**
 * Cross-language contract: frames produced by the plugin, consumed by the band.
 *
 * The two ends of the protocol are written in different languages, so agreeing
 * on paper is not enough. test/data/plugin-frames.json is emitted by the real
 * Rust sender:
 *
 *   cd astrobox-plugin && cargo run -p omsu-sync-core --example emit_frames \
 *       --target x86_64-unknown-linux-gnu
 *
 * If either side changes its framing, these tests fail.
 */

import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import mock from '../src/common/mock.js'
import { PHASE, createReceiver, step } from '../src/common/link.js'

const here = dirname(fileURLToPath(import.meta.url))
const fixture = JSON.parse(readFileSync(join(here, 'data', 'plugin-frames.json'), 'utf8'))

const T0 = 1_000_000

/** Feed frames through the receiver the way the .ux page does. */
function replay(frames) {
  let state = createReceiver()
  const sent = []
  let applied = null
  let error = null

  frames.forEach((frame, index) => {
    const out = step(state, frame, T0 + index)
    state = out.state
    sent.push(...out.send)
    if (out.apply) applied = out.apply
    if (out.error) error = out.error
  })

  return { state, sent, applied, error }
}

describe('одно сообщение от плагина', () => {
  it('в реальном расписании ровно один кадр', () => {
    // Это и есть причина, по которой нарезка — запасной путь.
    expect(fixture.single.frames).toHaveLength(1)
    expect(fixture.single.payload_bytes).toBe(4372)
  })

  it('браслет принимает его и отвечает done', () => {
    const { applied, sent, error, state } = replay(fixture.single.frames)

    expect(error).toBe(null)
    expect(applied).toEqual(mock)
    expect(state.phase).toBe(PHASE.IDLE)
    expect(sent).toHaveLength(1)
    expect(JSON.parse(sent[0])).toEqual({
      type: 'done',
      v: 1,
      h: fixture.single.hash
    })
  })
})

describe('нарезка от плагина', () => {
  it('фикстура действительно нарезана', () => {
    expect(fixture.chunked.frames.length).toBeGreaterThan(3)
  })

  it('браслет собирает payload обратно байт в байт', () => {
    const { applied, error } = replay(fixture.chunked.frames)

    expect(error).toBe(null)
    expect(applied).not.toBe(null)
    expect(JSON.stringify(applied)).toBe(fixture.chunked.payload)
  })

  it('на каждую часть уходит подтверждение, и в конце done', () => {
    const { sent } = replay(fixture.chunked.frames)
    const parsed = sent.map((s) => JSON.parse(s))

    const acks = parsed.filter((m) => m.type === 'ack')
    const dones = parsed.filter((m) => m.type === 'done')

    // begin и end не подтверждаются, части — каждая.
    expect(acks).toHaveLength(fixture.chunked.frames.length - 2)
    expect(acks.map((m) => m.i)).toEqual(acks.map((_, i) => i))
    expect(dones).toHaveLength(1)
    expect(dones[0].h).toBe(fixture.chunked.hash)
  })

  it('кириллица не бьётся на границах кусков', () => {
    // Плагин режет по символам, а не по байтам; если бы по байтам —
    // половина двухбайтовых букв развалилась бы.
    const { applied } = replay(fixture.chunked.frames)
    expect(applied._pad).toContain('Очень длинное название дисциплины')
  })

  it('потеря любой одной части замечается', () => {
    const frames = fixture.chunked.frames
    for (let drop = 1; drop < frames.length - 1; drop += 1) {
      const without = frames.filter((_, i) => i !== drop)
      const { applied, error } = replay(without)
      expect(applied, `часть ${drop} пропущена, но данные приняты`).toBe(null)
      expect(error).toBeTruthy()
    }
  })
})

describe('формат кадров', () => {
  it('все кадры — валидный JSON с полем type', () => {
    const all = [...fixture.single.frames, ...fixture.chunked.frames]
    for (const frame of all) {
      const parsed = JSON.parse(frame)
      expect(typeof parsed.type).toBe('string')
      expect(parsed.v).toBe(1)
    }
  })

  it('ни один кадр не превышает потолок в 16 КБ', () => {
    const all = [...fixture.single.frames, ...fixture.chunked.frames]
    for (const frame of all) {
      expect(Buffer.byteLength(frame, 'utf8')).toBeLessThanOrEqual(16 * 1024)
    }
  })

  it('расписание передаётся объектом, а не строкой', () => {
    // Строкой было бы вдвое длиннее: каждая кириллическая буква ушла бы
    // в \uXXXX.
    const parsed = JSON.parse(fixture.single.frames[0])
    expect(typeof parsed.d).toBe('object')
  })
})
