import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  api,
  toQuery,
  CATEGORIES,
  CONDITIONS,
  MEDIA_TYPES,
  STATUSES,
  type Category,
  type Condition,
  type Facets,
  type Item,
  type ItemStatus,
  type MediaType,
  type Summary,
} from '../api'
import { CheckList, ErrorText, money } from '../components'
import ItemDialog from './ItemDialog'

interface Filters {
  q: string
  status: ItemStatus[]
  category: Category[]
  platform_id: number[]
  brand: string[]
  era: string[]
  media_type: MediaType[]
  condition: Condition[]
  region: string[]
  tag: string
  location: string
}

const EMPTY_FILTERS: Filters = {
  q: '',
  status: ['owned'],
  category: [],
  platform_id: [],
  brand: [],
  era: [],
  media_type: [],
  condition: [],
  region: [],
  tag: '',
  location: '',
}

const FILTERS_KEY = 'vgvault.filters'

function loadFilters(key: string): Filters {
  try {
    const raw = localStorage.getItem(key)
    return raw ? { ...EMPTY_FILTERS, ...JSON.parse(raw) } : EMPTY_FILTERS
  } catch {
    return EMPTY_FILTERS
  }
}

const PAGE_SIZE = 100
const opts = <T extends string>(labels: Record<T, string>) =>
  (Object.entries(labels) as [T, string][]).map(([value, label]) => ({ value, label }))
const strOpts = (values: string[]) => values.map((v) => ({ value: v, label: v }))

type SortKey =
  | 'title'
  | 'platform'
  | 'brand'
  | 'condition'
  | 'market_price'
  | 'value'
  | 'purchase_price'
  | 'purchase_date'
  | 'created_at'

interface SharedPage {
  owner: string
  shows_paid: boolean
  items: Item[]
  total: number
}

/** Your own collection, or (with `ownerId`) someone's shared collection, read-only. */
export default function CollectionPage({ ownerId }: { ownerId?: number }) {
  const qc = useQueryClient()
  const readOnly = ownerId !== undefined
  const base = readOnly ? `/shared/${ownerId}` : '/collection'
  const storeKey = readOnly ? `vgvault.shared.${ownerId}` : FILTERS_KEY
  const [filters, setFilters] = useState<Filters>(() => loadFilters(storeKey))
  const [search, setSearch] = useState(filters.q)
  const [sort, setSort] = useState<{ key: SortKey; order: 'asc' | 'desc' }>({ key: 'title', order: 'asc' })
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [editing, setEditing] = useState<Item | 'new' | null>(null)

  useEffect(() => {
    try {
      localStorage.setItem(storeKey, JSON.stringify(filters))
    } catch {
      /* storage unavailable */
    }
  }, [filters, storeKey])

  // Debounce the text search.
  useEffect(() => {
    const t = setTimeout(() => update({ q: search }), 250)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search])

  const update = (patch: Partial<Filters>) => {
    setFilters((f) => ({ ...f, ...patch }))
    setPage(0)
    setSelected(new Set())
  }

  const facets = useQuery({ queryKey: ['facets', ownerId], queryFn: () => api.get<Facets>(`${base}/facets`) })
  const items = useQuery({
    queryKey: ['collection', ownerId, filters, sort, page],
    queryFn: () =>
      api.get<Partial<SharedPage> & { items: Item[]; total: number }>(readOnly ? `${base}/collection` : base, {
        ...filters,
        sort: sort.key,
        order: sort.order,
        offset: page * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
    placeholderData: keepPreviousData,
  })
  const summary = useQuery({
    queryKey: ['summary', ownerId],
    queryFn: () => api.get<Partial<Summary> & { total_value: number; quantity: number }>(`${base}/summary`),
  })
  const showPaid = !readOnly || !!items.data?.shows_paid

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['collection'] })
    qc.invalidateQueries({ queryKey: ['facets'] })
    qc.invalidateQueries({ queryKey: ['summary'] })
    qc.invalidateQueries({ queryKey: ['analytics'] })
  }
  const bulk = useMutation({
    mutationFn: (changes: Record<string, unknown>) =>
      api.patch('/collection/bulk', { ids: [...selected], changes }),
    onSuccess: () => {
      setSelected(new Set())
      invalidate()
    },
  })
  const bulkDelete = useMutation({
    mutationFn: () => Promise.all([...selected].map((id) => api.del(`/collection/${id}`))),
    onSuccess: () => {
      setSelected(new Set())
      invalidate()
    },
  })

  const rows = items.data?.items ?? []
  const total = items.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const allSelected = rows.length > 0 && rows.every((r) => selected.has(r.id))
  const f = facets.data

  const header = (key: SortKey, label: string, extra = '') => (
    <th
      className={`sortable ${extra}`}
      onClick={() =>
        setSort((s) => {
          if (s.key === key) return { key, order: s.order === 'asc' ? 'desc' : 'asc' }
          // Money and date columns are most useful biggest/newest first.
          const descFirst = ['market_price', 'value', 'purchase_price', 'purchase_date', 'created_at'].includes(key)
          return { key, order: descFirst ? 'desc' : 'asc' }
        })
      }
    >
      {label}
      {sort.key === key && (sort.order === 'asc' ? ' ▲' : ' ▼')}
    </th>
  )

  return (
    <div className="collection">
      <aside className="filters">
        <input
          type="search"
          placeholder={readOnly ? 'Search titles…' : 'Search titles & notes…'}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button className="link" onClick={() => (setSearch(''), update({ ...EMPTY_FILTERS, status: [] }))}>
          Reset all filters
        </button>
        <CheckList label="Status" options={opts(STATUSES)} value={filters.status} onChange={(v) => update({ status: v })} />
        <CheckList
          label="Category"
          options={opts(CATEGORIES)}
          value={filters.category}
          onChange={(v) => update({ category: v })}
        />
        <CheckList label="Brand" options={strOpts(f?.brands ?? [])} value={filters.brand} onChange={(v) => update({ brand: v })} />
        <CheckList
          label="Platform"
          options={(f?.platforms ?? []).map((p) => ({ value: p.id, label: p.name }))}
          value={filters.platform_id}
          onChange={(v) => update({ platform_id: v })}
        />
        <CheckList label="Era" options={strOpts(f?.eras ?? [])} value={filters.era} onChange={(v) => update({ era: v })} />
        <CheckList
          label="Media"
          options={opts(MEDIA_TYPES)}
          value={filters.media_type}
          onChange={(v) => update({ media_type: v })}
        />
        <CheckList
          label="Condition"
          options={opts(CONDITIONS)}
          value={filters.condition}
          onChange={(v) => update({ condition: v })}
        />
        <CheckList
          label="Region"
          options={strOpts(f?.regions ?? [])}
          value={filters.region}
          onChange={(v) => update({ region: v })}
        />
        {f && f.tags.length > 0 && (
          <label className="field">
            <span>Tag</span>
            <select value={filters.tag} onChange={(e) => update({ tag: e.target.value })}>
              <option value="">Any</option>
              {f.tags.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </label>
        )}
        {f && f.locations.length > 0 && (
          <label className="field">
            <span>Location</span>
            <select value={filters.location} onChange={(e) => update({ location: e.target.value })}>
              <option value="">Any</option>
              {f.locations.map((l) => (
                <option key={l}>{l}</option>
              ))}
            </select>
          </label>
        )}
      </aside>

      <section className="results">
        <div className="page-head">
          <h1>{readOnly ? `${items.data?.owner ?? '…'}'s collection` : 'Collection'}</h1>
          {readOnly && <span className="badge">read-only</span>}
          {summary.data && (
            <span className="muted">
              <strong className="value">{money(summary.data.total_value)}</strong> value · {summary.data.quantity}{' '}
              owned
              {summary.data.cost_basis !== undefined && ` · paid ${money(summary.data.cost_basis)}`}
              {!!summary.data.unpriced && ` · ${summary.data.unpriced} unpriced`}
            </span>
          )}
          <div className="spacer" />
          {readOnly ? (
            <Link to="/shared" className="link">
              All shared collections
            </Link>
          ) : (
            <>
              <Link to="/import" className="link">
                Import
              </Link>
              <details className="dropdown">
                <summary>Export ▾</summary>
                <div className="menu">
                  <p className="muted small" style={{ margin: '0 0 0.4rem' }}>
                    Items matching the current filters
                  </p>
                  <a className="link" href={`/api/collection/export${toQuery({ ...filters, format: 'csv' })}`} download>
                    CSV (spreadsheet)
                  </a>
                  <br />
                  <a className="link" href={`/api/collection/export${toQuery({ ...filters, format: 'json' })}`} download>
                    JSON
                  </a>
                </div>
              </details>
              <button onClick={() => setEditing('new')}>+ Add item</button>
            </>
          )}
        </div>

        {!readOnly && selected.size > 0 && (
          <div className="bulkbar">
            <strong>{selected.size} selected</strong>
            <select
              value=""
              onChange={(e) => e.target.value && bulk.mutate({ status: e.target.value })}
              aria-label="Set status"
            >
              <option value="">Set status…</option>
              {opts(STATUSES).map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <select
              value=""
              onChange={(e) => e.target.value && bulk.mutate({ condition: e.target.value })}
              aria-label="Set condition"
            >
              <option value="">Set condition…</option>
              {opts(CONDITIONS).map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
            <button
              className="ghost"
              onClick={() => {
                const location = prompt('Set location for selected items:')
                if (location !== null) bulk.mutate({ location: location || null })
              }}
            >
              Set location
            </button>
            <button
              className="ghost danger"
              onClick={() => confirm(`Delete ${selected.size} items?`) && bulkDelete.mutate()}
            >
              Delete
            </button>
            <button className="link" onClick={() => setSelected(new Set())}>
              clear
            </button>
          </div>
        )}
        <ErrorText error={items.error ?? bulk.error ?? bulkDelete.error} />

        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                {!readOnly && (
                  <th>
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={() => setSelected(allSelected ? new Set() : new Set(rows.map((r) => r.id)))}
                      aria-label="Select all"
                    />
                  </th>
                )}
                {header('title', 'Title')}
                {header('platform', 'Platform')}
                {header('brand', 'Brand')}
                <th>Category</th>
                {header('condition', 'Condition')}
                <th>Qty</th>
                {header('market_price', 'Market', 'num')}
                {header('value', 'Value', 'num')}
                {showPaid && header('purchase_price', 'Paid')}
                {showPaid && header('purchase_date', 'Bought')}
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((item) => (
                <tr
                  key={item.id}
                  className={readOnly ? '' : 'clickable'}
                  onClick={readOnly ? undefined : () => setEditing(item)}
                >
                  {!readOnly && (
                    <td onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selected.has(item.id)}
                        onChange={(e) => {
                          const next = new Set(selected)
                          if (e.target.checked) next.add(item.id)
                          else next.delete(item.id)
                          setSelected(next)
                        }}
                      />
                    </td>
                  )}
                  <td className="title-cell">
                    {item.product.has_image ? (
                      <img className="thumb" src={`/api/products/${item.product.id}/image`} alt="" loading="lazy" />
                    ) : (
                      <span className="thumb" />
                    )}
                    {item.product.title}
                    {!readOnly && !item.product.pricecharting_id && (
                      <span className="tag" title="Not linked to PriceCharting">
                        unlinked
                      </span>
                    )}
                    {item.tags.map((t) => (
                      <span key={t} className="tag">
                        {t}
                      </span>
                    ))}
                  </td>
                  <td>{item.product.platform.name}</td>
                  <td>{item.product.platform.brand}</td>
                  <td>{CATEGORIES[item.product.category]}</td>
                  <td>{CONDITIONS[item.condition]}</td>
                  <td>{item.quantity}</td>
                  <td className="num">{money(item.market_price)}</td>
                  <td className="num">
                    <strong>{money(item.value)}</strong>
                  </td>
                  {showPaid && <td className="num">{money(item.purchase_price)}</td>}
                  {showPaid && <td>{item.purchase_date ?? ''}</td>}
                  <td>{STATUSES[item.status]}</td>
                </tr>
              ))}
              {!items.isLoading && rows.length === 0 && (
                <tr>
                  <td colSpan={12} className="muted empty">
                    {readOnly ? 'No items match these filters.' : 'Nothing here yet. Add an item or loosen the filters.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="pager">
          <span className="muted">{total} items</span>
          <div className="spacer" />
          <button className="ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>
            ← Prev
          </button>
          <span>
            {page + 1} / {pages}
          </span>
          <button className="ghost" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>
            Next →
          </button>
        </div>
      </section>

      {editing && (
        <ItemDialog
          item={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={invalidate}
        />
      )}
    </div>
  )
}
