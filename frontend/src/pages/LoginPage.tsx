import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, type User } from '../api'
import { ErrorText, Field } from '../components'
import Logo from '../Logo'

export default function LoginPage({ allowRegistration }: { allowRegistration: boolean }) {
  const qc = useQueryClient()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const submit = useMutation({
    mutationFn: () =>
      api.post<User>(mode === 'login' ? '/auth/login' : '/auth/register', { username, password }),
    onSuccess: (user) => qc.setQueryData(['me'], user),
  })

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    submit.mutate()
  }

  return (
    <div className="center">
      <form className="card auth" onSubmit={onSubmit}>
        <h1>
          <Logo />
          <span>
            <span className="vg">VG</span>Vault
          </span>
        </h1>
        <Field label="Username">
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus required />
        </Field>
        <Field label="Password">
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </Field>
        <ErrorText error={submit.error} />
        <button type="submit" disabled={submit.isPending}>
          {mode === 'login' ? 'Log in' : 'Create account'}
        </button>
        {allowRegistration && (
          <button
            type="button"
            className="link"
            onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
          >
            {mode === 'login' ? 'Need an account? Register' : 'Have an account? Log in'}
          </button>
        )}
      </form>
    </div>
  )
}
