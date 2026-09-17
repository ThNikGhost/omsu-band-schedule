/**
 * Расписание без телефона.
 *
 * У браслета одна активная bluetooth-сессия, и если её держит Mi Fitness ради
 * сна и пульса, то AstroBox до браслета не достучится (docs/DECISIONS.md).
 * Поэтому расписание вшивается прямо в сборку, и приложение работает совсем
 * само по себе.
 *
 * Вшитое расписание состоит из двух частей, и они очень разные по надёжности:
 *
 *   days   реальные дни, опубликованные вузом. Правда, но их мало: вперёд
 *          публикуют примерно на десять дней.
 *   cycle  двухнедельный шаблон по дням недели. Им заполняются даты, до
 *          которых публикация не дошла.
 *
 * Точность шаблона измерена на реальных данных группы 5028 за два семестра:
 * 85–90% дней совпадают полностью. Ошибается он почти всегда в одну сторону —
 * в жизни появляется пара, которой в шаблоне нет (так среди семестра
 * начинается новый предмет). Поэтому вычисленные дни помечаются `a: 1`,
 * и экран показывает их как приблизительные: обещать точность, которой нет,
 * хуже, чем честно сказать «примерно».
 *
 * Здесь нет ни одного `@system.*` — модуль чистый и проверяется на Node.
 */

/** Сколько дней вперёд собирать. Больше двух недель смысла не имеет. */
export const WINDOW_DAYS = 14

const MS_PER_DAY = 86400000

function toUtc(iso) {
  const parts = String(iso).split('-')
  return Date.UTC(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]))
}

function isoOf(ms) {
  const date = new Date(ms)
  const month = date.getUTCMonth() + 1
  const day = date.getUTCDate()
  return (
    date.getUTCFullYear() +
    '-' +
    (month < 10 ? '0' + month : month) +
    '-' +
    (day < 10 ? '0' + day : day)
  )
}

/** Понедельник = 0, воскресенье = 6 — как в ключах цикла. */
function weekdayOf(ms) {
  return (new Date(ms).getUTCDay() + 6) % 7
}

/**
 * Чётность недели относительно якорного понедельника.
 *
 * Считается разницей дат, а не номером ISO-недели: разницу на браслете
 * вычислить тривиально, а ISO-нумерация с её правилами про январь — нет,
 * и ошибиться в ней значит показать расписание чужой недели.
 */
export function parityOf(anchorIso, iso) {
  const weeks = Math.floor((toUtc(iso) - toUtc(anchorIso)) / (7 * MS_PER_DAY))
  return ((weeks % 2) + 2) % 2
}

/**
 * Собирает payload той же формы, что приходит с сервера, — чтобы вся логика
 * экранов работала над ним без единой правки.
 *
 * @param {Object} baked содержимое shared/baked.json
 * @param {string} todayIso сегодня, `YYYY-MM-DD`
 * @param {number} [days] ширина окна
 */
export function offlinePayload(baked, todayIso, days) {
  if (!baked || !baked.cycle) {
    return null
  }
  const width = days || WINDOW_DAYS
  const published = {}
  const list = baked.days || []
  for (let i = 0; i < list.length; i += 1) {
    published[list[i].d] = list[i].l
  }

  const start = toUtc(todayIso)
  const out = []
  for (let i = 0; i < width; i += 1) {
    const ms = start + i * MS_PER_DAY
    const iso = isoOf(ms)

    const real = published[iso]
    if (real && real.length) {
      out.push({ d: iso, l: real })
      continue
    }
    if (real) {
      // Вуз опубликовал день и он пуст — это факт, а не пробел в данных,
      // и подставлять сюда шаблон нельзя.
      continue
    }

    const slot = weekdayOf(ms) + '-' + parityOf(baked.anchor, iso)
    const guess = baked.cycle[slot]
    if (guess && guess.length) {
      out.push({ d: iso, l: guess, a: 1 })
    }
  }

  return {
    v: baked.v || 1,
    gid: baked.gid,
    g: baked.g,
    gen: baked.gen,
    src: baked.src,
    stale: false,
    h: 'baked-' + (baked.gen || ''),
    days: out
  }
}

/** Правда ли, что день собран по шаблону, а не опубликован вузом. */
export function isApproximate(payload, iso) {
  if (!payload || !payload.days) {
    return false
  }
  for (let i = 0; i < payload.days.length; i += 1) {
    if (payload.days[i].d === iso) {
      return !!payload.days[i].a
    }
  }
  return false
}
