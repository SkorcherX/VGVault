import { useMemo, useRef, useState } from 'react'
import { money } from './components'

export interface LineSeries {
  key: string
  label: string
  color: string
  dashed?: boolean
  values: number[]
}

const W = 800
const H = 260
const PAD = { l: 64, r: 72, t: 12, b: 26 }

/** Compact money axis label: $1.2k, $3.4M. */
export function shortMoney(v: number) {
  const a = Math.abs(v)
  if (a >= 1e6) return `$${(v / 1e6).toFixed(1)}M`
  if (a >= 1e4) return `$${Math.round(v / 1e3)}k`
  if (a >= 1e3) return `$${(v / 1e3).toFixed(1)}k`
  return `$${Math.round(v)}`
}

export function niceTicks(min: number, max: number, count = 4): number[] {
  if (max <= min) return [min]
  const raw = (max - min) / count
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw
  // Round the top up to a whole step so the data always fits under the highest gridline.
  const top = Math.ceil(max / step) * step
  const ticks = []
  for (let v = Math.floor(min / step) * step; v <= top + step * 0.001; v += step) ticks.push(v)
  return ticks
}

/** Multi-series line chart on one money axis, with crosshair tooltip and end labels. */
export function TimeChart({ dates, series }: { dates: string[]; series: LineSeries[] }) {
  const wrap = useRef<HTMLDivElement>(null)
  const [hover, setHover] = useState<number | null>(null)

  const geo = useMemo(() => {
    const all = series.flatMap((s) => s.values)
    const ticks = niceTicks(0, Math.max(1, ...all))
    const maxV = ticks[ticks.length - 1]
    const x = (i: number) => PAD.l + (dates.length > 1 ? i / (dates.length - 1) : 0.5) * (W - PAD.l - PAD.r)
    const y = (v: number) => PAD.t + (1 - v / maxV) * (H - PAD.t - PAD.b)
    return { ticks, x, y }
  }, [dates, series])

  if (dates.length === 0) return <p className="muted">No data yet.</p>
  const { ticks, x, y } = geo
  const fmtDate = (d: string, opts: Intl.DateTimeFormatOptions) =>
    new Date(`${d}T00:00:00`).toLocaleDateString(undefined, opts)

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * W
    const i = Math.round(((px - PAD.l) / (W - PAD.l - PAD.r)) * (dates.length - 1))
    setHover(Math.max(0, Math.min(dates.length - 1, i)))
  }

  // End labels: keep them from colliding by nudging apart vertically.
  const ends = series
    .map((s) => ({ s, y: y(s.values[s.values.length - 1] ?? 0) }))
    .sort((a, b) => a.y - b.y)
  for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 14) ends[i].y = ends[i - 1].y + 14

  const tipLeft = hover !== null ? (x(hover) / W) * (wrap.current?.clientWidth ?? W) : 0
  const tipOnLeft = hover !== null && hover > dates.length / 2

  return (
    <div className="timechart" ref={wrap}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`${series.map((s) => s.label).join(' and ')} over time`}
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      >
        {ticks.map((v) => (
          <g key={v}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} className="grid" />
            <text x={PAD.l - 8} y={y(v) + 4} textAnchor="end" className="axis">
              {shortMoney(v)}
            </text>
          </g>
        ))}
        {[0, Math.floor((dates.length - 1) / 2), dates.length - 1]
          .filter((i, idx, arr) => arr.indexOf(i) === idx)
          .map((i) => (
            <text
              key={i}
              x={x(i)}
              y={H - 6}
              textAnchor={i === 0 ? 'start' : i === dates.length - 1 ? 'end' : 'middle'}
              className="axis"
            >
              {fmtDate(dates[i], { year: 'numeric', month: 'short' })}
            </text>
          ))}
        {series.map((s) => (
          <path
            key={s.key}
            d={s.values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('')}
            fill="none"
            stroke={s.color}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeDasharray={s.dashed ? '6 4' : undefined}
          />
        ))}
        {ends.map(({ s, y: ly }) => (
          <text key={s.key} x={W - PAD.r + 6} y={ly + 4} className="end-label">
            {shortMoney(s.values[s.values.length - 1] ?? 0)}
          </text>
        ))}
        {hover !== null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={H - PAD.b} className="grid" />
            {series.map((s) => (
              <circle
                key={s.key}
                cx={x(hover)}
                cy={y(s.values[hover])}
                r={4}
                fill={s.color}
                stroke="var(--surface)"
                strokeWidth={2}
              />
            ))}
          </g>
        )}
      </svg>
      {hover !== null && (
        <div
          className="chart-tip"
          style={{
            top: 8,
            left: tipOnLeft ? undefined : tipLeft + 12,
            right: tipOnLeft ? (wrap.current?.clientWidth ?? W) - tipLeft + 12 : undefined,
          }}
        >
          <div className="muted">{fmtDate(dates[hover], { year: 'numeric', month: 'short', day: 'numeric' })}</div>
          {series.map((s) => (
            <div key={s.key}>
              <span className="swatch" style={{ background: s.color }} />
              {s.label}: <strong>{money(s.values[hover])}</strong>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function Legend({ series }: { series: Pick<LineSeries, 'key' | 'label' | 'color' | 'dashed'>[] }) {
  return (
    <div className="legend">
      {series.map((s) => (
        <span key={s.key}>
          <span className={`swatch ${s.dashed ? 'dashed' : ''}`} style={{ background: s.color }} />
          {s.label}
        </span>
      ))}
    </div>
  )
}

/** Horizontal single-hue bars (magnitude), value labels at the end, click to filter. */
export function BarList({
  rows,
  onSelect,
  max = 12,
}: {
  rows: { key: string; label: string; value: number; detail: string }[]
  onSelect?: (key: string) => void
  max?: number
}) {
  const shown = rows.slice(0, max)
  const rest = rows.slice(max)
  const other = rest.length
    ? [{ key: '__other', label: `Other (${rest.length})`, value: rest.reduce((a, r) => a + r.value, 0), detail: '' }]
    : []
  const all = [...shown, ...other]
  const top = Math.max(1, ...all.map((r) => r.value))
  if (rows.length === 0) return <p className="muted">No data.</p>
  return (
    <div className="bars" role="list">
      {all.map((r) => (
        <button
          key={r.key}
          type="button"
          role="listitem"
          className="bar-row"
          title={r.detail}
          disabled={r.key === '__other' || !onSelect}
          onClick={() => onSelect?.(r.key)}
        >
          <span className="bar-label">{r.label}</span>
          <span className="bar-track">
            <span className="bar-fill" style={{ width: `${(r.value / top) * 100}%`, display: 'block' }} />
          </span>
          <span className="bar-value">{money(r.value)}</span>
        </button>
      ))}
    </div>
  )
}
