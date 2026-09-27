import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  api,
  CATEGORIES,
  CONDITIONS,
  MEDIA_TYPES,
  type Category,
  type Condition,
  type Facets,
  type Group,
  type Item,
  type MediaType,
  type Mover,
  type Movers,
  type Overview,
  type TimePoint,
} from '../api'
import { Legend, TimeChart, BarList, type LineSeries } from '../charts'
import { ErrorText, money } from '../components'
import ItemDialog from './ItemDialog'

interface DashFilters {
  category: Category[]
  brand: string[]
  platform_id: number[]
  era: string[]
  media_type: MediaType[]
  condition: Condition[]
  region: string[]
}

const EMPTY: DashFilters = {
  category: [],
  brand: [],
  platform_id: [],
  era: [],
  media_type: [],
  condition: [],
  region: [],
}
const STORE_KEY = 'vgvault.dashboard'

type Range = '3m' | '1y' | '5y' | 'all'
type GroupBy = 'brand' | 'platform' | 'region' | 'era' | 'media_type' | 'category' | 'condition' | 'genre'

const GROUP_LABELS: Record<GroupBy, string> = {
  brand: 'Brand',
  platform: 'Platform',
  region: 'Region',
  era: 'Era',
  media_type: 'Media',
  category: 'Category',
  condition: 'Condition',
  genre: 'Genre',
}
const MOVER_PERIODS = { '7D': 7, '30D': 30, '90D': 90, '1Y': 365 } as const
type MoverPeriod = keyof typeof MOVER_PERIODS

function loadPrefs() {
  try {
    return JSON.parse(localStorage.getItem(STORE_KEY) ?? '{}')
  } catch {
    return {}
  }
}

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? '' : `${v > 0 ? '+' : ''}${v.toFixed(1)}%`
const signedMoney = (v: number) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${money(Math.abs(v))}`

function Delta({ value, pctValue }: { value: number; pctValue?: number | null }) {
  const dir = value > 0 ? 'up' : value < 0 ? 'down' : ''
  return (
    <span>
      {dir && (
        <span className={`delta-icon ${dir}`} aria-label={dir === 'up' ? 'increase' : 'decrease'}>
          {dir === 'up' ? '▲' : '▼'}{' '}
        </span>
      )}
      {signedMoney(value)}
      {pctValue !== undefined && pctValue !== null && <span className="muted"> ({pct(pctValue)})</span>}
    </span>
  )
}

export default function DashboardPage() {
  const qc = useQueryClient()
  const prefs = loadPrefs()
  const [filters, setFilters] = useState<DashFilters>({ ...EMPTY, ...prefs.filters })
  const [range, setRange] = useState<Range>(prefs.range ?? '1y')
  const [groupBy, setGroupBy] = useState<GroupBy>(prefs.groupBy ?? 'brand')
  const [period, setPeriod] = useState<MoverPeriod>(prefs.period ?? '30D')
  const [minValue, setMinValue] = useState<number>(prefs.minValue ?? 5)
  const [editing, setEditing] = useState<Item | null>(null)

  useEffect(() => {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({ filters, range, groupBy, period, minValue }))
    } catch {
      /* storage unavailable */
    }
  }, [filters, range, groupBy, period, minValue])

  const facets = useQuery({ queryKey: ['facets'], queryFn: () => api.get<Facets>('/collection/facets') })
  const opts = { placeholderData: keepPreviousData }
  const overview = useQuery({
    queryKey: ['analytics', 'overview', filters],
    queryFn: () => api.get<Overview>('/analytics/overview', { ...filters }),
    ...opts,
  })
  const series = useQuery({
    queryKey: ['analytics', 'timeseries', filters, range],
    queryFn: () => api.get<TimePoint[]>('/analytics/timeseries', { ...filters, range }),
    ...opts,
  })
  const groups = useQuery({
    queryKey: ['analytics', 'breakdown', filters, groupBy],
    queryFn: () => api.get<Group[]>('/analytics/breakdown', { ...filters, by: groupBy }),
    ...opts,
  })
  const movers = useQuery({
    queryKey: ['analytics', 'movers', filters, period, minValue],
    queryFn: () =>
      api.get<Movers>('/analytics/movers', { ...filters, days: MOVER_PERIODS[period], min_value: minValue }),
    ...opts,
  })

  const openItem = async (id: number) => setEditing(await api.get<Item>(`/collection/${id}`))
  const update = (patch: Partial<DashFilters>) => setFilters((f) => ({ ...f, ...patch }))
  const active = Object.values(filters).some((v) => v.length > 0)

  // Clicking a bar narrows the whole dashboard to that group.
  const drillDown = (key: string) => {
    const f = facets.data
    switch (groupBy) {
      case 'brand':
        return update({ brand: [key] })
      case 'era':
        return update({ era: [key] })
      case 'region':
        return update({ region: [key] })
      case 'media_type':
        return update({ media_type: [key as MediaType] })
      case 'category':
        return update({ category: [key as Category] })
      case 'condition':
        return update({ condition: [key as Condition] })
      case 'platform': {
        const p = f?.platforms.find((x) => x.name === key)
        return p && update({ platform_id: [p.id] })
      }
    }
  }
  const groupLabel = (key: string) => {
    if (groupBy === 'category') return CATEGORIES[key as Category] ?? key
    if (groupBy === 'condition') return CONDITIONS[key as Condition] ?? key
    if (groupBy === 'media_type') return MEDIA_TYPES[key as MediaType] ?? key
    return key
  }

  const o = overview.data
  const pts = series.data ?? []
  const lines: LineSeries[] = [
    { key: 'value', label: 'Market value', color: 'var(--series-1)', values: pts.map((p) => p.value) },
    { key: 'cost', label: 'Paid', color: 'var(--series-2)', dashed: true, values: pts.map((p) => p.cost) },
  ]
  const f = facets.data

  return (
    <div className="dashboard">
      <div className="page-head" style={{ marginBottom: 0 }}>
        <h1>Dashboard</h1>
        <span className="muted small">Owned items only</span>
      </div>

      <div className="filterbar">
        <MultiSelect
          label="Category"
          options={Object.entries(CATEGORIES).map(([value, label]) => ({ value: value as Category, label }))}
          value={filters.category}
          onChange={(v) => update({ category: v })}
        />
        <MultiSelect
          label="Brand"
          options={(f?.brands ?? []).map((b) => ({ value: b, label: b }))}
          value={filters.brand}
          onChange={(v) => update({ brand: v })}
        />
        <MultiSelect
          label="Platform"
          options={(f?.platforms ?? []).map((p) => ({ value: p.id, label: p.name }))}
          value={filters.platform_id}
          onChange={(v) => update({ platform_id: v })}
        />
        <MultiSelect
          label="Region"
          options={(f?.regions ?? []).map((r) => ({ value: r, label: r }))}
          value={filters.region}
          onChange={(v) => update({ region: v })}
        />
        <MultiSelect
          label="Era"
          options={(f?.eras ?? []).map((e) => ({ value: e, label: e }))}
          value={filters.era}
          onChange={(v) => update({ era: v })}
        />
        <MultiSelect
          label="Media"
          options={Object.entries(MEDIA_TYPES).map(([value, label]) => ({ value: value as MediaType, label }))}
          value={filters.media_type}
          onChange={(v) => update({ media_type: v })}
        />
        <MultiSelect
          label="Condition"
          options={Object.entries(CONDITIONS).map(([value, label]) => ({ value: value as Condition, label }))}
          value={filters.condition}
          onChange={(v) => update({ condition: v })}
        />
        {active && (
          <button className="link" onClick={() => setFilters(EMPTY)}>
            Clear filters
          </button>
        )}
      </div>

      <ErrorText error={overview.error ?? series.error ?? groups.error ?? movers.error} />

      {o && (
        <div className="kpis">
          <div className="kpi">
            <div className="muted small">Market value</div>
            <div className="kpi-value">{money(o.total_value)}</div>
            <div className="kpi-sub muted">
              {o.priced} priced{o.unpriced > 0 && ` · ${o.unpriced} unpriced`}
            </div>
          </div>
          <div className="kpi">
            <div className="muted small">Paid</div>
            <div className="kpi-value">{money(o.cost_basis)}</div>
            <div className="kpi-sub muted">
              {o.quantity} {o.quantity === 1 ? 'item' : 'items'}
            </div>
          </div>
          <div className="kpi" title="Market value minus paid, for items with a purchase price">
            <div className="muted small">Gain / loss</div>
            {o.gain_pct === null ? (
              <>
                <div className="kpi-value">—</div>
                <div className="kpi-sub muted">Add purchase prices to see this</div>
              </>
            ) : (
              <>
                <div className="kpi-value">{signedMoney(o.gain)}</div>
                <div className="kpi-sub">
                  <Delta value={o.gain} pctValue={o.gain_pct} />
                </div>
              </>
            )}
          </div>
          {(['30d', '1y'] as const).map((k) => (
            <div className="kpi" key={k}>
              <div className="muted small">{k === '30d' ? 'Last 30 days' : 'Last 12 months'}</div>
              <div className="kpi-value">{signedMoney(o.changes[k].change)}</div>
              <div className="kpi-sub">
                <Delta value={o.changes[k].change} pctValue={o.changes[k].pct} />
              </div>
            </div>
          ))}
        </div>
      )}

      <section className="panel">
        <div className="panel-head">
          <h2>Value over time</h2>
          <Legend series={lines} />
          <div className="spacer" />
          <div className="seg">
            {(['3m', '1y', '5y', 'all'] as Range[]).map((r) => (
              <button key={r} className={r === range ? 'on' : ''} onClick={() => setRange(r)}>
                {r.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
        <TimeChart dates={pts.map((p) => p.date)} series={lines} />
        <p className="muted small" style={{ margin: '0.5rem 0 0' }}>
          What the items you own now were worth on each date. Paid counts items from their purchase date.
        </p>
      </section>

      <div className="dash-grid">
        <section className="panel">
          <div className="panel-head">
            <h2>Value by</h2>
            <select
              value={groupBy}
              onChange={(e) => setGroupBy(e.target.value as GroupBy)}
              style={{ width: 'auto' }}
              aria-label="Group by"
            >
              {Object.entries(GROUP_LABELS).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </div>
          <BarList
            rows={(groups.data ?? []).map((g) => ({
              key: g.key,
              label: groupLabel(g.key),
              value: g.value,
              detail: `${g.quantity} items · paid ${money(g.cost)}`,
            }))}
            onSelect={groupBy === 'genre' ? undefined : drillDown}
          />
          {groupBy !== 'genre' && <p className="muted small">Click a bar to filter the dashboard.</p>}
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2>Most valuable</h2>
          </div>
          <RankTable
            rows={(o?.top_items ?? []).map((t) => ({ ...t, right: <strong>{money(t.value)}</strong> }))}
            onOpen={openItem}
            empty="No priced items yet."
          />
        </section>
      </div>

      <section className="panel">
        <div className="panel-head">
          <h2>Biggest movers</h2>
          <div className="seg">
            {(Object.keys(MOVER_PERIODS) as MoverPeriod[]).map((p) => (
              <button key={p} className={p === period ? 'on' : ''} onClick={() => setPeriod(p)}>
                {p}
              </button>
            ))}
          </div>
          <div className="spacer" />
          <label className="row small muted">
            Ignore items under
            <input
              type="number"
              min={0}
              value={minValue}
              onChange={(e) => setMinValue(Math.max(0, Number(e.target.value)))}
              style={{ width: 80 }}
            />
          </label>
        </div>
        <div className="dash-grid">
          <div>
            <h3 className="small muted">Gainers</h3>
            <MoverTable rows={movers.data?.gainers ?? []} onOpen={openItem} />
          </div>
          <div>
            <h3 className="small muted">Losers</h3>
            <MoverTable rows={movers.data?.losers ?? []} onOpen={openItem} />
          </div>
        </div>
      </section>

      <p className="muted small">
        Prices come from PriceCharting. Items that aren't linked have no price; find them in the{' '}
        <Link to="/collection" className="link">
          collection
        </Link>
        .
      </p>

      {editing && (
        <ItemDialog
          item={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            qc.invalidateQueries({ queryKey: ['analytics'] })
            qc.invalidateQueries({ queryKey: ['collection'] })
          }}
        />
      )}
    </div>
  )
}

function MoverTable({ rows, onOpen }: { rows: Mover[]; onOpen: (id: number) => void }) {
  return (
    <RankTable
      rows={rows.map((m) => ({
        ...m,
        right: (
          <span title={`${money(m.then)} → ${money(m.price)} per item`}>
            <Delta value={m.value_change} />
            <div className="muted small">{pct(m.pct)}</div>
          </span>
        ),
      }))}
      onOpen={onOpen}
      empty="No price changes in this period."
    />
  )
}

function RankTable({
  rows,
  onOpen,
  empty,
}: {
  rows: {
    item_id: number
    product_id: number
    title: string
    platform: string
    condition: Condition
    has_image: boolean
    quantity: number
    price: number
    right: React.ReactNode
  }[]
  onOpen: (id: number) => void
  empty: string
}) {
  if (rows.length === 0) return <p className="muted">{empty}</p>
  return (
    <table className="table rank-table">
      <tbody>
        {rows.map((r) => (
          <tr key={r.item_id} className="clickable" onClick={() => onOpen(r.item_id)}>
            <td className="title-cell">
              {r.has_image ? (
                <img className="thumb" src={`/api/products/${r.product_id}/image`} alt="" loading="lazy" />
              ) : (
                <span className="thumb" />
              )}
              <span>
                {r.title}
                <div className="muted small">
                  {r.platform} · {CONDITIONS[r.condition]}
                  {r.quantity > 1 && ` · ×${r.quantity}`} · {money(r.price)}
                </div>
              </span>
            </td>
            <td className="num">{r.right}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function MultiSelect<T extends string | number>({
  label,
  options,
  value,
  onChange,
}: {
  label: string
  options: { value: T; label: string }[]
  value: T[]
  onChange: (v: T[]) => void
}) {
  if (options.length === 0) return null
  return (
    <details className={`dropdown ${value.length ? 'active' : ''}`}>
      <summary>
        {label}
        {value.length > 0 && <span className="badge">{value.length}</span>} ▾
      </summary>
      <div className="menu">
        {options.map((o) => (
          <label key={String(o.value)}>
            <input
              type="checkbox"
              checked={value.includes(o.value)}
              onChange={(e) =>
                onChange(e.target.checked ? [...value, o.value] : value.filter((v) => v !== o.value))
              }
            />
            {o.label}
          </label>
        ))}
        {value.length > 0 && (
          <button className="link small" onClick={() => onChange([])}>
            clear
          </button>
        )}
      </div>
    </details>
  )
}

