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
  condition: 'Condition',
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
  sold_price: 'Sold price',
  sold_date: 'Sold date',
  target_price: 'Target price',
  location: 'Location',
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

export default function ImportPage() {
  const qc = useQueryClient()
  const [fileName, setFileName] = useState<string | null>(null)
  const [headers, setHeaders] = useState<string[]>([])
  const [rows, setRows] = useState<Row[]>([])
  const [parseError, setParseError] = useState<string | null>(null)
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [defaults, setDefaults] = useState({
    default_status: 'owned' as ItemStatus,
    default_condition: 'loose' as Condition,
    default_category: 'game' as Category,
    default_platform_id: '' as number | '',
    day_first: false,
    skip_duplicates: true,
    default_region: 'NTSC-U' as 'NTSC-U' | 'PAL' | 'NTSC-J',
  })
  const [problemsOnly, setProblemsOnly] = useState(false)

  const platforms = useQuery({ queryKey: ['platforms'], queryFn: () => api.get<Platform[]>('/platforms') })
  const payload = () => ({
    rows,
    mapping,
    ...defaults,
    default_platform_id: defaults.default_platform_id || null,
  })
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

  const onFile = (file: File) => {
    setParseError(null)
    validate.reset()
    commit.reset()
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
        setFileName(file.name)
        setHeaders(fields)
        setRows(res.data)
        setMapping(await api.post<Record<string, string>>('/import/suggest', { headers: fields }))
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
          A CSV exported from a spreadsheet, another tracker, or VGVault itself. The first line must be column headers;
          one row per item.
        </p>
        <input
          type="file"
          accept=".csv,.tsv,.txt,text/csv"
          onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])}
        />
        <ErrorText error={parseError} />
        {fileName && (
          <p className="muted small">
            {fileName}: {rows.length} rows, {headers.length} columns
          </p>
        )}
      </section>

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
                      {rows[0]?.[h] ? ` (e.g. ${String(rows[0][h]).slice(0, 24)})` : ''}
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
              <span>Condition</span>
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
            <label className="check">
              <input type="checkbox" checked={defaults.day_first} onChange={(e) => setDefault('day_first', e.target.checked)} />
              Dates are day/month/year
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
                  <th>Condition</th>
                  <th>Status</th>
                  <th className="num">Qty</th>
                  <th className="num">Paid</th>
                  <th>Notes</th>
                </tr>
              </thead>
              <tbody>
                {preview.map((r) => (
                  <tr key={r.index} className={r.ok ? '' : 'row-error'}>
                    <td className="muted">{r.index + 2}</td>
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
          <p className="muted small">Row numbers match the spreadsheet (header is row 1).</p>
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
