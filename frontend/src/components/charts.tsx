import { useState } from 'react'
import { fmtNumber, languageName } from '../lib/format'

const dayFmt = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short' })
const weekdayFmt = new Intl.DateTimeFormat(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
const parseDay = (d: string) => new Date(`${d}T00:00:00`)

/**
 * Single-series column chart of new articles per day.
 * One hue (no legend needed; the heading names the series), recessive axis,
 * per-bar hover/focus tooltip, and a visually hidden table for screen readers.
 */
export function DailyBars({ data }: { data: { date: string; count: number }[] }) {
  const [active, setActive] = useState<number | null>(null)
  const width = 560
  const height = 180
  const pad = { top: 16, right: 4, bottom: 2, left: 4 }
  const max = Math.max(1, ...data.map((d) => d.count))
  const innerW = width - pad.left - pad.right
  const innerH = height - pad.top - pad.bottom
  const slot = innerW / Math.max(1, data.length)
  const barW = Math.max(4, slot - 2) // 2px surface gap between adjacent bars
  const y = (v: number) => pad.top + innerH - (v / max) * innerH
  const labelEvery = Math.ceil(data.length / 7)
  const total = data.reduce((s, d) => s + d.count, 0)
  const activeItem = active != null ? data[active] : null

  return (
    <figure className="chart">
      <div className="chart-canvas">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={`New articles per day over ${data.length} days, ${fmtNumber(total)} in total`}
          onMouseLeave={() => setActive(null)}
        >
          <line className="chart-axis" x1={pad.left} x2={width - pad.right} y1={pad.top + innerH} y2={pad.top + innerH} />
          {data.map((d, i) => {
            const x = pad.left + i * slot + (slot - barW) / 2
            const top = y(d.count)
            const h = pad.top + innerH - top
            const r = Math.min(4, h, barW / 2)
            return (
              <g key={d.date}>
                {d.count > 0 && (
                  <path
                    className={`chart-bar ${active === i ? 'is-active' : ''}`}
                    d={`M${x},${pad.top + innerH} V${top + r} Q${x},${top} ${x + r},${top} H${x + barW - r} Q${x + barW},${top} ${x + barW},${top + r} V${pad.top + innerH} Z`}
                  />
                )}
                {/* Hit target is the whole column, larger than the mark */}
                <rect
                  x={pad.left + i * slot}
                  y={pad.top}
                  width={slot}
                  height={innerH}
                  fill="transparent"
                  tabIndex={0}
                  aria-label={`${weekdayFmt.format(parseDay(d.date))}: ${d.count} articles`}
                  onMouseEnter={() => setActive(i)}
                  onFocus={() => setActive(i)}
                  onBlur={() => setActive(null)}
                />
              </g>
            )
          })}
        </svg>
        {activeItem && active != null && (
          <div
            className="chart-tooltip"
            style={{ left: `${((pad.left + active * slot + slot / 2) / width) * 100}%` }}
            aria-hidden="true"
          >
            <strong>{fmtNumber(activeItem.count)}</strong> articles
            <span>{weekdayFmt.format(parseDay(activeItem.date))}</span>
          </div>
        )}
      </div>
      {/* Tick labels in HTML so they stay readable however the SVG scales */}
      <div className="chart-ticks" aria-hidden="true">
        {data.map((d, i) =>
          i % labelEvery === 0 && i + labelEvery <= data.length ? (
            <span key={d.date} style={{ left: `${((pad.left + i * slot + (i === 0 ? 0 : slot / 2)) / width) * 100}%` }}>
              {dayFmt.format(parseDay(d.date))}
            </span>
          ) : null,
        )}
      </div>
      <table className="sr-only">
        <caption>New articles per day</caption>
        <thead>
          <tr>
            <th>Date</th>
            <th>Articles</th>
          </tr>
        </thead>
        <tbody>
          {data.map((d) => (
            <tr key={d.date}>
              <td>{d.date}</td>
              <td>{d.count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  )
}

/** Ranked magnitudes: labelled horizontal bars, values in text ink. */
export function RankedBars({ data }: { data: { language: string; count: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.count))
  return (
    <ul className="ranked">
      {data.map((d) => (
        <li key={d.language}>
          <span className="ranked-label">{languageName(d.language)}</span>
          <span className="ranked-track" aria-hidden="true">
            <span className="ranked-fill" style={{ width: `${(d.count / max) * 100}%` }} />
          </span>
          <span className="ranked-value">{fmtNumber(d.count)}</span>
        </li>
      ))}
    </ul>
  )
}
