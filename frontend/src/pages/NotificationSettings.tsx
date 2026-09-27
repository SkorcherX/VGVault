import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { api } from '../api'
import { ErrorText, Field } from '../components'

interface Settings {
  enabled: boolean
  urls: string[]
  price_moves: boolean
  move_pct: number
  move_min_value: string
  wishlist_targets: boolean
}

export default function NotificationSettings() {
  const qc = useQueryClient()
  const current = useQuery({
    queryKey: ['notifications'],
    queryFn: () => api.get<Settings>('/auth/notifications'),
  })
  const [form, setForm] = useState<Settings | null>(null)
  const [urlText, setUrlText] = useState('')
  useEffect(() => {
    if (current.data) {
      setForm(current.data)
      setUrlText(current.data.urls.join('\n'))
    }
  }, [current.data])

  const save = useMutation({
    mutationFn: () =>
      api.put<Settings>('/auth/notifications', {
        ...form,
        urls: urlText.split('\n').map((u) => u.trim()).filter(Boolean),
      }),
    onSuccess: (data) => qc.setQueryData(['notifications'], data),
  })
  const test = useMutation({ mutationFn: () => api.post('/auth/notifications/test') })

  if (!form) return null
  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => setForm({ ...form, [k]: v })
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    test.reset()
    save.mutate()
  }

  return (
    <form className="card" onSubmit={onSubmit}>
      <h2>Price alerts</h2>
      <p className="muted small">
        After each scheduled price update you get one message listing what changed. Uses{' '}
        <a
          className="link"
          href="https://github.com/caronc/apprise/wiki#notification-services"
          target="_blank"
          rel="noreferrer noopener"
        >
          Apprise URLs
        </a>
        , e.g. <code>discord://webhook_id/token</code>, <code>ntfys://ntfy.sh/my-topic</code> or{' '}
        <code>mailtos://user:pass@gmail.com</code>.
      </p>
      <label className="check" style={{ marginBottom: '0.75rem' }}>
        <input type="checkbox" checked={form.enabled} onChange={(e) => set('enabled', e.target.checked)} />
        Send price alerts
      </label>
      <label className="field">
        <span>Notification URLs (one per line)</span>
        <textarea rows={3} value={urlText} onChange={(e) => setUrlText(e.target.value)} spellCheck={false} />
      </label>
      <label className="check" style={{ marginBottom: '0.5rem' }}>
        <input type="checkbox" checked={form.price_moves} onChange={(e) => set('price_moves', e.target.checked)} />
        Owned items that move in price
      </label>
      {form.price_moves && (
        <div className="grid2">
          <Field label="By at least (%)">
            <input
              type="number"
              min={1}
              step={1}
              value={form.move_pct}
              onChange={(e) => set('move_pct', Number(e.target.value))}
            />
          </Field>
          <Field label="Ignore items under ($)">
            <input
              type="number"
              min={0}
              step={1}
              value={form.move_min_value}
              onChange={(e) => set('move_min_value', e.target.value)}
            />
          </Field>
        </div>
      )}
      <label className="check" style={{ marginBottom: '0.75rem' }}>
        <input
          type="checkbox"
          checked={form.wishlist_targets}
          onChange={(e) => set('wishlist_targets', e.target.checked)}
        />
        Wishlist items that drop to their target price
      </label>
      <ErrorText error={save.error ?? test.error} />
      {save.isSuccess && test.isIdle && <p className="ok">Saved.</p>}
      {test.isSuccess && <p className="ok">Test message sent.</p>}
      <div className="row">
        <button type="submit" disabled={save.isPending}>
          Save
        </button>
        <button
          type="button"
          className="ghost"
          disabled={test.isPending || current.data?.urls.length === 0}
          title={current.data?.urls.length === 0 ? 'Save a URL first' : ''}
          onClick={() => test.mutate()}
        >
          {test.isPending ? 'Sending…' : 'Send test'}
        </button>
      </div>
    </form>
  )
}
