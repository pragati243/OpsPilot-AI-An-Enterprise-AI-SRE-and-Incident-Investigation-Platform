import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import * as api from './api'
import type { User } from './types'

const STORAGE_KEY = 'opspilot.tokens'

interface StoredTokens {
  accessToken: string
  refreshToken: string
}

interface AuthState {
  user: User | null
  accessToken: string | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

function readStoredTokens(): StoredTokens | null {
  const raw = localStorage.getItem(STORAGE_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as StoredTokens
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [accessToken, setAccessToken] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const stored = readStoredTokens()
    if (!stored) {
      setLoading(false)
      return
    }
    api
      .getMe(stored.accessToken)
      .then((me) => {
        setUser(me)
        setAccessToken(stored.accessToken)
      })
      .catch(() => {
        // Expired/invalid — this app doesn't implement silent refresh;
        // a demo-scale simplification, not an oversight. The user just
        // logs in again.
        localStorage.removeItem(STORAGE_KEY)
      })
      .finally(() => setLoading(false))
  }, [])

  const login = async (email: string, password: string) => {
    const tokens = await api.login(email, password)
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token }),
    )
    const me = await api.getMe(tokens.access_token)
    setUser(me)
    setAccessToken(tokens.access_token)
  }

  const logout = () => {
    localStorage.removeItem(STORAGE_KEY)
    setUser(null)
    setAccessToken(null)
  }

  const value = useMemo(
    () => ({ user, accessToken, loading, login, logout }),
    [user, accessToken, loading],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within an AuthProvider')
  return context
}
