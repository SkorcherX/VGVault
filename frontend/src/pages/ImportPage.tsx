import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import Papa from 'papaparse'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  api,
  CATEGORIES,
  CONDITIONS,
  STATUSES,
  type Category,
  type Condition,
  type ItemStatus,
  type Platform,
} from '../api'
import { ErrorText, money } from '../components'

type Row = Record<string, string>

const FIELD_LABELS: Record<string, string> = {
  title: 'Title *',
  platform: 'Platform *',
  condition: 'Ownership',
  status: 'Status (owned / wishlist / sold)',
  quantity: 'Quantity',
  purchase_price: 'Purchase price',
  purchase_date: 'Purchase date',
  category: 'Category',
  region: 'Region',
  has_item: 'Has game/cart',
  has_box: 'Has box',
  has_manual: 'Has manual',
  has_inserts: 'Has inserts',
  grade: 'Grade',
  item_rating: 'Condition: game/cart (1-10)',
  box_rating: 'Condition: box (1-10)',
  manual_rating: 'Condition: manual (1-10)',
  sold_price: 'Sold price',
  sold_date: 'Sold date',
  target_price: 'Target price',
  location: 'Location',
  acquired_from: 'Bought from (store, eBay…)',
  tags: 'Tags',
  notes: 'Notes',
  pricecharting_url: 'PriceCharting URL',
  upc: 'UPC / barcode',
}

interface ValidateRow {
  index: number
  ok: boolean
  errors: string[]
  warnings: string[]
  title: string | null
  platform: string | null
  condition: Condition | null
  status: ItemStatus | null
  quantity: number | null
  purchase_price: string | null
  existing_product: boolean
  duplicate: boolean
}

interface ValidateResult {
  rows: ValidateRow[]
  summary: { total: number; ok: number; errors: number; duplicates: number; new_products: number }
}

interface CommitResult {
  created_items: number
  created_products: number
  skipped: number
  failed: number
  unlinked: number
}

interface Sheet {
  name: string
  hidden: boolean
  header_row: number | null
  headers: string[]
  rows: Row[]
  row_numbers: number[]
}

/** Sheets with the same columns (ignoring link and sheet-name columns) import together. */
const layoutOf = (s: Sheet) => s.headers.filter((h) => !h.endsWith(' (link)') && h !== 'Sheet name').join('|')

const isExcel = (f: File) => /\.(xlsx|xlsm)$/i.test(f.name)

export default function ImportPage() {
  const qc = useQueryClient()
  const [fileName, setFileName] = useState<string | null>(null)
  const [headers, setHeaders] = useState<string[]>([])
  const [rows, setRows] = useState<Row[]>([])
  const [parseError, setParseError] = useState<string | null>(null)
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [sheets, setSheets] = useState<Sheet[] | null>(null)
  const [layout, setLayout] = useState<string | null>(null)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [reading, setReading] = useState(false)
  // Where each row came from, for messages: "NES row 5" (workbook) or "row 5" (CSV, header on row 1)
  const [rowLabels, setRowLabels] = useState<string[]>([])
  const [defaults, setDefaults] = useState({
    default_status: 'owned' as ItemStatus,
    default_condition: 'loose' as Condition,
    default_category: 'game' as Category,
    default_platform_id: '' as number | '',
    date_order: 'auto' as 'auto' | 'dmy' | 'mdy',
    skip_duplicates: true,
    default_region: 'NTSC-U' as 'NTSC-U' | 'PAL' | 'NTSC-J',
    prices_per_row: false,
  })
  const [problemsOnly, setProblemsOnly] = useState(false)

  const platforms = useQuery({ queryKey: ['platforms'], queryFn: () => api.get<Platform[]>('/platforms') })
  const payload = () => {
    const { date_order, ...rest } = defaults
    return {
      rows,
      mapping,
      ...rest,
      day_first: date_order === 'auto' ? null : date_order === 'dmy',
      default_platform_id: defaults.default_platform_id || null,
    }
  }
  const validate = useMutation({ mutationFn: () => api.post<ValidateResult>('/import/validate', payload()) })
  const commit = useMutation({
    mutationFn: () => api.post<CommitResult>('/import/commit', payload()),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['collection'] })
      qc.invalidateQueries({ queryKey: ['facets'] })
      qc.invalidateQueries({ queryKey: ['summary'] })
      qc.invalidateQueries({ queryKey: ['analytics'] })
      qc.invalidateQueries({ queryKey: ['autolink'] })
    },
  })

  /** Load parsed rows into the mapper, with a mapping suggestion based on headers and cell values. */
  const loadRows = async (fields: string[], data: Row[]) => {
    validate.reset()
    commit.reset()
    setHeaders(fields)
    setRows(data)
    setMapping(await api.post<Record<string, string>>('/import/suggest', { headers: fields, rows: data.slice(0, 300) }))
  }

  const pickLayout = (key: string, all: Sheet[]) => {
    setLayout(key)
    // Hidden tabs are often templates or scratch space: offer them, but don't tick them.
    setPicked(new Set(all.filter((s) => layoutOf(s) === key && s.rows.length > 0 && !s.hidden).map((s) => s.name)))
  }

  const applySheets = () => {
    const chosen = (sheets ?? []).filter((s) => picked.has(s.name))
    const fields = [...new Set(chosen.flatMap((s) => s.headers))].filter((h) => h !== 'Sheet name')
    setRowLabels(chosen.flatMap((s) => s.row_numbers.map((n) => `${s.name} row ${n}`)))
    loadRows([...fields, 'Sheet name'], chosen.flatMap((s) => s.rows))
  }

  const onFile = async (file: File) => {
    setParseError(null)
    setSheets(null)
    setHeaders([])
    setRows([])
    validate.reset()
    commit.reset()
    setFileName(file.name)
    if (isExcel(file)) {
      setReading(true)
      try {
        const form = new FormData()
        form.append('file', file)
        const res = await fetch('/api/import/workbook', { method: 'POST', body: form, credentials: 'same-origin' })
        const data = await res.json()
        if (!res.ok) throw new Error(data.detail ?? res.statusText)
        const all: Sheet[] = data.sheets
        const withRows = all.filter((s) => s.rows.length > 0)
        if (withRows.length === 0) throw new Error('No sheets with a recognizable header row and data.')
        setSheets(all)
        // Start with the layout covering the most rows (e.g. all the per-platform game tabs).
        const counts = new Map<string, number>()
        for (const s of withRows) counts.set(layoutOf(s), (counts.get(layoutOf(s)) ?? 0) + s.rows.length)
        pickLayout([...counts.entries()].sort((a, b) => b[1] - a[1])[0][0], all)
      } catch (e) {
        setParseError(e instanceof Error ? e.message : String(e))
      } finally {
        setReading(false)
      }
      return
    }
    Papa.parse<Row>(file, {
      header: true,
      skipEmptyLines: 'greedy',
      transformHeader: (h) => h.trim(),
      complete: async (res) => {
        const fields = (res.meta.fields ?? []).filter(Boolean)
        if (fields.length === 0 || res.data.length === 0) {
          setParseError('No rows found. The first line must be column headers.')
          return
        }
        // A trailing comma on every line (GamEye exports) lands in __parsed_extra; drop it.
        const data = res.data.map((row) => {
          const { __parsed_extra, ...rest } = row as Row & { __parsed_extra?: unknown }
          void __parsed_extra
          return rest
        })
        setRowLabels(data.map((_, i) => `row ${i + 2}`))
        loadRows(fields, data)
      },
      error: (err) => setParseError(err.message),
    })
  }

  const setField = (field: string, column: string) => {
    validate.reset()
    setMapping((m) => {
      const next = { ...m }
      if (column) next[field] = column
      else delete next[field]
      return next
    })
  }
  const setDefault = <K extends keyof typeof defaults>(k: K, v: (typeof defaults)[K]) => {
    validate.reset()
    setDefaults((d) => ({ ...d, [k]: v }))
  }

  const preview = useMemo(() => {
    const all = validate.data?.rows ?? []
    return (problemsOnly ? all.filter((r) => !r.ok || r.warnings.length) : all).slice(0, 300)
  }, [validate.data, problemsOnly])

  const v = validate.data?.summary
  const toImport = v ? v.ok - (defaults.skip_duplicates ? v.duplicates : 0) : 0
  const canCheck = rows.length > 0 && !!mapping.title && (!!mapping.platform || !!defaults.default_platform_id || !!mapping.pricecharting_url)

  return (
    <div className="page import-page">
      <div className="page-head">
        <h1>Import collection</h1>
        <div className="spacer" />
        <Link to="/collection" className="link">
          Back to collection
        </Link>
      </div>

      <section className="card">
        <h2>1. Choose a file</h2>
        <p className="muted small">
          An Excel workbook (.xlsx) or CSV from a spreadsheet, another tracker, or VGVault itself: one row per item.
          Workbooks can have a tab per platform and a header row further down; hyperlinks to PriceCharting are picked
          up automatically.
        </p>
        <input
          type="file"
          accept=".xlsx,.xlsm,.csv,.tsv,.txt,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])}
        />
        {reading && <p className="muted small">Reading workbook…</p>}
        <ErrorText error={parseError} />
        {fileName && rows.length > 0 && (
          <p className="muted small">
            {fileName}: {rows.length} rows, {headers.length} columns
          </p>
        )}
      </section>

      {sheets && (
        <SheetPicker
          sheets={sheets}
          layout={layout}
          picked={picked}
          loaded={rows.length > 0}
          onLayout={(key) => {
            pickLayout(key, sheets)
            setHeaders([])
            setRows([])
            validate.reset()
          }}
          onToggle={(name) => {
            const next = new Set(picked)
            if (next.has(name)) next.delete(name)
            else next.add(name)
            setPicked(next)
          }}
          onUse={applySheets}
        />
      )}

      {headers.length > 0 && (
        <section className="card">
          <h2>2. Match columns</h2>
          <p className="muted small">
            Columns were matched by name where possible. Fields left blank use the defaults. PAL and Japanese releases
            are separate platforms: a Region column, or words like "PAL" or "Japanese" in the platform name, pick them.
          </p>
          <div className="map-grid">
            {Object.entries(FIELD_LABELS).map(([field, label]) => (
              <label key={field} className="field">
                <span>{label}</span>
                <select value={mapping[field] ?? ''} onChange={(e) => setField(field, e.target.value)}>
                  <option value="">—</option>
                  {headers.map((h) => (
                    <option key={h} value={h}>
                      {h}
                      {example(rows, h) ? ` (e.g. ${example(rows, h)})` : ''}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
          <h3 className="small muted">Defaults</h3>
          <div className="map-grid">
            <label className="field">
              <span>Status</span>
              <select value={defaults.default_status} onChange={(e) => setDefault('default_status', e.target.value as ItemStatus)}>
                {Object.entries(STATUSES).map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Ownership</span>
              <select
                value={defaults.default_condition}
                onChange={(e) => setDefault('default_condition', e.target.value as Condition)}
              >
                {Object.entries(CONDITIONS).map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Category</span>
              <select
                value={defaults.default_category}
                onChange={(e) => setDefault('default_category', e.target.value as Category)}
              >
                {Object.entries(CATEGORIES).map(([k, l]) => (
                  <option key={k} value={k}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Region when not stated</span>
              <select
                value={defaults.default_region}
                onChange={(e) => setDefault('default_region', e.target.value as typeof defaults.default_region)}
              >
                <option value="NTSC-U">NTSC-U (North America)</option>
                <option value="PAL">PAL (Europe / Australia)</option>
                <option value="NTSC-J">NTSC-J (Japan)</option>
              </select>
            </label>
            <label className="field">
              <span>Platform (when missing or unrecognized)</span>
              <select
                value={defaults.default_platform_id}
                onChange={(e) => setDefault('default_platform_id', e.target.value ? Number(e.target.value) : '')}
              >
                <option value="">None: flag the row</option>
                {platforms.data?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="row">
            <label className="row small">
              Prices paid are
              <select
                value={defaults.prices_per_row ? 'row' : 'copy'}
                onChange={(e) => setDefault('prices_per_row', e.target.value === 'row')}
                style={{ width: 'auto' }}
              >
                <option value="copy">per copy</option>
                <option value="row">the total for the row</option>
              </select>
            </label>
            <label className="row small">
              Dates
              <select
                value={defaults.date_order}
                onChange={(e) => setDefault('date_order', e.target.value as typeof defaults.date_order)}
                style={{ width: 'auto' }}
              >
                <option value="auto">Detect automatically</option>
                <option value="dmy">Day / month / year</option>
                <option value="mdy">Month / day / year</option>
              </select>
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={defaults.skip_duplicates}
                onChange={(e) => setDefault('skip_duplicates', e.target.checked)}
              />
              Skip items already in my collection
            </label>
            <div className="spacer" />
            <button disabled={!canCheck || validate.isPending} onClick={() => validate.mutate()}>
              {validate.isPending ? 'Checking…' : 'Check rows'}
            </button>
          </div>
          {!canCheck && <p className="muted small">Map at least the title and platform columns (or pick a default platform).</p>}
          <ErrorText error={validate.error} />
        </section>
      )}

      {v && (
        <section className="card">
          <h2>3. Review</h2>
          <div className="row" style={{ marginBottom: '0.75rem' }}>
            <span className="pill ok">{v.ok} ready</span>
            {v.errors > 0 && <span className="pill failed">{v.errors} with errors (skipped)</span>}
            {v.duplicates > 0 && (
              <span className="pill">
                {v.duplicates} already owned{defaults.skip_duplicates ? ' (skipped)' : ''}
              </span>
            )}
            <span className="pill">{v.new_products} new catalog entries</span>
            <div className="spacer" />
            <label className="check small">
              <input type="checkbox" checked={problemsOnly} onChange={(e) => setProblemsOnly(e.target.checked)} />
              Only rows with issues
            </label>
          </div>
          <div className="table-wrap" style={{ maxHeight: 420, overflowY: 'auto' }}>
            <table className="table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Title</th>
                  <th>Platform</th>
                  <th>Ownership</th>
                  <th>Status</th>
                  <th className="num">Qty</th>
                  <th className="num">Paid</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {preview.map((r) => (
                  <tr key={r.index} className={r.ok ? '' : 'row-error'}>
                    <td className="muted">{rowLabels[r.index] ?? r.index + 2}</td>
                    <td>{r.title || <span className="muted">—</span>}</td>
                    <td>{r.platform ?? <span className="muted">—</span>}</td>
                    <td>{r.condition ? CONDITIONS[r.condition] : ''}</td>
                    <td>{r.status ? STATUSES[r.status] : ''}</td>
                    <td className="num">{r.quantity}</td>
                    <td className="num">{r.purchase_price ? money(r.purchase_price) : ''}</td>
                    <td className="wrap small">
                      {r.errors.map((e) => (
                        <div key={e} className="error" style={{ margin: 0 }}>
                          ✕ {e}
                        </div>
                      ))}
                      {r.warnings.map((w) => (
                        <div key={w} className="muted">
                          ⚠ {w}
                        </div>
                      ))}
                      {r.ok && !r.warnings.length && (r.existing_product ? <span className="muted">in catalog</span> : '')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {(validate.data?.rows.length ?? 0) > 300 && <p className="muted small">Showing the first 300 rows.</p>}
          <p className="muted small">Row numbers match the spreadsheet.</p>
          <div className="row">
            <button disabled={toImport === 0 || commit.isPending || commit.isSuccess} onClick={() => commit.mutate()}>
              {commit.isPending ? 'Importing…' : `Import ${toImport} item${toImport === 1 ? '' : 's'}`}
            </button>
          </div>
          <ErrorText error={commit.error} />
        </section>
      )}

      {commit.data && (
        <section className="card">
          <h2>Done</h2>
          <p>
            Added <strong>{commit.data.created_items}</strong> items ({commit.data.created_products} new catalog entries)
            {commit.data.skipped > 0 && `, skipped ${commit.data.skipped} already owned`}
            {commit.data.failed > 0 && `, ${commit.data.failed} rows had errors`}.
          </p>
        </section>
      )}

      <AutoLinkPanel />
    </div>
  )
}

interface AutoLinkStatus {
  running: boolean
  busy: boolean
  total: number
  done: number
  linked: number
  current: string | null
  unmatched: { product_id: number; title: string; platform: string; reason?: string }[]
  error: string | null
  unlinked: number
}

export function AutoLinkPanel() {
  const qc = useQueryClient()
  const status = useQuery({
    queryKey: ['autolink'],
    queryFn: () => api.get<AutoLinkStatus>('/import/autolink'),
    refetchInterval: (q) => (q.state.data?.running ? 2000 : false),
  })
  const start = useMutation({
    mutationFn: () => api.post('/import/autolink'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['autolink'] }),
  })
  const cancel = useMutation({
    mutationFn: () => api.post('/import/autolink/cancel'),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['autolink'] }),
  })
  const s = status.data
  if (!s || (s.unlinked === 0 && !s.running && s.total === 0)) return null
  const finished = !s.running && s.total > 0

  return (
    <section className="card">
      <h2>Link to PriceCharting</h2>
      <p className="muted small">
        {s.unlinked} item{s.unlinked === 1 ? '' : 's'} in your collection {s.unlinked === 1 ? 'has' : 'have'} no price
        source. Auto-link searches PriceCharting for each one and links it only when there's exactly one exact title match
        on the same platform. It runs in the background at the polite scraping rate (about 10–20 seconds per item), so
        you can leave this page.
      </p>
      {s.running ? (
        <>
          <div className="row">
            <strong>
              {s.done} / {s.total}
            </strong>
            <span className="muted">
              {s.linked} linked{s.current && ` · now: ${s.current}`}
            </span>
            <div className="spacer" />
            <button className="ghost danger" onClick={() => cancel.mutate()}>
              Cancel
            </button>
          </div>
          <div className="bar">
            <div style={{ width: `${(s.done / Math.max(1, s.total)) * 100}%` }} />
          </div>
        </>
      ) : (
        <div className="row">
          <button disabled={s.busy || s.unlinked === 0 || start.isPending} onClick={() => start.mutate()}>
            Auto-link {s.unlinked} item{s.unlinked === 1 ? '' : 's'}
          </button>
          {s.busy && <span className="muted small">Another user's auto-link is running; try again shortly.</span>}
        </div>
      )}
      <ErrorText error={start.error ?? cancel.error ?? s.error} />
      {finished && (
        <p>
          Linked <strong>{s.linked}</strong> of {s.total}.
        </p>
      )}
      {s.unmatched.length > 0 && (
        <details>
          <summary className="link">{s.unmatched.length} need linking by hand</summary>
          <p className="muted small">
            Open each one from the collection and use "Link" with its PriceCharting URL.
          </p>
          <ul className="small">
            {s.unmatched.map((u) => (
              <li key={u.product_id}>
                {u.title} <span className="muted">· {u.platform}{u.reason && ` · ${u.reason}`}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}

function example(rows: Row[], column: string): string {
  const row = rows.find((r) => r[column])
  return row ? String(row[column]).slice(0, 28) : ''
}

function SheetPicker({
  sheets,
  layout,
  picked,
  loaded,
  onLayout,
  onToggle,
  onUse,
}: {
  sheets: Sheet[]
  layout: string | null
  picked: Set<string>
  loaded: boolean
  onLayout: (key: string) => void
  onToggle: (name: string) => void
  onUse: () => void
}) {
  const groups = useMemo(() => {
    const map = new Map<string, Sheet[]>()
    for (const s of sheets.filter((s) => s.rows.length > 0)) {
      const key = layoutOf(s)
      map.set(key, [...(map.get(key) ?? []), s])
    }
    return [...map.entries()].sort((a, b) => b[1].length - a[1].length)
  }, [sheets])
  const skipped = sheets.filter((s) => s.rows.length === 0)
  const count = sheets.filter((s) => picked.has(s.name)).reduce((n, s) => n + s.rows.length, 0)

  return (
    <section className="card">
      <h2>Choose tabs</h2>
      <p className="muted small">
        Tabs with the same columns import together. Import a different layout (like a separate consoles tab) as a
        second pass afterwards.
      </p>
      {groups.map(([key, group]) => (
        <div key={key} className={`sheet-group ${key === layout ? 'on' : ''}`}>
          <label className="check">
            <input type="radio" checked={key === layout} onChange={() => onLayout(key)} />
            <strong>
              {group.length} tab{group.length === 1 ? '' : 's'}, {group.reduce((n, s) => n + s.rows.length, 0)} rows
            </strong>
            <span className="muted small">
              {group[0].headers.filter((h) => h !== 'Sheet name').slice(0, 8).join(', ')}
              {group[0].headers.length > 9 ? ', …' : ''}
            </span>
          </label>
          {key === layout && (
            <div className="sheet-list">
              {group.map((s) => (
                <label key={s.name} className="check small">
                  <input type="checkbox" checked={picked.has(s.name)} onChange={() => onToggle(s.name)} />
                  {s.name} <span className="muted">({s.rows.length})</span>
                  {s.hidden && <span className="tag">hidden</span>}
                </label>
              ))}
            </div>
          )}
        </div>
      ))}
      {skipped.length > 0 && (
        <p className="muted small">Skipped (no header row or no data): {skipped.map((s) => s.name).join(', ')}</p>
      )}
      <div className="row">
        <button disabled={picked.size === 0} onClick={onUse}>
          {loaded ? 'Reload' : 'Use'} {picked.size} tab{picked.size === 1 ? '' : 's'} ({count} rows)
        </button>
      </div>
    </section>
  )
}
