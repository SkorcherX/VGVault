import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { api, parseUtc } from '../api'
import { ErrorText, Field } from '../components'

interface BackupSettings {
  enabled: boolean
  cron: string
  keep: number
}

interface BackupStatus {
  supported: boolean
  settings: BackupSettings
  next_run_at: string | null
  directory: string
  backups: { name: string; size: number; created_at: string }[]
}

const size = (b: number) => (b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.ceil(b / 1e3)} KB`)

export default function BackupsPage() {
  const qc = useQueryClient()
  const status = useQuery({ queryKey: ['backups'], queryFn: () => api.get<BackupStatus>('/admin/backups') })
  const refresh = () => qc.invalidateQueries({ queryKey: ['backups'] })
  const create = useMutation({ mutationFn: () => api.post('/admin/backups'), onSuccess: refresh })
  const remove = useMutation({ mutationFn: (name: string) => api.del(`/admin/backups/${name}`), onSuccess: refresh })
  const s = status.data

  return (
    <div className="page">
      <div className="page-head">
        <h1>Backups</h1>
        <div className="spacer" />
        <button onClick={() => create.mutate()} disabled={!s?.supported || create.isPending}>
          {create.isPending ? 'Backing up…' : 'Back up now'}
        </button>
      </div>
      <ErrorText error={status.error ?? create.error ?? remove.error} />
      {s && !s.supported && (
        <p className="error">Built-in backups only support SQLite. Back up Postgres with pg_dump.</p>
      )}
      {s && (
        <div className="two-col">
          <SettingsForm settings={s.settings} nextRun={s.next_run_at} onSaved={refresh} />
          <div className="card">
            <h2>Saved backups</h2>
            <p className="muted small">
              Stored in <code>{s.directory}</code>. To restore: stop the container, replace{' '}
              <code>vgvault.db</code> in <code>/config</code> with a backup file (renamed to{' '}
              <code>vgvault.db</code>), delete any <code>vgvault.db-wal</code> / <code>-shm</code> files, then start it
              again.
            </p>
            {s.backups.length === 0 ? (
              <p className="muted">No backups yet.</p>
            ) : (
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>File</th>
                      <th>Created</th>
                      <th className="num">Size</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {s.backups.map((b) => (
                      <tr key={b.name}>
                        <td>{b.name}</td>
                        <td>{parseUtc(b.created_at).toLocaleString()}</td>
                        <td className="num">{size(b.size)}</td>
                        <td className="actions">
                          <a className="link" href={`/api/admin/backups/${b.name}`} download>
                            Download
                          </a>
                          <button
                            className="ghost danger"
                            onClick={() => confirm(`Delete ${b.name}?`) && remove.mutate(b.name)}
                          >
                            Delete
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function SettingsForm({
  settings,
  nextRun,
  onSaved,
}: {
  settings: BackupSettings
  nextRun: string | null
  onSaved: () => void
}) {
  const [form, setForm] = useState(settings)
  useEffect(() => setForm(settings), [settings])
  const save = useMutation({ mutationFn: () => api.put('/admin/backups/settings', form), onSuccess: onSaved })
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }
  return (
    <form className="card" onSubmit={onSubmit}>
      <h2>Schedule</h2>
      <label className="check" style={{ marginBottom: '0.75rem' }}>
        <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} />
        Automatic backups
      </label>
      <Field label="Schedule (cron)">
        <input value={form.cron} onChange={(e) => setForm({ ...form, cron: e.target.value })} />
      </Field>
      <Field label="Keep the newest">
        <input
          type="number"
          min={1}
          max={365}
          value={form.keep}
          onChange={(e) => setForm({ ...form, keep: Number(e.target.value) })}
        />
      </Field>
      <p className="muted small">
        Next backup: {settings.enabled && nextRun ? parseUtc(nextRun).toLocaleString() : '—'}
      </p>
      <ErrorText error={save.error} />
      <button type="submit" disabled={save.isPending || JSON.stringify(form) === JSON.stringify(settings)}>
        Save
      </button>
    </form>
  )
}
