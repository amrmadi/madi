/**
 * Sign-in and registration page.
 *
 * Both forms live here because they share the same layout and error handling.
 * The form validates locally first (so a caregiver gets an instant, specific
 * message) and still relies on the server for the rules it cannot know about,
 * such as "this email is already registered".
 */

import { useEffect, useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { ApiError, NetworkError } from '../api/errors'
import { useAuth } from '../auth/AuthContext'

type Mode = 'signin' | 'register'

export function LoginPage() {
  const { signIn, signUp, user } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [mode, setMode] = useState<Mode>('signin')
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  // Where to go after signing in (set by RequireAuth when it redirected here).
  const from = (location.state as { from?: string } | null)?.from ?? '/dashboard'

  // If already signed in (e.g. the token was restored), do not show this page.
  // This must run in an effect, not during render: calling navigate() while
  // rendering makes React update a different component mid-render, which warns
  // "Cannot update a component (BrowserRouter) while rendering a different
  // component (LoginPage)".
  useEffect(() => {
    if (user) {
      navigate(from, { replace: true })
    }
  }, [user, from, navigate])

  /** A few checks we can do without asking the server. */
  function validate(): Record<string, string> {
    const problems: Record<string, string> = {}

    if (!email.trim()) {
      problems.email = 'Please enter your email address.'
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      problems.email = 'That does not look like an email address.'
    }

    if (!password) {
      problems.password = 'Please enter your password.'
    } else if (mode === 'register' && password.length < 8) {
      problems.password = 'Use at least 8 characters.'
    }

    if (mode === 'register' && !displayName.trim()) {
      problems.displayName = 'Please enter a name to display.'
    }

    return problems
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)

    const problems = validate()
    setFieldErrors(problems)
    if (Object.keys(problems).length > 0) return

    setSubmitting(true)
    try {
      if (mode === 'signin') {
        await signIn({ email: email.trim(), password })
      } else {
        await signUp({
          email: email.trim(),
          display_name: displayName.trim(),
          password,
        })
      }
      navigate(from, { replace: true })
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message)
        // Surface per-field problems from the server too.
        const mapped: Record<string, string> = {}
        for (const field of caught.fields) {
          mapped[field.field] = field.message
        }
        setFieldErrors(mapped)
      } else if (caught instanceof NetworkError) {
        setError(caught.message)
      } else {
        setError('Something unexpected went wrong. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  function switchMode(next: Mode) {
    setMode(next)
    setError(null)
    setFieldErrors({})
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-12">
      <div className="w-full max-w-lg">
        <div className="mb-8 text-center">
          <span className="text-5xl" aria-hidden="true">
            🏡
          </span>
          <h1 className="mt-3 text-brand-800">ElderLife AI</h1>
          <p className="mt-2 text-slate-600">
            A monitoring dashboard to help caregivers look after elderly people
            at home.
          </p>
        </div>

        <div className="card">
          {/* Mode switch, styled as two clear buttons rather than a small link. */}
          <div className="mb-6 flex gap-2" role="tablist" aria-label="Choose sign in or register">
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'signin'}
              className={mode === 'signin' ? 'btn-primary flex-1' : 'btn-secondary flex-1'}
              onClick={() => switchMode('signin')}
            >
              Sign in
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'register'}
              className={mode === 'register' ? 'btn-primary flex-1' : 'btn-secondary flex-1'}
              onClick={() => switchMode('register')}
            >
              Create account
            </button>
          </div>

          <form onSubmit={handleSubmit} noValidate>
            {error && (
              <div
                className="mb-5 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-red-900"
                role="alert"
              >
                {error}
              </div>
            )}

            {mode === 'register' && (
              <div className="mb-5">
                <label className="field-label" htmlFor="displayName">
                  Your name
                </label>
                <input
                  id="displayName"
                  className="field-input"
                  type="text"
                  autoComplete="name"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  aria-invalid={Boolean(fieldErrors.displayName)}
                  aria-describedby={fieldErrors.displayName ? 'displayName-error' : undefined}
                />
                {fieldErrors.displayName && (
                  <p className="field-error" id="displayName-error">
                    {fieldErrors.displayName}
                  </p>
                )}
              </div>
            )}

            <div className="mb-5">
              <label className="field-label" htmlFor="email">
                Email address
              </label>
              <input
                id="email"
                className="field-input"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                aria-invalid={Boolean(fieldErrors.email)}
                aria-describedby={fieldErrors.email ? 'email-error' : undefined}
              />
              {fieldErrors.email && (
                <p className="field-error" id="email-error">
                  {fieldErrors.email}
                </p>
              )}
            </div>

            <div className="mb-6">
              <label className="field-label" htmlFor="password">
                Password
              </label>
              <input
                id="password"
                className="field-input"
                type="password"
                autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                aria-invalid={Boolean(fieldErrors.password)}
                aria-describedby={fieldErrors.password ? 'password-error' : 'password-hint'}
              />
              {mode === 'register' && !fieldErrors.password && (
                <p className="field-hint" id="password-hint">
                  At least 8 characters.
                </p>
              )}
              {fieldErrors.password && (
                <p className="field-error" id="password-error">
                  {fieldErrors.password}
                </p>
              )}
            </div>

            <button type="submit" className="btn-primary w-full" disabled={submitting}>
              {submitting
                ? mode === 'signin'
                  ? 'Signing in…'
                  : 'Creating account…'
                : mode === 'signin'
                  ? 'Sign in'
                  : 'Create account'}
            </button>
          </form>

          <p className="mt-6 border-t border-slate-200 pt-4 text-base text-slate-600">
            New accounts are created as <strong>caregivers</strong>. Administrator
            accounts are set up separately, so nobody can grant themselves extra
            access.
          </p>
        </div>

        <p className="mt-6 text-center text-base text-slate-500">
          This is a graduation project running locally. Do not enter real
          personal or medical information.
        </p>
      </div>
    </div>
  )
}
