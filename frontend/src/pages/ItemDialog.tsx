import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  api,
  CATEGORIES,
  CONDITIONS,
  parseUtc,
  RATINGS,
  STATUSES,
  type Category,
  type Condition,
  type Item,
  type ItemFields,
  type ItemStatus,
  type Platform,
  type Product,
  type SearchHit,
  type Snapshot,
} from '../api'
import { ErrorText, Field, Modal, money } from '../components'
import BarcodeScanner, { cameraAvailable, normalizeUpc } from '../BarcodeScanner'
import PriceChart from '../PriceChart'

const DEFAULTS: ItemFields = {
  status: 'owned',
  condition: 'loose',
  has_item: true,
  has_box: false,
  has_manual: false,
  has_inserts: false,
  grade: null,
  item_rating: null,
  box_rating: null,
  manual_rating: null,
  quantity: 1,
  purchase_price: null,
  purchase_date: null,
  sold_price: null,
  sold_date: null,
  target_price: null,
  location: null,
  acquired_from: null,
  tags: [],
  notes: null,
}

export default function ItemDialog({
  item,
  onClose,
  onSaved,
}: {
  item: Item | null
  onClose: () => void
  onSaved: () => void
}) {
  const [product, setProduct] = useState<Product | null>(item?.product ?? null)
  const [fields, setFields] = useState<ItemFields>(() => {
    if (!item) return DEFAULTS
    const {
      id: _id,
      product: _p,
      created_at: _c,
      updated_at: _u,
      market_price: _m,
      value: _v,
      priced_on: _po,
      ...rest
    } = item
    return rest
  })
  const [tagText, setTagText] = useState(fields.tags.join(', '))

  const save = useMutation({
    mutationFn: () => {
      const body = {
        ...fields,
        product_id: product!.id,
        tags: tagText
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
      }
      return item ? api.patch(`/collection/${item.id}`, body) : api.post('/collection', body)
    },
    onSuccess: () => {
      onSaved()
      onClose()
    },
  })
  const remove = useMutation({
    mutationFn: () => api.del(`/collection/${item!.id}`),
    onSuccess: () => {
      onSaved()
      onClose()
    },
  })

  const set = <K extends keyof ItemFields>(key: K, value: ItemFields[K]) =>
    setFields((f) => ({ ...f, [key]: value }))
  const str = (v: string) => (v === '' ? null : v)
  // Shown on the collapsed "More details" header so existing data isn't hidden silently.
  const filledExtras = [
    fields.item_rating,
    fields.box_rating,
    fields.manual_rating,
    fields.location,
    fields.acquired_from,
    tagText.trim(),
    fields.notes,
  ].filter((v) => v != null && v !== '').length
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }

  return (
    <Modal title={item ? 'Edit item' : 'Add item'} onClose={onClose} wide>
      {product ? (
        <div className="picked">
          {product.has_image && <img className="cover" src={`/api/products/${product.id}/image`} alt="" />}
          <div>
            <strong>{product.title}</strong>
            <div className="muted">
              {product.platform.name} · {CATEGORIES[product.category]}
              {product.genre && ` · ${product.genre}`}
            </div>
          </div>
          <div className="spacer" />
          {!item && (
            <button className="link" onClick={() => setProduct(null)}>
              change
            </button>
          )}
        </div>
      ) : (
        <ProductPicker onPick={setProduct} />
      )}

      {product && (
        <PricePanel
          product={product}
          condition={fields.condition}
          purchasePrice={fields.purchase_price}
          onProductChange={(p) => {
            setProduct(p)
            onSaved()
          }}
        />
      )}

      {product && (
        <form onSubmit={onSubmit} className="grid2">
          <Field label="Status">
            <select value={fields.status} onChange={(e) => set('status', e.target.value as ItemStatus)}>
              {Object.entries(STATUSES).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Ownership">
            <select value={fields.condition} onChange={(e) => set('condition', e.target.value as Condition)}>
              {Object.entries(CONDITIONS).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </Field>
          <div className="span2 row checks">
            {(['has_item', 'has_box', 'has_manual', 'has_inserts'] as const).map((k) => (
              <label key={k} className="check">
                <input type="checkbox" checked={fields[k]} onChange={(e) => set(k, e.target.checked)} />
                {k.replace('has_', '').replace(/^./, (c) => c.toUpperCase())}
              </label>
            ))}
          </div>
          {fields.condition === 'graded' && (
            <Field label="Grade">
              <input value={fields.grade ?? ''} onChange={(e) => set('grade', str(e.target.value))} />
            </Field>
          )}
          <Field label="Quantity">
            <input
              type="number"
              min={1}
              value={fields.quantity}
              onChange={(e) => set('quantity', Math.max(1, Number(e.target.value)))}
            />
          </Field>
          {fields.status === 'wishlist' ? (
            <Field label="Target price">
              <input
                type="number"
                step="0.01"
                min={0}
                value={fields.target_price ?? ''}
                onChange={(e) => set('target_price', str(e.target.value))}
              />
            </Field>
          ) : (
            <>
              <Field label="Purchase price">
                <input
                  type="number"
                  step="0.01"
                  min={0}
                  value={fields.purchase_price ?? ''}
                  onChange={(e) => set('purchase_price', str(e.target.value))}
                />
              </Field>
              <Field label="Purchase date">
                <input
                  type="date"
                  value={fields.purchase_date ?? ''}
                  onChange={(e) => set('purchase_date', str(e.target.value))}
                />
              </Field>
            </>
          )}
          {fields.status === 'sold' && (
            <>
              <Field label="Sold price">
                <input
                  type="number"
                  step="0.01"
                  min={0}
                  value={fields.sold_price ?? ''}
                  onChange={(e) => set('sold_price', str(e.target.value))}
                />
              </Field>
              <Field label="Sold date">
                <input
                  type="date"
                  value={fields.sold_date ?? ''}
                  onChange={(e) => set('sold_date', str(e.target.value))}
                />
              </Field>
            </>
          )}
          <details className="span2 more-fields">
            <summary>
              More details
              {filledExtras > 0 && <span className="muted small"> · {filledExtras} filled</span>}
            </summary>
            <div className="grid2">
              <div className="span2 ratings">
                <span className="muted small">Condition</span>
                {(
                  [
                    ['item_rating', 'Game', 'has_item'],
                    ['box_rating', 'Box', 'has_box'],
                    ['manual_rating', 'Manual', 'has_manual'],
                  ] as const
                ).map(([k, label, part]) => (
                  <Field key={k} label={label}>
                    <select
                      value={fields[k] ?? ''}
                      disabled={!fields[part]}
                      onChange={(e) => set(k, e.target.value ? Number(e.target.value) : null)}
                    >
                      <option value="">Not rated</option>
                      {Object.entries(RATINGS)
                        .reverse()
                        .map(([v, l]) => (
                          <option key={v} value={v}>
                            {v} · {l}
                          </option>
                        ))}
                    </select>
                  </Field>
                ))}
              </div>
              <Field label="Location">
                <input value={fields.location ?? ''} onChange={(e) => set('location', str(e.target.value))} />
              </Field>
              <Field label="Bought from">
                <input
                  value={fields.acquired_from ?? ''}
                  onChange={(e) => set('acquired_from', str(e.target.value))}
                  placeholder="Game store, eBay, garage sale…"
                  maxLength={64}
                  list="sources"
                />
              </Field>
              <Field label="Tags (comma separated)">
                <input value={tagText} onChange={(e) => setTagText(e.target.value)} />
              </Field>
              <label className="field span2">
                <span>Notes</span>
                <textarea rows={3} value={fields.notes ?? ''} onChange={(e) => set('notes', str(e.target.value))} />
              </label>
            </div>
          </details>
          <div className="span2">
            <ErrorText error={save.error ?? remove.error} />
            <div className="row">
              <button type="submit" disabled={save.isPending}>
                {item ? 'Save' : 'Add to collection'}
              </button>
              {item && (
                <button
                  type="button"
                  className="ghost danger"
                  onClick={() => confirm('Delete this item?') && remove.mutate()}
                >
                  Delete
                </button>
              )}
            </div>
          </div>
        </form>
      )}
    </Modal>
  )
}

/** Current market price, history chart, and PriceCharting link/refresh controls. */
function PricePanel({
  product,
  condition,
  purchasePrice,
  onProductChange,
}: {
  product: Product
  condition: Condition
  purchasePrice: string | null
  onProductChange: (p: Product) => void
}) {
  const qc = useQueryClient()
  const [linkUrl, setLinkUrl] = useState('')
  const history = useQuery({
    queryKey: ['prices', product.id],
    queryFn: () => api.get<Snapshot[]>(`/products/${product.id}/prices`),
    enabled: !!product.pricecharting_url,
  })
  const done = (p: Product) => {
    qc.invalidateQueries({ queryKey: ['prices', product.id] })
    setLinkUrl('')
    onProductChange(p)
  }
  const refresh = useMutation({
    mutationFn: () => api.post<Product>(`/products/${product.id}/refresh`),
    onSuccess: done,
  })
  const link = useMutation({
    mutationFn: () => api.post<Product>(`/products/${product.id}/link`, { url: linkUrl.trim() }),
    onSuccess: done,
  })

  if (!product.pricecharting_url) {
    return (
      <div className="price-panel">
        <p className="muted">Not linked to PriceCharting, so no price tracking yet. Paste the game's page URL:</p>
        <div className="row">
          <input
            placeholder="https://www.pricecharting.com/game/…"
            value={linkUrl}
            onChange={(e) => setLinkUrl(e.target.value)}
            style={{ flex: 1, width: 'auto' }}
          />
          <button type="button" disabled={!linkUrl || link.isPending} onClick={() => link.mutate()}>
            {link.isPending ? 'Linking…' : 'Link'}
          </button>
        </div>
        <ErrorText error={link.error} />
      </div>
    )
  }

  const snaps = history.data ?? []
  const latest = snaps[snaps.length - 1]
  const current = latest?.[condition]

  return (
    <div className="price-panel">
      <div className="row">
        <div>
          <div className="muted small">{CONDITIONS[condition]} market price</div>
          <div className="big">{money(current)}</div>
        </div>
        {latest && (
          <div className="muted small">
            Loose {money(latest.loose)} · CIB {money(latest.cib)} · New {money(latest.new)}
          </div>
        )}
        <div className="spacer" />
        <div className="muted small right">
          {product.last_priced_at ? `Updated ${parseUtc(product.last_priced_at).toLocaleString()}` : 'Never updated'}
          <br />
          <a href={product.pricecharting_url} target="_blank" rel="noreferrer noopener" className="link">
            View on PriceCharting ↗
          </a>
        </div>
        <button type="button" className="ghost" disabled={refresh.isPending} onClick={() => refresh.mutate()}>
          {refresh.isPending ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
      <ErrorText error={refresh.error} />
      {history.isLoading ? (
        <p className="muted">Loading history…</p>
      ) : (
        <PriceChart snapshots={snaps} condition={condition} purchasePrice={purchasePrice} />
      )}
    </div>
  )
}

/** Search PriceCharting (default) or the local catalog / create manually. */
function ProductPicker({ onPick }: { onPick: (p: Product) => void }) {
  const [mode, setMode] = useState<'pricecharting' | 'manual'>('pricecharting')
  const [platformId, setPlatformId] = useState<number | ''>('')
  const platforms = useQuery({ queryKey: ['platforms'], queryFn: () => api.get<Platform[]>('/platforms') })

  return (
    <div className="picker">
      <div className="seg" style={{ marginBottom: '0.75rem' }}>
        <button type="button" className={mode === 'pricecharting' ? 'on' : ''} onClick={() => setMode('pricecharting')}>
          Search PriceCharting
        </button>
        <button type="button" className={mode === 'manual' ? 'on' : ''} onClick={() => setMode('manual')}>
          Catalog / manual
        </button>
      </div>
      <Field label="Platform">
        <select value={platformId} onChange={(e) => setPlatformId(e.target.value ? Number(e.target.value) : '')}>
          <option value="">{mode === 'pricecharting' ? 'Any' : 'Choose…'}</option>
          {platforms.data?.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} ({p.brand})
            </option>
          ))}
        </select>
      </Field>
      {mode === 'pricecharting' ? (
        <PriceChartingSearch platformId={platformId} onPick={onPick} />
      ) : (
        <ManualPicker platformId={platformId} onPick={onPick} />
      )}
    </div>
  )
}

function PriceChartingSearch({ platformId, onPick }: { platformId: number | ''; onPick: (p: Product) => void }) {
  const [q, setQ] = useState('')
  const [category, setCategory] = useState<Category | ''>('')
  const [scanning, setScanning] = useState(false)
  const isUpc = /^\d{8,14}$/.test(q.trim())
  const search = useMutation({
    mutationFn: async (query: string) => {
      // A barcode already in the catalog doesn't need a trip to PriceCharting.
      if (/^\d{8,14}$/.test(query)) {
        const local = await api.get<Product[]>('/products', { upc: query })
        if (local.length > 0) {
          onPick(local[0])
          return []
        }
      }
      return api.get<SearchHit[]>('/pricecharting/search', { q: query, platform_id: platformId || undefined })
    },
  })
  const onScanned = useCallback(
    (code: string) => {
      setScanning(false)
      setQ(code)
      search.mutate(code)
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )
  const choose = useMutation({
    mutationFn: (hit: SearchHit) =>
      hit.product_id
        ? api.get<Product>(`/products/${hit.product_id}`)
        : api.post<Product>('/products/import', {
            url: hit.url,
            platform_id: hit.platform_id ?? (platformId || null),
            category: category || null,
            upc: isUpc ? q.trim() : null,
          }),
    onSuccess: onPick,
  })
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    const query = /^\d{13}$/.test(q.trim()) ? normalizeUpc(q.trim()) : q.trim()
    if (query !== q) setQ(query)
    if (query.length >= 2) search.mutate(query)
  }

  return (
    <>
      <form onSubmit={onSubmit} className="row">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Title, UPC or ASIN"
          autoFocus
          style={{ flex: 1, width: 'auto' }}
        />
        <button type="submit" disabled={search.isPending || q.trim().length < 2}>
          {search.isPending ? 'Searching…' : 'Search'}
        </button>
        <button
          type="button"
          className="ghost"
          onClick={() => setScanning(true)}
          disabled={!cameraAvailable()}
          title={cameraAvailable() ? 'Scan a UPC barcode' : 'Camera needs HTTPS (or localhost). Type the UPC instead.'}
        >
          📷 Scan
        </button>
      </form>
      {scanning && <BarcodeScanner onDetected={onScanned} onClose={() => setScanning(false)} />}
      <ErrorText error={search.error ?? choose.error} />
      {search.isSuccess && search.data.length === 0 && (
        <p className="muted">{isUpc ? 'No product found for that barcode. Try searching by title.' : 'No results.'}</p>
      )}
      {search.data && search.data.length > 0 && (
        <>
          <ul className="results-list">
            {search.data.map((hit) => (
              <li key={hit.source_id}>
                <button
                  type="button"
                  className="ghost hit"
                  disabled={choose.isPending}
                  onClick={() => choose.mutate(hit)}
                >
                  {hit.image_url ? <img src={hit.image_url} alt="" loading="lazy" /> : <span className="noimg" />}
                  <span className="hit-title">
                    <strong>{hit.title}</strong>
                    <span className="muted">
                      {' '}
                      · {hit.console_name ?? hit.console_slug}
                      {hit.platform_match && ' ✓'}
                      {hit.product_id && ' · in catalog'}
                      {!hit.platform_id && !platformId && ' · no platform mapping'}
                    </span>
                  </span>
                  <span className="hit-prices muted small">
                    L {money(hit.loose)} · C {money(hit.cib)} · N {money(hit.new)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <div className="row small">
            <span className="muted">Import as</span>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as Category | '')}
              style={{ width: 'auto' }}
              aria-label="Category"
            >
              <option value="">Auto (game / console)</option>
              {Object.entries(CATEGORIES).map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
            {choose.isPending && <span className="muted">Fetching prices & history…</span>}
          </div>
        </>
      )}
      <p className="muted small">Requests to PriceCharting are rate limited, so each one can take a few seconds.</p>
    </>
  )
}

function ManualPicker({ platformId, onPick }: { platformId: number | ''; onPick: (p: Product) => void }) {
  const [q, setQ] = useState('')
  const [debounced, setDebounced] = useState('')
  const [category, setCategory] = useState<Category>('game')

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 250)
    return () => clearTimeout(t)
  }, [q])

  const results = useQuery({
    queryKey: ['products', debounced, platformId],
    queryFn: () => api.get<Product[]>('/products', { q: debounced, platform_id: platformId || undefined, limit: 20 }),
    enabled: debounced.length >= 2,
  })
  const create = useMutation({
    mutationFn: () => api.post<Product>('/products', { title: q.trim(), platform_id: platformId, category }),
    onSuccess: onPick,
  })

  return (
    <>
      <Field label="Title">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search your catalog" autoFocus />
      </Field>
      {results.data && results.data.length > 0 && (
        <ul className="results-list">
          {results.data.map((p) => (
            <li key={p.id}>
              <button type="button" className="ghost" onClick={() => onPick(p)}>
                <strong>{p.title}</strong>
                <span className="muted">
                  {' '}
                  · {p.platform.name} · {CATEGORIES[p.category]}
                  {p.pricecharting_id && ' · priced'}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {debounced.length >= 2 && results.isSuccess && (
        <div className="row create-row">
          <span className="muted">Not listed?</span>
          <select value={category} onChange={(e) => setCategory(e.target.value as Category)} aria-label="Category">
            {Object.entries(CATEGORIES).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
          <button type="button" disabled={!platformId || create.isPending} onClick={() => create.mutate()}>
            Create “{q.trim()}”
          </button>
          {!platformId && <span className="muted">(pick a platform first)</span>}
        </div>
      )}
      <ErrorText error={create.error} />
    </>
  )
}
