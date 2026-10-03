import { fmtDuration, fmtRelative, hostOf, intervalLabel, stopReasonLabel } from '../lib/format'

describe('format helpers', () => {
  const now = Date.parse('2026-10-04T12:00:00Z')

  it('formats relative times', () => {
    expect(fmtRelative('2026-10-04T11:00:00Z', now)).toBe('1 hour ago')
    expect(fmtRelative('2026-10-04T11:59:50Z', now)).toBe('just now')
    expect(fmtRelative(null, now)).toBe('never')
  })

  it('formats durations', () => {
    expect(fmtDuration('2026-10-04T11:59:15Z', '2026-10-04T12:00:00Z')).toBe('45s')
    expect(fmtDuration('2026-10-04T11:55:00Z', '2026-10-04T12:00:30Z')).toBe('5m 30s')
    expect(fmtDuration(null, null)).toBe('—')
  })

  it('labels schedules and stop reasons in plain words', () => {
    expect(intervalLabel(60)).toBe('Hourly')
    expect(intervalLabel(1440)).toBe('Daily')
    expect(intervalLabel(30)).toBe('Every 30 min')
    expect(stopReasonLabel('max_pages')).toBe('Reached the page limit')
    expect(hostOf('https://www.bbc.com/news')).toBe('bbc.com')
  })
})
