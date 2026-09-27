import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState, type FormEvent } from 'react'
import { api, MEDIA_TYPES, type MediaType, type Platform } from '../api'
import { ErrorText, Field, Modal } from '../components'

const EMPTY: Omit<Platform, 'id'> = {
  name: '',
  slug: '',
  brand: '',
  generation: null,
  era: null,
  media_type: 'cartridge',
  handheld: false,
  region: 'NTSC-U',
  release_year: null,
  pricecharting_slug: null,
}

export default function PlatformsPage({ isAdmin }: { isAdmin: boolean }) {
  const platforms = useQuery({ queryKey: ['platforms'], queryFn: () => api.get<Platform[]>('/platforms') })
  const [filter, setFilter] = useState('')
  const [editing, setEditing] = useState<Platform | 'new' | null>(null)

  const rows = useMemo(() => {
    const f = filter.toLowerCase()
    return (platforms.data ?? []).filter(
      (p) => !f || p.name.toLowerCase().includes(f) || p.brand.toLowerCase().includes(f),
    )
  }, [platforms.data, filter])

  return (
    <div className="page">
      <div className="page-head">
        <h1>Platforms</h1>
        <input placeholder="Filter…" value={filter} onChange={(e) => setFilter(e.target.value)} />
        {isAdmin && <button onClick={() => setEditing('new')}>+ Add platform</button>}
      </div>
      <table className="table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Brand</th>
            <th>Era</th>
            <th>Media</th>
            <th>Handheld</th>
            <th>Year</th>
            <th>PriceCharting slug</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.id} className={isAdmin ? 'clickable' : ''} onClick={() => isAdmin && setEditing(p)}>
              <td>{p.name}</td>
              <td>{p.brand}</td>
              <td>{p.era ?? '—'}</td>
              <td>{MEDIA_TYPES[p.media_type]}</td>
              <td>{p.handheld ? 'Yes' : ''}</td>
              <td>{p.release_year ?? ''}</td>
              <td className="muted">{p.pricecharting_slug ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {editing && (
        <PlatformForm platform={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />
      )}
    </div>
  )
}

function PlatformForm({ platform, onClose }: { platform: Platform | null; onClose: () => void }) {
  const qc = useQueryClient()
  const [form, setForm] = useState<Omit<Platform, 'id'>>(platform ?? EMPTY)
  const save = useMutation({
    mutationFn: () => {
      if (!platform) return api.post('/platforms', form)
      const { slug: _slug, ...changes } = form
      return api.patch(`/platforms/${platform.id}`, changes)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['platforms'] })
      onClose()
    },
  })
  const remove = useMutation({
    mutationFn: () => api.del(`/platforms/${platform!.id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['platforms'] })
      onClose()
    },
  })
  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) => setForm({ ...form, [key]: value })
  const num = (v: string) => (v === '' ? null : Number(v))
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }

  return (
    <Modal title={platform ? `Edit ${platform.name}` : 'Add platform'} onClose={onClose}>
      <form onSubmit={onSubmit} className="grid2">
        <Field label="Name">
          <input value={form.name} onChange={(e) => set('name', e.target.value)} required />
        </Field>
        <Field label="Slug">
          <input
            value={form.slug}
            onChange={(e) => set('slug', e.target.value)}
            required
            pattern="[a-z0-9-]+"
            disabled={!!platform}
          />
        </Field>
        <Field label="Brand">
          <input value={form.brand} onChange={(e) => set('brand', e.target.value)} required />
        </Field>
        <Field label="Era">
          <input value={form.era ?? ''} onChange={(e) => set('era', e.target.value || null)} />
        </Field>
        <Field label="Generation">
          <input type="number" value={form.generation ?? ''} onChange={(e) => set('generation', num(e.target.value))} />
        </Field>
        <Field label="Release year">
          <input
            type="number"
            value={form.release_year ?? ''}
            onChange={(e) => set('release_year', num(e.target.value))}
          />
        </Field>
        <Field label="Media type">
          <select value={form.media_type} onChange={(e) => set('media_type', e.target.value as MediaType)}>
            {Object.entries(MEDIA_TYPES).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Region">
          <input value={form.region} onChange={(e) => set('region', e.target.value)} />
        </Field>
        <Field label="PriceCharting slug">
          <input
            value={form.pricecharting_slug ?? ''}
            onChange={(e) => set('pricecharting_slug', e.target.value || null)}
          />
        </Field>
        <label className="check">
          <input type="checkbox" checked={form.handheld} onChange={(e) => set('handheld', e.target.checked)} />
          Handheld
        </label>
        <div className="span2">
          <ErrorText error={save.error ?? remove.error} />
          <div className="row">
            <button type="submit" disabled={save.isPending}>
              Save
            </button>
            {platform && (
              <button
                type="button"
                className="ghost danger"
                onClick={() => confirm(`Delete ${platform.name}?`) && remove.mutate()}
              >
                Delete
              </button>
            )}
          </div>
        </div>
      </form>
    </Modal>
  )
}
