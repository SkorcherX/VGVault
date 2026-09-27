import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, type Role, type User } from '../api'
import { ErrorText, Field, Modal } from '../components'

export default function UsersPage({ me }: { me: User }) {
  const qc = useQueryClient()
  const users = useQuery({ queryKey: ['users'], queryFn: () => api.get<User[]>('/users') })
  const [creating, setCreating] = useState(false)
  const [resetting, setResetting] = useState<User | null>(null)
  const refresh = () => qc.invalidateQueries({ queryKey: ['users'] })

  const update = useMutation({
    mutationFn: ({ id, ...body }: Partial<User> & { id: number; password?: string }) =>
      api.patch(`/users/${id}`, body),
    onSuccess: refresh,
  })
  const remove = useMutation({ mutationFn: (id: number) => api.del(`/users/${id}`), onSuccess: refresh })

  return (
    <div className="page">
      <div className="page-head">
        <h1>Users</h1>
        <button onClick={() => setCreating(true)}>+ Add user</button>
      </div>
      <ErrorText error={update.error ?? remove.error} />
      <table className="table">
        <thead>
          <tr>
            <th>Username</th>
            <th>Email</th>
            <th>Role</th>
            <th>Active</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {users.data?.map((u) => (
            <tr key={u.id}>
              <td>{u.username}</td>
              <td>{u.email ?? '—'}</td>
              <td>
                <select
                  value={u.role}
                  onChange={(e) => update.mutate({ id: u.id, role: e.target.value as Role })}
                >
                  <option value="user">user</option>
                  <option value="admin">admin</option>
                </select>
              </td>
              <td>
                <input
                  type="checkbox"
                  checked={u.is_active}
                  disabled={u.id === me.id}
                  onChange={(e) => update.mutate({ id: u.id, is_active: e.target.checked })}
                />
              </td>
              <td className="actions">
                <button className="ghost" onClick={() => setResetting(u)}>
                  Reset password
                </button>
                {u.id !== me.id && (
                  <button
                    className="ghost danger"
                    onClick={() =>
                      confirm(`Delete ${u.username} and their entire collection?`) && remove.mutate(u.id)
                    }
                  >
                    Delete
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {creating && <CreateUser onClose={() => setCreating(false)} onDone={refresh} />}
      {resetting && (
        <ResetPassword
          user={resetting}
          onClose={() => setResetting(null)}
          onSubmit={(password) => update.mutateAsync({ id: resetting.id, password })}
        />
      )}
    </div>
  )
}

function CreateUser({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({ username: '', email: '', password: '', role: 'user' as Role })
  const create = useMutation({
    mutationFn: () => api.post('/users', { ...form, email: form.email || null }),
    onSuccess: () => {
      onDone()
      onClose()
    },
  })
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    create.mutate()
  }
  return (
    <Modal title="Add user" onClose={onClose}>
      <form onSubmit={onSubmit}>
        <Field label="Username">
          <input
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })}
            required
            minLength={3}
          />
        </Field>
        <Field label="Email">
          <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </Field>
        <Field label="Password">
          <input
            type="password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            required
            minLength={8}
          />
        </Field>
        <Field label="Role">
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
            <option value="user">user</option>
            <option value="admin">admin</option>
          </select>
        </Field>
        <ErrorText error={create.error} />
        <button type="submit" disabled={create.isPending}>
          Create
        </button>
      </form>
    </Modal>
  )
}

function ResetPassword({
  user,
  onClose,
  onSubmit,
}: {
  user: User
  onClose: () => void
  onSubmit: (password: string) => Promise<unknown>
}) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(null)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    try {
      await onSubmit(password)
      onClose()
    } catch (err) {
      setError(err)
    }
  }
  return (
    <Modal title={`Reset password — ${user.username}`} onClose={onClose}>
      <form onSubmit={submit}>
        <Field label="New password">
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            autoFocus
          />
        </Field>
        <p className="muted">This signs the user out of all sessions.</p>
        <ErrorText error={error} />
        <button type="submit">Reset</button>
      </form>
    </Modal>
  )
}
