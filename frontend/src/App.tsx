/**
 * The application root: providers, routing, and layout.
 *
 * Route structure
 * ---------------
 *   /login                public (redirects away if already signed in)
 *   /dashboard            protected
 *   /residents            protected
 *   /residents/:id        protected (detail, with its own tabs)
 *   /alerts               protected
 *   /                      redirects to /dashboard (which redirects to /login
 *                          if no session exists)
 *   *                      a real "not found" page, not a blank screen
 *
 * `RequireAuth` wraps the protected routes and renders `AppLayout` inside
 * itself, so the header/navigation only appears for a signed-in user — a
 * signed-out visitor never briefly sees a nav bar they cannot use.
 *
 * The order of the providers matters: `BrowserRouter` must be outside
 * `AuthProvider` because the auth provider is not the only thing that may need
 * to navigate, and `AuthProvider` must be inside the router before any page
 * reads `useAuth`.
 */

import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { AuthProvider } from './auth/AuthContext'
import { AppLayout } from './components/AppLayout'
import { RequireAuth } from './components/RequireAuth'
import { EmptyState } from './components/States'
import { AlertsPage } from './pages/AlertsPage'
import { DashboardPage } from './pages/DashboardPage'
import { LoginPage } from './pages/LoginPage'
import { ResidentDetailPage } from './pages/ResidentDetailPage'
import { ResidentsPage } from './pages/ResidentsPage'

/** Shown for a URL that matches no route. */
function NotFoundPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <EmptyState
        icon="🧭"
        title="Page not found"
        description="The address you followed does not match any page in this application."
        action={
          <a href="/dashboard" className="btn-primary">
            Go to the dashboard
          </a>
        }
      />
    </div>
  )
}

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          {/* Public. */}
          <Route path="/login" element={<LoginPage />} />

          {/* Protected: RequireAuth gates these and renders the shell. */}
          <Route element={<RequireAuth />}>
            <Route element={<AppLayout />}>
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/residents" element={<ResidentsPage />} />
              <Route path="/residents/:id" element={<ResidentDetailPage />} />
              <Route path="/alerts" element={<AlertsPage />} />
            </Route>
          </Route>

          {/* Root and unknown paths. */}
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
