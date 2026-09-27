import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, type User } from '../api'
import { ErrorText, Field } from '../components'
import Logo from '../Logo'

export default function SetupPage() {
  const qc = useQueryClient()
  const [form, setForm] = useState({ username: '', email: '', password: '', confirm: '' })
  const [error, setError] = useState<string | null>(null)
  const setup = useMutation({
    mutationFn: () =>
      api.post<User>('/setup', {
        username: form.username,
        email: form.email || null,
        password: form.password,
      }),
    onSuccess: (user) => {
      qc.setQueryData(['me'], user)
      qc.setQueryData(['setup'], { needs_setup: false, allow_registration: false })
      qc.invalidateQueries({ queryKey: ['setup'] })
    },
  })

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (form.password !== form.confirm) return setError('Passwords do not match')
    setError(null)
    setup.mutate()
  }
  const bind = (key: keyof typeof form) => ({
    value: form[key],
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [key]: e.target.value }),
  })

  return (
    <div className="center">
      <form className="card auth" onSubmit={onSubmit}>
        <h1>
          <Logo />
          <span>
            Welcome to <span className="vg">VG</span>Vault
          </span>
        </h1>
        <p className="muted">Create the administrator account to get started.</p>
        <Field label="Username">
          <input {...bind('username')} autoFocus required minLength={3} />
        </Field>
        <Field label="Email (optional)">
          <input type="email" {...bind('email')} />
        </Field>
        <Field label="Password">
          <input type="password" {...bind('password')} required minLength={8} />
        </Field>
        <Field label="Confirm password">
          <input type="password" {...bind('confirm')} required />
        </Field>
        <ErrorText error={error ?? setup.error} />
        <button type="submit" disabled={setup.isPending}>
          Create admin
        </button>
      </form>
    </div>
  )
}
