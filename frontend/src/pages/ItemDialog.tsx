import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import {
  api,
  CATEGORIES,
  CONDITIONS,
  STATUSES,
  type Category,
  type Condition,
  type Item,
  type ItemFields,
  type ItemStatus,
  type Platform,
  type Product,
} from '../api'
import { ErrorText, Field, Modal } from '../components'

const DEFAULTS: ItemFields = {
  status: 'owned',
  condition: 'loose',
  has_item: true,
  has_box: false,
  has_manual: false,
  has_inserts: false,
  grade: null,
  quantity: 1,
  purchase_price: null,
  purchase_date: null,
  sold_price: null,
  sold_date: null,
  target_price: null,
  location: null,
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
    const { id: _id, product: _p, created_at: _c, updated_at: _u, ...rest } = item
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

  const set = <K extends keyof ItemFields>(key: K, value: ItemFields[K]) => setFields((f) => ({ ...f, [key]: value }))
  const str = (v: string) => (v === '' ? null : v)
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }

  return (
    <Modal title={item ? 'Edit item' : 'Add item'} onClose={onClose} wide>
      {product ? (
        <div className="picked">
          <div>
            <strong>{product.title}</strong>
            <span className="muted">
              {' '}
              · {product.platform.name} · {CATEGORIES[product.category]}
            </span>
          </div>
          <button className="link" onClick={() => setProduct(null)}>
            change
          </button>
        </div>
      ) : (
        <ProductPicker onPick={setProduct} />
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
          <Field label="Condition">
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
          <Field label="Location">
            <input value={fields.location ?? ''} onChange={(e) => set('location', str(e.target.value))} />
          </Field>
          <Field label="Tags (comma separated)">
            <input value={tagText} onChange={(e) => setTagText(e.target.value)} />
          </Field>
          <label className="field span2">
            <span>Notes</span>
            <textarea rows={3} value={fields.notes ?? ''} onChange={(e) => set('notes', str(e.target.value))} />
          </label>
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

/** Search the shared catalog, or create a new catalog product. */
function ProductPicker({ onPick }: { onPick: (p: Product) => void }) {
  const [q, setQ] = useState('')
  const [debounced, setDebounced] = useState('')
  const [platformId, setPlatformId] = useState<number | ''>('')
  const [category, setCategory] = useState<Category>('game')
  const platforms = useQuery({ queryKey: ['platforms'], queryFn: () => api.get<Platform[]>('/platforms') })

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
    <div className="picker">
      <div className="grid2">
        <Field label="Title">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. Super Metroid" autoFocus />
        </Field>
        <Field label="Platform">
          <select value={platformId} onChange={(e) => setPlatformId(e.target.value ? Number(e.target.value) : '')}>
            <option value="">Any / choose…</option>
            {platforms.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.brand})
              </option>
            ))}
          </select>
        </Field>
      </div>
      {results.data && results.data.length > 0 && (
        <ul className="results-list">
          {results.data.map((p) => (
            <li key={p.id}>
              <button className="ghost" onClick={() => onPick(p)}>
                <strong>{p.title}</strong>
                <span className="muted">
                  {' '}
                  · {p.platform.name} · {CATEGORIES[p.category]}
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
          <button disabled={!platformId || create.isPending} onClick={() => create.mutate()}>
            Create “{q.trim()}”
          </button>
          {!platformId && <span className="muted">(pick a platform first)</span>}
        </div>
      )}
      <ErrorText error={create.error} />
      <p className="muted small">PriceCharting search & linking arrives in phase 2.</p>
    </div>
  )
}
