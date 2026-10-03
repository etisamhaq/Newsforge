const numberFmt = new Intl.NumberFormat()
const dateFmt = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
const dateTimeFmt = new Intl.DateTimeFormat(undefined, {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})
const timeFmt = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' })
const relFmt = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })

export const fmtNumber = (n: number | null | undefined) => (n == null ? '—' : numberFmt.format(n))

export function fmtDate(iso: string | null | undefined): string {
  return iso ? dateFmt.format(new Date(iso)) : '—'
}

export function fmtDateTime(iso: string | null | undefined): string {
  return iso ? dateTimeFmt.format(new Date(iso)) : '—'
}

export function fmtTime(iso: string): string {
  return timeFmt.format(new Date(iso))
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 31_536_000],
  ['month', 2_592_000],
  ['week', 604_800],
  ['day', 86_400],
  ['hour', 3_600],
  ['minute', 60],
]

export function fmtRelative(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return 'never'
  const seconds = (new Date(iso).getTime() - now) / 1000
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return relFmt.format(Math.round(seconds / size), unit)
  }
  return 'just now'
}

export function fmtDuration(startIso: string | null, endIso: string | null, now = Date.now()): string {
  if (!startIso) return '—'
  const ms = (endIso ? new Date(endIso).getTime() : now) - new Date(startIso).getTime()
  const s = Math.max(0, Math.round(ms / 1000))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ${s % 60}s`
  return `${Math.floor(m / 60)}h ${m % 60}m`
}

export function fmtPercent(value: number): string {
  return `${Math.round(value * 100)}%`
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

const LANGUAGES = new Intl.DisplayNames(undefined, { type: 'language' })
export function languageName(code: string | null | undefined): string {
  if (!code || code === 'unknown') return 'Unknown'
  try {
    return LANGUAGES.of(code) ?? code
  } catch {
    return code
  }
}

export function intervalLabel(minutes: number): string {
  if (minutes % 1440 === 0) return minutes === 1440 ? 'Daily' : `Every ${minutes / 1440} days`
  if (minutes % 60 === 0) return minutes === 60 ? 'Hourly' : `Every ${minutes / 60} hours`
  return `Every ${minutes} min`
}

/** Human wording for the crawl engine's stop reasons. */
export function stopReasonLabel(reason: string | null | undefined): string {
  switch (reason) {
    case 'max_pages':
      return 'Reached the page limit'
    case 'frontier_exhausted':
      return 'No more pages to visit'
    case 'time_budget':
      return 'Ran out of time budget'
    case 'cancelled':
      return 'Cancelled'
    default:
      return reason ?? '—'
  }
}
