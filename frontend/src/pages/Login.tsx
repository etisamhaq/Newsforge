import { useState, type FormEvent, type ReactNode } from 'react'
import { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'

function AuthShell({ title, intro, children }: { title: string; intro?: ReactNode; children: ReactNode }) {
  return (
    <main className="login">
      <div className="login-panel">
        <p className="wordmark wordmark-large">
          <span className="wordmark-mark" aria-hidden="true">
            N
          </span>
          Newsforge
        </p>
        <h1>{title}</h1>
        {intro && <p className="muted">{intro}</p>}
        {children}
      </div>
    </main>
  )
}

function useSubmit() {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Try again.')
    } finally {
      setBusy(false)
    }
  }
  return { error, setError, busy, run }
}

const MIN_PASSWORD = 8

type View = 'signIn' | 'signUp' | 'forgot' | 'checkEmail' | 'resetSent'

function AccountSignIn() {
  const { signIn, signUp, sendPasswordReset, expired } = useAuth()
  const [view, setView] = useState<View>('signIn')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const { error, setError, busy, run } = useSubmit()

  const go = (next: View) => {
    setError(null)
    setPassword('')
    setView(next)
  }

  if (view === 'checkEmail') {
    return (
      <AuthShell title="Check your email" intro={<>We sent a confirmation link to <strong>{email}</strong>. Open it on this device to finish creating your account.</>}>
        <p className="muted auth-note">After confirming, an admin still needs to add you to the team before you can see anything.</p>
        <button type="button" className="btn btn-quiet btn-block" onClick={() => go('signIn')}>
          Back to sign in
        </button>
      </AuthShell>
    )
  }
  if (view === 'resetSent') {
    return (
      <AuthShell title="Check your email" intro={<>If <strong>{email}</strong> has an account, we sent it a link to choose a new password.</>}>
        <button type="button" className="btn btn-quiet btn-block" onClick={() => go('signIn')}>
          Back to sign in
        </button>
      </AuthShell>
    )
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      if (view === 'signIn') await signIn(email, password)
      else if (view === 'signUp') {
        if (password.length < MIN_PASSWORD) throw new Error(`Use a password with at least ${MIN_PASSWORD} characters.`)
        const { needsConfirmation } = await signUp(email, password)
        if (needsConfirmation) setView('checkEmail')
      } else {
        await sendPasswordReset(email)
        setView('resetSent')
      }
    })
  }

  const titles: Record<'signIn' | 'signUp' | 'forgot', [string, string]> = {
    signIn: ['Sign in', 'Use the email and password for your Newsforge account.'],
    signUp: ['Create your account', 'Use the email address an admin invited.'],
    forgot: ['Reset your password', 'We’ll email you a link to choose a new one.'],
  }
  const v = view as 'signIn' | 'signUp' | 'forgot'
  const action = { signIn: 'Sign in', signUp: 'Create account', forgot: 'Send reset link' }[v]

  return (
    <AuthShell title={titles[v][0]} intro={titles[v][1]}>
      <form onSubmit={submit} className="form">
        {(error || (expired && view === 'signIn')) && (
          <p className="notice notice-error" role="alert">
            {error ?? 'Your session ended. Sign in again.'}
          </p>
        )}
        <div className="field">
          <label htmlFor="auth-email">Email</label>
          <input id="auth-email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        {view !== 'forgot' && (
          <div className="field">
            <div className="label-row">
              <label htmlFor="auth-password">Password</label>
              {view === 'signIn' && (
                <button type="button" className="link-btn" onClick={() => go('forgot')}>
                  Forgot password?
                </button>
              )}
            </div>
            <input
              id="auth-password"
              type="password"
              autoComplete={view === 'signUp' ? 'new-password' : 'current-password'}
              required
              minLength={view === 'signUp' ? MIN_PASSWORD : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {view === 'signUp' && <p className="field-hint">At least {MIN_PASSWORD} characters.</p>}
          </div>
        )}
        <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
          {busy ? 'Please wait…' : action}
        </button>
      </form>
      <p className="auth-switch">
        {view === 'signIn' ? (
          <>
            New to Newsforge?{' '}
            <button type="button" className="link-btn" onClick={() => go('signUp')}>
              Create an account
            </button>
          </>
        ) : (
          <>
            Already have an account?{' '}
            <button type="button" className="link-btn" onClick={() => go('signIn')}>
              Sign in
            </button>
          </>
        )}
      </p>
    </AuthShell>
  )
}

function ApiKeySignIn() {
  const { signInWithKey, expired } = useAuth()
  const [key, setKey] = useState('')
  const [remember, setRemember] = useState(false)
  const { error, busy, run } = useSubmit()

  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      try {
        await signInWithKey(key.trim(), remember)
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) throw new Error('That API key was not accepted. Check it and try again.')
        throw err
      }
    })
  }

  return (
    <AuthShell title="Sign in" intro="Use the API key set as API_KEY on your Newsforge server.">
      <form onSubmit={submit} className="form">
        {(error || expired) && (
          <p className="notice notice-error" role="alert">
            {error ?? 'Your session ended. Sign in again with your API key.'}
          </p>
        )}
        <div className="field">
          <label htmlFor="api-key">API key</label>
          <input id="api-key" type="password" autoComplete="current-password" required value={key} onChange={(e) => setKey(e.target.value)} />
        </div>
        <label className="check">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          Stay signed in on this device
        </label>
        <button type="submit" className="btn btn-primary btn-block" disabled={busy || !key.trim()}>
          {busy ? 'Checking…' : 'Sign in'}
        </button>
      </form>
    </AuthShell>
  )
}

export function Login() {
  const { mode } = useAuth()
  return mode === 'accounts' ? <AccountSignIn /> : <ApiKeySignIn />
}

export function SetNewPassword() {
  const { updatePassword } = useAuth()
  const [password, setPassword] = useState('')
  const { error, busy, run } = useSubmit()
  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      if (password.length < MIN_PASSWORD) throw new Error(`Use a password with at least ${MIN_PASSWORD} characters.`)
      await updatePassword(password)
    })
  }
  return (
    <AuthShell title="Choose a new password" intro="You’ll stay signed in after saving it.">
      <form onSubmit={submit} className="form">
        {error && (
          <p className="notice notice-error" role="alert">
            {error}
          </p>
        )}
        <div className="field">
          <label htmlFor="new-password">New password</label>
          <input
            id="new-password"
            type="password"
            autoComplete="new-password"
            required
            minLength={MIN_PASSWORD}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <p className="field-hint">At least {MIN_PASSWORD} characters.</p>
        </div>
        <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
          {busy ? 'Saving…' : 'Save password'}
        </button>
      </form>
    </AuthShell>
  )
}

export function NoWorkspace() {
  const { email, signOut, createWorkspace } = useAuth()
  const [name, setName] = useState('')
  const { error, busy, run } = useSubmit()
  const submit = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      await createWorkspace(name)
    })
  }
  return (
    <AuthShell
      title="Create a workspace"
      intro={
        <>
          You’re signed in as <strong>{email}</strong> but aren’t in any workspace. Create one to start collecting news, or ask a
          teammate to invite this email to theirs.
        </>
      }
    >
      <form onSubmit={submit} className="form">
        {error && (
          <p className="notice notice-error" role="alert">
            {error}
          </p>
        )}
        <div className="field">
          <label htmlFor="ws-name">Workspace name</label>
          <input id="ws-name" required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} placeholder="Newsroom" />
        </div>
        <button type="submit" className="btn btn-primary btn-block" disabled={busy || !name.trim()}>
          {busy ? 'Creating…' : 'Create workspace'}
        </button>
      </form>
      <button type="button" className="btn btn-quiet btn-block auth-note" onClick={() => void signOut()}>
        Sign out
      </button>
    </AuthShell>
  )
}

export function AuthLoading() {
  return (
    <main className="login" aria-busy="true">
      <p className="muted">Loading…</p>
    </main>
  )
}
