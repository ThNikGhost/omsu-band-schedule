/**
 * Display strings. Pure, Russian-only, no Intl (the Vela engine has no
 * guaranteed Intl support, so month names and plurals are spelled out).
 */

const MONTHS_GENITIVE = [
  'января',
  'февраля',
  'марта',
  'апреля',
  'мая',
  'июня',
  'июля',
  'августа',
  'сентября',
  'октября',
  'ноября',
  'декабря'
]

const WEEKDAYS_SHORT = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб']

/** 525 -> "08:45" */
export function hhmm(minutes) {
  if (minutes === null || minutes === undefined || isNaN(minutes)) {
    return '--:--'
  }
  const total = ((Math.floor(minutes) % 1440) + 1440) % 1440
  return pad(Math.floor(total / 60)) + ':' + pad(total % 60)
}

/** "08:45 – 10:20" */
export function range(start, end) {
  return hhmm(start) + ' – ' + hhmm(end)
}

function pad(value) {
  return value < 10 ? '0' + value : String(value)
}

/**
 * Russian plural. plural(1, 'минута', 'минуты', 'минут') -> 'минута'
 */
export function plural(count, one, few, many) {
  const n = Math.abs(Math.floor(count))
  const mod100 = n % 100
  if (mod100 >= 11 && mod100 <= 14) {
    return many
  }
  const mod10 = n % 10
  if (mod10 === 1) {
    return one
  }
  if (mod10 >= 2 && mod10 <= 4) {
    return few
  }
  return many
}

/** 12 -> "12 мин", 1 -> "1 мин". Under a minute reads as "меньше минуты". */
export function minutesLabel(minutes) {
  const value = Math.max(0, Math.ceil(minutes))
  if (value === 0) {
    return 'меньше минуты'
  }
  if (value < 60) {
    return value + ' мин'
  }
  const hours = Math.floor(value / 60)
  const rest = value % 60
  const hourWord = plural(hours, 'час', 'часа', 'часов')
  if (rest === 0) {
    return hours + ' ' + hourWord
  }
  return hours + ' ' + hourWord + ' ' + rest + ' мин'
}

/** "2026-09-16" -> {y, m, d}; returns null for anything unparseable. */
export function parseISO(iso) {
  if (typeof iso !== 'string' || iso.length < 10) {
    return null
  }
  const y = Number(iso.slice(0, 4))
  const m = Number(iso.slice(5, 7))
  const d = Number(iso.slice(8, 10))
  if (!y || !m || !d || m < 1 || m > 12 || d < 1 || d > 31) {
    return null
  }
  return { y: y, m: m, d: d }
}

/** "2026-09-16" -> "ср, 16 сентября" */
export function dateLabel(iso) {
  const parts = parseISO(iso)
  if (!parts) {
    return iso || ''
  }
  const weekday = WEEKDAYS_SHORT[dayOfWeek(parts)]
  return weekday + ', ' + parts.d + ' ' + MONTHS_GENITIVE[parts.m - 1]
}

/** "Сегодня" / "Завтра" / "ср, 16 сентября", relative to todayIso. */
export function relativeDateLabel(iso, todayIso) {
  const diff = daysBetween(todayIso, iso)
  if (diff === 0) {
    return 'Сегодня'
  }
  if (diff === 1) {
    return 'Завтра'
  }
  return dateLabel(iso)
}

/** Whole days from isoA to isoB; null when either date is unparseable. */
export function daysBetween(isoA, isoB) {
  const a = parseISO(isoA)
  const b = parseISO(isoB)
  if (!a || !b) {
    return null
  }
  return toEpochDay(b) - toEpochDay(a)
}

/** Days since 1970-01-01. Calendar arithmetic without Date or timezones. */
export function toEpochDay(parts) {
  let y = parts.y
  let m = parts.m
  if (m <= 2) {
    y -= 1
    m += 12
  }
  const era = Math.floor(y / 400)
  const yoe = y - era * 400
  const doy = Math.floor((153 * (m - 3) + 2) / 5) + parts.d - 1
  const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy
  return era * 146097 + doe - 719468
}

/** 0 = Sunday, matching WEEKDAYS_SHORT. */
export function dayOfWeek(parts) {
  return (((toEpochDay(parts) + 4) % 7) + 7) % 7
}

/** "2026-09-16T14:05:44+06:00" -> "16 сентября, 14:05" */
export function timestampLabel(iso) {
  if (typeof iso !== 'string' || iso.length < 16) {
    return '—'
  }
  const parts = parseISO(iso.slice(0, 10))
  const time = iso.slice(11, 16)
  if (!parts) {
    return '—'
  }
  return parts.d + ' ' + MONTHS_GENITIVE[parts.m - 1] + ', ' + time
}

/** Anything falsy or "-" becomes an em dash, so the layout never collapses. */
export function orDash(value) {
  if (value === null || value === undefined) {
    return '—'
  }
  const text = String(value).trim()
  return text === '' || text === '-' ? '—' : text
}
