import { useState, type FormEvent } from 'react'
import { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'

export function Login() {
  const { signIn, expired } = useAuth()
  const [key, setKey] = useState('')
  const [remember, setRemember] = useState(false)
  const [error, setError] = useState<string | null>(expired ? 'Your session ended. Sign in again with your API key.' : null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await signIn(key.trim(), remember)
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? 'That API key was not accepted. Check it and try again.'
          : err instanceof Error
            ? err.message
            : 'Could not sign in.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="login">
      <div className="login-panel">
        <p className="wordmark wordmark-large">
          <span className="wordmark-mark" aria-hidden="true">
            N
          </span>
          Newsforge
        </p>
        <h1>Sign in</h1>
        <p className="muted">Use the API key set as API_KEY on your Newsforge server.</p>
        <form onSubmit={submit} className="form">
          {error && (
            <p className="notice notice-error" role="alert">
              {error}
            </p>
          )}
          <div className="field">
            <label htmlFor="api-key">API key</label>
            <input
              id="api-key"
              type="password"
              autoComplete="current-password"
              required
              value={key}
              onChange={(e) => setKey(e.target.value)}
            />
          </div>
          <label className="check">
            <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
            Stay signed in on this device
          </label>
          <button type="submit" className="btn btn-primary btn-block" disabled={busy || !key.trim()}>
            {busy ? 'Checking…' : 'Sign in'}
          </button>
        </form>
      </div>
    </main>
  )
}
