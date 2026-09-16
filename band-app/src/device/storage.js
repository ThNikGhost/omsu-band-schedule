/**
 * Cache in @system.storage.
 *
 * The only part of the app that touches storage, so the protocol logic in
 * src/common/ stays testable. Values are strings only - objects have to be
 * stringified by hand.
 *
 * Writing goes to a temporary key first, is read back, and only then replaces
 * the live one. A half-written value would otherwise leave the watch showing
 * nothing at all, which is worse than showing yesterday's schedule.
 */

import storage from '@system.storage'

export const KEY = 'omsu.schedule.v1'
export const TMP_KEY = 'omsu.schedule.v1.tmp'
export const META_KEY = 'omsu.meta.v1'

/**
 * The runtime returns a stored value in one of three shapes depending on
 * version; the reference app handles all three, so this does too.
 */
function valueOf(data) {
  if (typeof data === 'string') {
    return data
  }
  if (data && typeof data.data === 'string') {
    return data.data
  }
  if (data && typeof data.value === 'string') {
    return data.value
  }
  return ''
}

function readKey(key, done) {
  try {
    storage.get({
      key: key,
      default: '',
      success: function (data) {
        done(valueOf(data))
      },
      fail: function () {
        done('')
      }
    })
  } catch (err) {
    console.warn('storage.get failed: ' + err)
    done('')
  }
}

function writeKey(key, value, done) {
  try {
    storage.set({
      key: key,
      value: value,
      success: function () {
        done(true)
      },
      fail: function (data, code) {
        console.warn('storage.set failed: ' + code)
        done(false)
      }
    })
  } catch (err) {
    console.warn('storage.set threw: ' + err)
    done(false)
  }
}

function deleteKey(key) {
  try {
    // An empty value deletes the entry, per the Vela storage docs; delete()
    // is called first and this is the fallback.
    storage.delete({ key: key, success: function () {}, fail: function () {} })
  } catch (err) {
    console.warn('storage.delete threw: ' + err)
  }
}

/** Reads the cached payload, or null when there is none or it is unusable. */
export function readPayload(done) {
  readKey(KEY, function (text) {
    if (!text) {
      done(null)
      return
    }
    try {
      done(JSON.parse(text))
    } catch (err) {
      console.warn('cached payload is not valid JSON, ignoring')
      done(null)
    }
  })
}

/**
 * Stores a payload. Temp write, read-back, then replace: a device that ran
 * out of space truncates silently, and the read-back is what catches it.
 */
export function writePayload(payload, done) {
  let text = ''
  try {
    text = JSON.stringify(payload)
  } catch (err) {
    done(false, 'не удалось сериализовать расписание')
    return
  }

  writeKey(TMP_KEY, text, function (ok) {
    if (!ok) {
      done(false, 'не удалось записать во временный ключ')
      return
    }

    readKey(TMP_KEY, function (readBack) {
      if (readBack !== text) {
        deleteKey(TMP_KEY)
        done(false, 'запись не подтвердилась, места может не хватать')
        return
      }

      writeKey(KEY, text, function (stored) {
        deleteKey(TMP_KEY)
        done(stored, stored ? null : 'не удалось сохранить расписание')
      })
    })
  })
}

/** Small bookkeeping blob: when we last synced, what the link said. */
export function readMeta(done) {
  readKey(META_KEY, function (text) {
    if (!text) {
      done({})
      return
    }
    try {
      done(JSON.parse(text) || {})
    } catch (err) {
      done({})
    }
  })
}

export function writeMeta(meta, done) {
  let text = '{}'
  try {
    text = JSON.stringify(meta)
  } catch (err) {
    text = '{}'
  }
  writeKey(META_KEY, text, done || function () {})
}

/** Used by the status screen to offer a clean slate. */
export function clearAll() {
  deleteKey(KEY)
  deleteKey(TMP_KEY)
  deleteKey(META_KEY)
}
