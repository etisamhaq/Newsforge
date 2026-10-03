import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { Session } from '@supabase/supabase-js'
import { api, clearKey, getStoredKey, getWorkspaceId, onUnauthorized, setWorkspaceId, storeKey } from './api'
import { appUrl, authMode, supabase } from './supabase'
import type { Me, RoleName, WorkspaceSummary } from './types'

const RANK: Record<RoleName, number> = { viewer: 1, editor: 2, admin: 3 }

export type AuthStatus = 'loading' | 'signedOut' | 'recovery' | 'noWorkspace' | 'ready'

interface AuthState {
  mode: typeof authMode
  status: AuthStatus
  me: Me | null
  /** Email of the signed-in person. */
  email: string | null
  /** The workspace every request is about, and the person's role in it. */
  workspace: WorkspaceSummary | null
  workspaces: WorkspaceSummary[]
  switchWorkspace: (id: number) => void
  createWorkspace: (name: string) => Promise<WorkspaceSummary>
  /** Re-read memberships (after renaming, deleting or leaving a workspace). */
  refreshWorkspaces: () => Promise<void>
  expired: boolean
  can: (role: RoleName) => boolean
  signIn: (email: string, password: string) => Promise<void>
  signUp: (email: string, password: string) => Promise<{ needsConfirmation: boolean }>
  sendPasswordReset: (email: string) => Promise<void>
  updatePassword: (password: string) => Promise<void>
  signInWithKey: (key: string, remember: boolean) => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

/** Supabase's error texts are written for developers; say what to do instead. */
function friendly(err: { message?: string; code?: string } | null): Error {
  const msg = err?.message ?? ''
  if (/invalid login credentials/i.test(msg)) return new Error('That email and password don’t match. Check them and try again.')
  if (/email not confirmed/i.test(msg)) return new Error('Confirm your email first: open the link we sent you, then sign in.')
  if (/password should be at least/i.test(msg)) return new Error('Use a password with at least 8 characters.')
  if (err?.code === 'over_email_send_rate_limit' || /email rate limit/i.test(msg))
    return new Error(
      'We couldn’t send the confirmation email because the email service has reached its hourly limit. Try again later, or ask your Newsforge admin to check the email settings.',
    )
  if (/rate limit|too many/i.test(msg)) return new Error('Too many attempts. Wait a few minutes and try again.')
  if (/same password|different from the old/i.test(msg)) return new Error('Choose a password you haven’t used before.')
  return new Error(msg || 'Something went wrong. Try again.')
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [session, setSession] = useState<Session | null>(null)
  const [sessionLoaded, setSessionLoaded] = useState(authMode === 'apikey')
  const [recovery, setRecovery] = useState(false)
  const [apiKey, setApiKey] = useState<string | null>(() => (authMode === 'apikey' ? getStoredKey() : null))
  const [expired, setExpired] = useState(false)
  const [selectedId, setSelectedId] = useState<number | null>(() => getWorkspaceId())

  useEffect(() => {
    if (!supabase) return
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session)
      setSessionLoaded(true)
    })
    const { data } = supabase.auth.onAuthStateChange((event, next) => {
      if (event === 'PASSWORD_RECOVERY') setRecovery(true)
      setSession(next)
    })
    return () => data.subscription.unsubscribe()
  }, [])

  const identity = authMode === 'accounts' ? session?.user.id ?? null : apiKey
  const meQuery = useQuery({
    queryKey: ['me', identity],
    queryFn: api.me,
    enabled: Boolean(identity) && !recovery,
    staleTime: 60_000,
    retry: false,
  })

  const signOut = useCallback(async () => {
    if (supabase) await supabase.auth.signOut()
    clearKey()
    setWorkspaceId(null)
    setSelectedId(null)
    setApiKey(null)
    setRecovery(false)
    queryClient.clear()
  }, [queryClient])

  useEffect(() => {
    onUnauthorized(() => {
      setExpired(true)
      void signOut()
    })
  }, [signOut])

  const workspaces = useMemo(() => meQuery.data?.workspaces ?? [], [meQuery.data])
  const workspace = workspaces.find((w) => w.id === selectedId) ?? workspaces[0] ?? null

  // Keep the request header in step with the workspace on screen.
  if (workspace && getWorkspaceId() !== workspace.id) setWorkspaceId(workspace.id)

  const status: AuthStatus = !sessionLoaded
    ? 'loading'
    : recovery
      ? 'recovery'
      : !identity
        ? 'signedOut'
        : meQuery.data
          ? workspace
            ? 'ready'
            : 'noWorkspace'
          : meQuery.error
            ? 'signedOut'
            : 'loading'

  const switchWorkspace = useCallback(
    (id: number) => {
      setWorkspaceId(id)
      setSelectedId(id)
      // Drop everything cached for the previous workspace; screens refetch for the new one.
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'me' })
    },
    [queryClient],
  )

  const refreshWorkspaces = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ['me'] })
  }, [queryClient])

  const createWorkspace = useCallback(
    async (name: string) => {
      const ws = await api.createWorkspace(name)
      await queryClient.invalidateQueries({ queryKey: ['me'] })
      switchWorkspace(ws.id)
      return ws
    },
    [queryClient, switchWorkspace],
  )

  const signIn = useCallback(async (email: string, password: string) => {
    if (!supabase) throw new Error('Account sign-in is not configured.')
    const { error } = await supabase.auth.signInWithPassword({ email: email.trim(), password })
    if (error) throw friendly(error)
    setExpired(false)
  }, [])

  const signUp = useCallback(async (email: string, password: string) => {
    if (!supabase) throw new Error('Account sign-in is not configured.')
    const { data, error } = await supabase.auth.signUp({
      email: email.trim(),
      password,
      options: { emailRedirectTo: appUrl() },
    })
    if (error) throw friendly(error)
    return { needsConfirmation: !data.session }
  }, [])

  const sendPasswordReset = useCallback(async (email: string) => {
    if (!supabase) throw new Error('Account sign-in is not configured.')
    const { error } = await supabase.auth.resetPasswordForEmail(email.trim(), { redirectTo: appUrl() })
    if (error) throw friendly(error)
  }, [])

  const updatePassword = useCallback(async (password: string) => {
    if (!supabase) throw new Error('Account sign-in is not configured.')
    const { error } = await supabase.auth.updateUser({ password })
    if (error) throw friendly(error)
    setRecovery(false)
  }, [])

  const signInWithKey = useCallback(async (key: string, remember: boolean) => {
    await api.verifyKey(key) // throws ApiError(401) for a wrong key
    storeKey(key, remember)
    setExpired(false)
    setApiKey(key)
  }, [])

  const me = meQuery.data ?? null
  const value = useMemo<AuthState>(
    () => ({
      mode: authMode,
      status,
      me,
      email: me?.email ?? session?.user.email ?? null,
      workspace,
      workspaces,
      switchWorkspace,
      createWorkspace,
      refreshWorkspaces,
      expired,
      can: (role) => (workspace ? RANK[workspace.role] >= RANK[role] : false),
      signIn,
      signUp,
      sendPasswordReset,
      updatePassword,
      signInWithKey,
      signOut,
    }),
    [status, me, session, workspace, workspaces, switchWorkspace, createWorkspace, refreshWorkspaces, expired,
     signIn, signUp, sendPasswordReset, updatePassword, signInWithKey, signOut],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
