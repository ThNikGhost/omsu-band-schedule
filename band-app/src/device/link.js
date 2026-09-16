/**
 * Thin wrapper over @system.interconnect.
 *
 * The connection is created and torn down by the runtime; the app only
 * registers callbacks and checks readiness. Everything here is deliberately
 * dumb - the protocol itself lives in src/common/link.js and is unit-tested.
 */

import interconnect from '@system.interconnect'

/** getReadyState reports 1 when the phone is reachable, 2 when it is not. */
export const READY = 1

export const LINK = {
  UNKNOWN: 'unknown',
  CONNECTED: 'connected',
  DISCONNECTED: 'disconnected'
}

/**
 * @param {Object} handlers `{onMessage, onOpen, onClose, onError}`
 * @returns the connection instance, or null when interconnect is unavailable
 *          (which is the normal case in the emulator).
 */
export function open(handlers) {
  let connection = null
  try {
    connection = interconnect.instance()
  } catch (err) {
    console.warn('interconnect unavailable: ' + err)
    return null
  }
  if (!connection) {
    return null
  }

  connection.onopen = function (data) {
    handlers.onOpen && handlers.onOpen(data)
  }
  connection.onclose = function (data) {
    handlers.onClose && handlers.onClose(data)
  }
  connection.onerror = function (data) {
    handlers.onError && handlers.onError(data)
  }
  connection.onmessage = function (data) {
    // The payload arrives as a string, sometimes wrapped; src/common/link.js
    // unwraps it.
    handlers.onMessage && handlers.onMessage(data)
  }

  return connection
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
 * `done(ok, code)` - code 1006 means the link dropped, 204 a timeout.
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
