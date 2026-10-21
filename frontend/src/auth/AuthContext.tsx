/**
 * Authentication state for the whole app.
 *
 * This provider answers three questions for the rest of the UI:
 *   1. Is somebody signed in? (`user`)
 *   2. Are we still finding out? (`loading` — the token is being checked)
 *   3. How do I sign in or out? (`signIn`, `signOut`)
 *
 * It also registers the "token was rejected" handler, so that when the server
 * returns a 401 on any later request the user is signed out and sent back to
 * the sign-in page rather than left staring at a broken screen.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { api } from '../api/client'
import { setUnauthorizedHandler } from '../api/http'
import { ApiError } from '../api/errors'
import { clearToken, getToken, setToken } from '../api/token'
import type { LoginPayload, RegisterPayload, User } from '../api/types'

interface AuthState {
  user: User | null
  /** True while we are checking whether an existing token is still valid. */
  loading: boolean
  signIn: (payload: LoginPayload) => Promise<void>
  signUp: (payload: RegisterPayload) => Promise<void>
  signOut: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const signOut = useCallback(() => {
    clearToken()
    setUser(null)
  }, [])

  // Ask the API who we are, if we already hold a token. This is what makes a
  // page refresh keep you signed in.
  useEffect(() => {
    let cancelled = false

    async function restoreSession() {
      if (!getToken()) {
        setLoading(false)
        return
      }
      try {
        const current = await api.me()
        if (!cancelled) setUser(current)
      } catch (error) {
        // Any failure here means the stored token is no longer usable. Being
        // signed out is the correct, honest outcome — do not keep a token we
        // cannot prove is valid.
        if (!cancelled && error instanceof ApiError) {
          clearToken()
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void restoreSession()
    return () => {
      cancelled = true
    }
  }, [])

  // Wire the global 401 handler to the sign-out action.
  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null))
    return () => setUnauthorizedHandler(null)
  }, [])

  const signIn = useCallback(async (payload: LoginPayload) => {
    const result = await api.login(payload)
    setToken(result.access_token)
    setUser(result.user)
  }, [])

  const signUp = useCallback(async (payload: RegisterPayload) => {
    const result = await api.register(payload)
    setToken(result.access_token)
    setUser(result.user)
  }, [])

  const value = useMemo<AuthState>(
    () => ({ user, loading, signIn, signUp, signOut }),
    [user, loading, signIn, signUp, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

/** Access the authentication state. Throws if used outside `AuthProvider`. */
export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used inside an <AuthProvider>.')
  }
  return context
}
