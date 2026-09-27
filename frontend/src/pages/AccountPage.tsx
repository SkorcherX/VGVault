import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, type User } from '../api'
import { ErrorText, Field } from '../components'

export default function AccountPage({ user }: { user: User }) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const change = useMutation({
    mutationFn: () => api.post('/auth/change-password', { current_password: current, new_password: next }),
    onSuccess: () => {
      setCurrent('')
      setNext('')
    },
  })

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    change.mutate()
  }

  return (
    <div className="page narrow">
      <h1>Account</h1>
      <p className="muted">
        Signed in as <strong>{user.username}</strong> ({user.role})
      </p>
      <form className="card" onSubmit={onSubmit}>
        <h2>Change password</h2>
        <Field label="Current password">
          <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        </Field>
        <Field label="New password">
          <input
            type="password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            required
            minLength={8}
          />
        </Field>
        <ErrorText error={change.error} />
        {change.isSuccess && <p className="ok">Password changed.</p>}
        <button type="submit" disabled={change.isPending}>
          Update password
        </button>
      </form>
    </div>
  )
}
