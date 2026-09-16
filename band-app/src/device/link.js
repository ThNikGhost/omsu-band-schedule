/**
 * Thin wrapper over @system.interconnect.
 *
 * The connection is created and torn down by the runtime; the app only
 * registers callbacks and checks readiness. Everything here is deliberately
 * dumb - the protocol itself lives in src/common/link.js and is unit-tested.
 *
 * The module is required lazily and only from stage 3 on - see device/stage.js.
 * The instance is never stored on the page view model: the framework would try
 * to make a native object reactive. The page keeps it in a WeakMap instead,
 * which is what the working reference app does.
 */

import { allows, STAGE_INTERCONNECT } from './stage.js'

/** getReadyState reports 1 when the phone is reachable, 2 when it is not. */
export const READY = 1

export const LINK = {
  UNKNOWN: 'unknown',
  CONNECTED: 'connected',
  DISCONNECTED: 'disconnected'
}

/** Resolved on first use, or null when this build must not open a link. */
function moduleOrNull() {
  if (!allows(STAGE_INTERCONNECT)) {
    return null
  }
  try {
    // eslint-disable-next-line no-undef
    const mod = require('@system.interconnect')
    return mod && mod.instance ? mod : null
  } catch (err) {
    console.warn('interconnect unavailable: ' + err)
    return null
  }
}

/**
 * @param {Object} handlers `{onMessage, onOpen, onClose, onError}`
 * @returns the connection instance, or null when interconnect is unavailable
 *          (which is the normal case in the emulator and before stage 3).
 */
export function open(handlers) {
  const interconnect = moduleOrNull()
  if (!interconnect) {
    return null
  }

  let connection = null
  try {
    connection = interconnect.instance()
  } catch (err) {
    console.warn('interconnect.instance() threw: ' + err)
    return null
  }
  if (!connection) {
    return null
  }

  // A throwing handler must not take the page down with it: these run on the
  // single JS thread that also drives the watch UI.
  function guard(fn) {
    return function (data) {
      try {
        fn && fn(data)
      } catch (err) {
        console.warn('interconnect handler threw: ' + err)
      }
    }
  }

  try {
    connection.onopen = guard(handlers.onOpen)
    connection.onclose = guard(handlers.onClose)
    connection.onerror = guard(handlers.onError)
    // The payload arrives as a string, sometimes wrapped; src/common/link.js
    // unwraps it.
    connection.onmessage = guard(handlers.onMessage)
  } catch (err) {
    console.warn('cannot attach interconnect handlers: ' + err)
    return null
  }

  return connection
}

/** Drops every handler so a destroyed page cannot be called back into. */
export function close(connection) {
  if (!connection) {
    return
  }
  try {
    connection.onopen = null
    connection.onclose = null
    connection.onerror = null
    connection.onmessage = null
  } catch (err) {
    console.warn('cannot detach interconnect handlers: ' + err)
  }
}

/** Asks the runtime whether the phone is currently reachable. */
export function checkState(connection, done) {
  if (!connection || !connection.getReadyState) {
    done(LINK.UNKNOWN)
    return
  }
  try {
    connection.getReadyState({
      success: function (data) {
        done(Number(data && data.status) === READY ? LINK.CONNECTED : LINK.DISCONNECTED)
      },
      fail: function () {
        done(LINK.DISCONNECTED)
      }
    })
  } catch (err) {
    done(LINK.UNKNOWN)
  }
}

/**
 * Sends one protocol message.
 *
 * The protocol builders produce strings, because that is what the plugin
 * sends and what the tests compare. But `send` takes an **object**: both the
 * Vela documentation and the working reference app pass one, and the runtime
 * does the encoding. So the string is parsed back here, at the boundary.
 *
 * `done(ok, code)` - code 1006 means the link dropped for good and must not be
 * retried; 202 and 204 are transient.
 */
export function send(connection, text, done) {
  const finish = done || function () {}
  if (!connection || !connection.send) {
    finish(false, 'нет соединения')
    return
  }

  let body = text
  try {
    body = JSON.parse(text)
  } catch (err) {
    // Not JSON: hand it over untouched rather than dropping the message.
    body = text
  }

  try {
    connection.send({
      data: body,
      success: function () {
        finish(true, null)
      },
      fail: function (data, code) {
        finish(false, code)
      }
    })
  } catch (err) {
    finish(false, String(err))
  }
}
