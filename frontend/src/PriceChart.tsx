import { useMemo, useState } from 'react'
import { CONDITIONS, type Condition, type Snapshot } from './api'
import { money } from './components'

const RANGES = { '1Y': 365, '5Y': 365 * 5, All: Infinity } as const
type Range = keyof typeof RANGES

const W = 560
const H = 180
const PAD = { l: 56, r: 12, t: 10, b: 22 }

/** Minimal dependency-free line chart of one condition's price history. */
export default function PriceChart({
  snapshots,
  condition,
  purchasePrice,
}: {
  snapshots: Snapshot[]
  condition: Condition
  purchasePrice?: string | null
}) {
  const [cond, setCond] = useState<Condition>(condition)
  const [range, setRange] = useState<Range>('5Y')
  const [hover, setHover] = useState<number | null>(null)

  const available = useMemo(
    () => (Object.keys(CONDITIONS) as Condition[]).filter((c) => snapshots.some((s) => s[c] !== null)),
    [snapshots],
  )

  const points = useMemo(() => {
    const cutoff = Date.now() - RANGES[range] * 86_400_000
    return snapshots
      .map((s) => ({ t: new Date(s.captured_on).getTime(), v: s[cond] === null ? null : Number(s[cond]) }))
      .filter((p): p is { t: number; v: number } => p.v !== null && p.t >= cutoff)
  }, [snapshots, cond, range])

  if (available.length === 0) return <p className="muted">No price history yet.</p>

  const paid = purchasePrice ? Number(purchasePrice) : null
  const values = points.map((p) => p.v).concat(paid ? [paid] : [])
  const minV = Math.min(...values) * 0.95
  const maxV = Math.max(...values) * 1.05 || 1
  const t0 = points[0]?.t ?? 0
  const t1 = points[points.length - 1]?.t ?? 1
  const x = (t: number) => PAD.l + ((t - t0) / (t1 - t0 || 1)) * (W - PAD.l - PAD.r)
  const y = (v: number) => PAD.t + (1 - (v - minV) / (maxV - minV || 1)) * (H - PAD.t - PAD.b)
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join('')
  const ticks = [minV, (minV + maxV) / 2, maxV]
  const hp = hover !== null ? points[hover] : null

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (points.length === 0) return
    const rect = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * W
    let best = 0
    for (let i = 1; i < points.length; i++) {
      if (Math.abs(x(points[i].t) - px) < Math.abs(x(points[best].t) - px)) best = i
    }
    setHover(best)
  }

  return (
    <div className="price-chart">
      <div className="row">
        <div className="seg">
          {available.map((c) => (
            <button key={c} className={c === cond ? 'on' : ''} onClick={() => setCond(c)} type="button">
              {CONDITIONS[c]}
            </button>
          ))}
        </div>
        <div className="spacer" />
        <div className="seg">
          {(Object.keys(RANGES) as Range[]).map((r) => (
            <button key={r} className={r === range ? 'on' : ''} onClick={() => setRange(r)} type="button">
              {r}
            </button>
          ))}
        </div>
      </div>
      {points.length < 2 ? (
        <p className="muted">Not enough data for this range.</p>
      ) : (
        <svg
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={`${CONDITIONS[cond]} price history`}
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
        >
          {ticks.map((v) => (
            <g key={v}>
              <line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} className="grid" />
              <text x={PAD.l - 6} y={y(v) + 4} textAnchor="end" className="axis">
                {money(v)}
              </text>
            </g>
          ))}
          <text x={PAD.l} y={H - 4} className="axis">
            {new Date(t0).toLocaleDateString(undefined, { year: 'numeric', month: 'short' })}
          </text>
          <text x={W - PAD.r} y={H - 4} textAnchor="end" className="axis">
            {new Date(t1).toLocaleDateString(undefined, { year: 'numeric', month: 'short' })}
          </text>
          {paid !== null && (
            <g>
              <line x1={PAD.l} x2={W - PAD.r} y1={y(paid)} y2={y(paid)} className="paid" />
              <text x={W - PAD.r} y={y(paid) - 4} textAnchor="end" className="axis">
                paid
              </text>
            </g>
          )}
          <path d={path} className="line" />
          {hp && (
            <g>
              <line x1={x(hp.t)} x2={x(hp.t)} y1={PAD.t} y2={H - PAD.b} className="grid" />
              <circle cx={x(hp.t)} cy={y(hp.v)} r={4} className="dot" />
              <text
                x={Math.min(x(hp.t) + 8, W - 120)}
                y={PAD.t + 14}
                className="tip"
              >{`${new Date(hp.t).toLocaleDateString()} · ${money(hp.v)}`}</text>
            </g>
          )}
        </svg>
      )}
    </div>
  )
}
