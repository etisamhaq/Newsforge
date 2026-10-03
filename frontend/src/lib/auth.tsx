import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, clearKey, getStoredKey, onUnauthorized, storeKey } from './api'

interface AuthState {
  apiKey: string | null
  signIn: (key: string, remember: boolean) => Promise<void>
  signOut: () => void
  expired: boolean
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [apiKey, setApiKey] = useState<string | null>(() => getStoredKey())
  const [expired, setExpired] = useState(false)
  const queryClient = useQueryClient()

  const signOut = useCallback(() => {
    clearKey()
    setApiKey(null)
    queryClient.clear()
  }, [queryClient])

  useEffect(() => {
    onUnauthorized(() => {
      setExpired(true)
      signOut()
    })
  }, [signOut])

  const signIn = useCallback(async (key: string, remember: boolean) => {
    await api.verifyKey(key) // throws ApiError(401) for a wrong key
    storeKey(key, remember)
    setExpired(false)
    setApiKey(key)
  }, [])

  const value = useMemo(() => ({ apiKey, signIn, signOut, expired }), [apiKey, signIn, signOut, expired])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
