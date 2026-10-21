/**
 * Route guard: only render the app for a signed-in user.
 *
 * While the session is being restored this shows a loading state rather than
 * redirecting, because redirecting too early would bounce a signed-in user to
 * the login page on every refresh.
 */

import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { LoadingState } from './States'
import { useAuth } from '../auth/AuthContext'

export function RequireAuth() {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <LoadingState label="Signing you in…" />
      </div>
    )
  }

  if (!user) {
    // Remember where they were going, so sign-in can return them there.
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return <Outlet />
}
