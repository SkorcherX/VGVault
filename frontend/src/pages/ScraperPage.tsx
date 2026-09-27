import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { api, parseUtc, type ScrapeErrorRow, type ScraperSettings, type ScraperStatus } from '../api'
import { ErrorText, Field } from '../components'

const fmt = (s: string | null) => (s ? parseUtc(s).toLocaleString() : '—')

function duration(run: { started_at: string; finished_at: string | null }) {
  const end = run.finished_at ? parseUtc(run.finished_at).getTime() : Date.now()
  const secs = Math.round((end - parseUtc(run.started_at).getTime()) / 1000)
  return secs < 60 ? `${secs}s` : secs < 3600 ? `${Math.round(secs / 60)}m` : `${(secs / 3600).toFixed(1)}h`
}

export default function ScraperPage() {
  const qc = useQueryClient()
  const status = useQuery({
    queryKey: ['scraper'],
    queryFn: () => api.get<ScraperStatus>('/admin/scraper'),
    refetchInterval: (q) => (q.state.data?.running ? 3000 : 30000),
  })
  const errors = useQuery({
    queryKey: ['scraper-errors'],
    queryFn: () => api.get<ScrapeErrorRow[]>('/admin/scraper/errors', { limit: 50 }),
    refetchInterval: status.data?.running ? 5000 : false,
  })
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['scraper'] })
    qc.invalidateQueries({ queryKey: ['scraper-errors'] })
  }
  const run = useMutation({
    mutationFn: (force: boolean) => api.post('/admin/scraper/run', { force }),
    onSuccess: () => setTimeout(invalidate, 500),
  })
  const cancel = useMutation({ mutationFn: () => api.post('/admin/scraper/cancel'), onSuccess: invalidate })

  const s = status.data
  const active = s?.runs.find((r) => r.id === s.current_run_id)

  return (
    <div className="page">
      <div className="page-head">
        <h1>Price tracking</h1>
        <div className="spacer" />
        {s?.running ? (
          <button className="ghost danger" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
            Cancel run
          </button>
        ) : (
          <>
            <button className="ghost" onClick={() => run.mutate(true)} disabled={run.isPending}>
              Update all now
            </button>
            <button onClick={() => run.mutate(false)} disabled={run.isPending}>
              Update stale now
            </button>
          </>
        )}
      </div>
      <ErrorText error={status.error ?? run.error ?? cancel.error} />

      {s && (
        <div className="stats">
          <Stat label="Status" value={s.running ? 'Running' : s.settings.enabled ? 'Scheduled' : 'Paused'} />
          <Stat label="Next scheduled run" value={s.settings.enabled ? fmt(s.next_run_at) : 'Disabled'} />
          <Stat label="Tracked items" value={String(s.tracked_products)} hint="linked & in a collection" />
          <Stat
            label="Unlinked items"
            value={String(s.unlinked_products)}
            hint="in a collection, no PriceCharting link"
          />
        </div>
      )}

      {s?.running && active && (
        <div className="card progress">
          <div className="row">
            <strong>Run #{active.id}</strong>
            <span className="muted">
              {active.succeeded + active.failed} / {active.total} · {active.failed} failed · {duration(active)}
            </span>
            <div className="spacer" />
            <span className="muted small">{s.current_item && `Now: ${s.current_item}`}</span>
          </div>
          <div className="bar">
            <div style={{ width: `${((active.succeeded + active.failed) / Math.max(1, active.total)) * 100}%` }} />
          </div>
        </div>
      )}

      <div className="two-col">
        {s && <SettingsForm settings={s.settings} onSaved={invalidate} />}
        <div className="card">
          <h2>Recent runs</h2>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Started</th>
                  <th>Trigger</th>
                  <th>Status</th>
                  <th className="num">OK</th>
                  <th className="num">Failed</th>
                  <th>Took</th>
                </tr>
              </thead>
              <tbody>
                {s?.runs.map((r) => (
                  <tr key={r.id} title={r.message ?? ''}>
                    <td>{r.id}</td>
                    <td>{fmt(r.started_at)}</td>
                    <td>{r.trigger}</td>
                    <td>
                      <span className={`pill ${r.status}`}>{r.status}</span>
                    </td>
                    <td className="num">
                      {r.succeeded}/{r.total}
                    </td>
                    <td className="num">{r.failed || ''}</td>
                    <td>{duration(r)}</td>
                  </tr>
                ))}
                {s?.runs.length === 0 && (
                  <tr>
                    <td colSpan={7} className="muted empty">
                      No runs yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="card">
        <h2>Recent errors</h2>
        {errors.data?.length === 0 ? (
          <p className="muted">No errors. 🎉</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Product</th>
                  <th>Kind</th>
                  <th>HTTP</th>
                  <th>Message</th>
                </tr>
              </thead>
              <tbody>
                {errors.data?.map((e) => (
                  <tr key={e.id}>
                    <td>{fmt(e.created_at)}</td>
                    <td>
                      {e.url ? (
                        <a href={e.url} target="_blank" rel="noreferrer noopener" className="link">
                          {e.product_title ?? e.url}
                        </a>
                      ) : (
                        (e.product_title ?? '—')
                      )}
                    </td>
                    <td>
                      <span className={`pill ${e.kind}`}>{e.kind}</span>
                    </td>
                    <td>{e.http_status ?? ''}</td>
                    <td className="wrap" title={e.snapshot_path ?? ''}>
                      {e.message}
                      {e.snapshot_path && <div className="muted small">HTML saved: {e.snapshot_path}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="stat" title={hint}>
      <div className="muted small">{label}</div>
      <div className="stat-value">{value}</div>
    </div>
  )
}

function SettingsForm({ settings, onSaved }: { settings: ScraperSettings; onSaved: () => void }) {
  const [form, setForm] = useState(settings)
  useEffect(() => setForm(settings), [settings])
  const save = useMutation({
    mutationFn: () => api.put<ScraperSettings>('/admin/scraper/settings', form),
    onSuccess: onSaved,
  })
  const set = <K extends keyof ScraperSettings>(k: K, v: ScraperSettings[K]) => setForm({ ...form, [k]: v })
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  const dirty = JSON.stringify(form) !== JSON.stringify(settings)

  return (
    <form className="card" onSubmit={onSubmit}>
      <h2>Schedule & limits</h2>
      <label className="check" style={{ marginBottom: '0.75rem' }}>
        <input type="checkbox" checked={form.enabled} onChange={(e) => set('enabled', e.target.checked)} />
        Scheduled updates enabled
      </label>
      <Field label="Schedule (cron: minute hour day month weekday)">
        <input value={form.cron} onChange={(e) => set('cron', e.target.value)} />
      </Field>
      <div className="row small muted" style={{ marginTop: '-0.3rem', marginBottom: '0.6rem' }}>
        Presets:
        {[
          ['Daily 3am', '0 3 * * *'],
          ['Weekly Sun 3am', '0 3 * * 0'],
          ['Twice weekly', '0 3 * * 0,3'],
          ['Monthly', '0 3 1 * *'],
        ].map(([label, cron]) => (
          <button key={cron} type="button" className="link" onClick={() => set('cron', cron)}>
            {label}
          </button>
        ))}
      </div>
      <div className="grid2">
        <Field label="Min delay between requests (s)">
          <input
            type="number"
            min={1}
            step={0.5}
            value={form.min_delay}
            onChange={(e) => set('min_delay', Number(e.target.value))}
          />
        </Field>
        <Field label="Max delay between requests (s)">
          <input
            type="number"
            min={1}
            step={0.5}
            value={form.max_delay}
            onChange={(e) => set('max_delay', Number(e.target.value))}
          />
        </Field>
        <Field label="Skip items priced within (hours)">
          <input
            type="number"
            min={0}
            value={form.min_hours_between_updates}
            onChange={(e) => set('min_hours_between_updates', Number(e.target.value))}
          />
        </Field>
        <Field label="Stop after N consecutive failures">
          <input
            type="number"
            min={1}
            value={form.max_consecutive_failures}
            onChange={(e) => set('max_consecutive_failures', Number(e.target.value))}
          />
        </Field>
        <Field label="User refresh cooldown (minutes)">
          <input
            type="number"
            min={0}
            value={form.user_refresh_cooldown_minutes}
            onChange={(e) => set('user_refresh_cooldown_minutes', Number(e.target.value))}
          />
        </Field>
      </div>
      <label className="check" style={{ marginBottom: '0.75rem' }}>
        <input
          type="checkbox"
          checked={form.backfill_history}
          onChange={(e) => set('backfill_history', e.target.checked)}
        />
        Backfill monthly price history from PriceCharting charts
      </label>
      <ErrorText error={save.error} />
      <button type="submit" disabled={!dirty || save.isPending}>
        Save settings
      </button>
    </form>
  )
}
