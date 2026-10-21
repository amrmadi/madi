/**
 * Dashboard: an at-a-glance overview for the signed-in caregiver.
 *
 * Honesty rules applied on this page:
 *   * Every number is derived from real API responses. If the API returns
 *     nothing, the page says so — it never shows a placeholder figure that
 *     looks like a real one.
 *   * Alerts are counted from the alerts endpoint for the residents this
 *     caregiver can actually see.
 *   * When the backend's health check reports a problem, that is shown plainly
 *     instead of being hidden.
 */

import { Link } from 'react-router-dom'

import { api } from '../api/client'
import { useApi } from '../api/useApi'
import { useAuth } from '../auth/AuthContext'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { alertStatusClasses, formatDateTime, humanize, severityClasses } from '../components/format'

export function DashboardPage() {
  const { user } = useAuth()

  const health = useApi(() => api.health(), [])
  const profiles = useApi(() => api.listProfiles({ page_size: 100 }), [])
  const alerts = useApi(() => api.listAlerts({ page_size: 100 }), [])

  const openAlerts =
    alerts.data?.items.filter((a) => a.status === 'new' || a.status === 'acknowledged') ?? []

  return (
    <div className="space-y-8">
      <div>
        <h1>Welcome back, {user?.display_name}</h1>
        <p className="mt-2 text-slate-600">
          Here is what needs your attention today.
        </p>
      </div>

      {/* Backend status: shown honestly, including when it is degraded. */}
      {health.error ? (
        <ErrorState error={health.error} onRetry={health.reload} />
      ) : health.loading ? (
        <LoadingState label="Checking the server…" />
      ) : health.data ? (
        <div
          className={`rounded-xl border px-5 py-4 ${
            health.data.status === 'ok'
              ? 'border-green-300 bg-green-50 text-green-900'
              : 'border-amber-300 bg-amber-50 text-amber-900'
          }`}
          role="status"
        >
          <p className="font-semibold">
            {health.data.status === 'ok'
              ? 'Server connected'
              : 'Server reachable, but the database is not connected'}
          </p>
          <p className="text-base">
            Database: {health.data.database} · API version {health.data.version} ·
            environment {health.data.environment}
          </p>
        </div>
      ) : null}

      {/* Summary counts, all derived from real responses. */}
      <section aria-labelledby="summary-heading">
        <h2 id="summary-heading" className="sr-only">
          Summary
        </h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="card">
            <p className="text-base font-semibold text-slate-600">
              Residents you can access
            </p>
            {profiles.loading ? (
              <p className="mt-2 text-2xl font-bold text-slate-400">…</p>
            ) : profiles.error ? (
              <p className="mt-2 text-base text-red-700">Could not load</p>
            ) : (
              <p className="mt-2 text-4xl font-bold text-brand-700">
                {profiles.data?.total ?? 0}
              </p>
            )}
          </div>

          <div className="card">
            <p className="text-base font-semibold text-slate-600">Open alerts</p>
            {alerts.loading ? (
              <p className="mt-2 text-2xl font-bold text-slate-400">…</p>
            ) : alerts.error ? (
              <p className="mt-2 text-base text-red-700">Could not load</p>
            ) : (
              <p className="mt-2 text-4xl font-bold text-red-700">{openAlerts.length}</p>
            )}
          </div>
        </div>
      </section>

      {/* Recent alerts. */}
      <section aria-labelledby="alerts-heading" className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 id="alerts-heading">Recent alerts</h2>
          <Link to="/alerts" className="btn-secondary">
            View all alerts
          </Link>
        </div>

        {alerts.loading ? (
          <LoadingState label="Loading alerts…" />
        ) : alerts.error ? (
          <ErrorState error={alerts.error} onRetry={alerts.reload} />
        ) : openAlerts.length === 0 ? (
          <EmptyState
            icon="✅"
            title="No open alerts"
            description="Nothing needs your attention right now. New alerts will appear here."
          />
        ) : (
          <ul className="space-y-3">
            {openAlerts.slice(0, 5).map((alert) => (
              <li key={alert.id} className="card">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`rounded-full border px-3 py-1 text-sm font-semibold ${severityClasses(alert.severity)}`}
                      >
                        {humanize(alert.severity)}
                      </span>
                      <span
                        className={`rounded-full border px-3 py-1 text-sm font-semibold ${alertStatusClasses(alert.status)}`}
                      >
                        {humanize(alert.status)}
                      </span>
                    </div>
                    <h3 className="mt-2 text-lg font-semibold text-slate-900">
                      {alert.title}
                    </h3>
                    <p className="text-base text-slate-600">
                      {alert.elderly_profile_name ?? 'Unknown resident'} ·{' '}
                      {formatDateTime(alert.created_at)}
                    </p>
                  </div>
                  <Link to="/alerts" className="btn-secondary">
                    Review
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Quick access to residents. */}
      <section aria-labelledby="residents-heading" className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 id="residents-heading">Your residents</h2>
          <Link to="/residents" className="btn-secondary">
            View all residents
          </Link>
        </div>

        {profiles.loading ? (
          <LoadingState label="Loading residents…" />
        ) : profiles.error ? (
          <ErrorState error={profiles.error} onRetry={profiles.reload} />
        ) : (profiles.data?.items.length ?? 0) === 0 ? (
          <EmptyState
            icon="👥"
            title="No residents yet"
            description="You are not assigned to any resident. Create one, or ask an administrator to assign you."
            action={
              <Link to="/residents" className="btn-primary">
                Go to residents
              </Link>
            }
          />
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {profiles.data?.items.slice(0, 4).map((profile) => (
              <li key={profile.id} className="card">
                <Link
                  to={`/residents/${profile.id}`}
                  className="text-xl font-semibold text-brand-700 hover:underline"
                >
                  {profile.display_name}
                </Link>
                <p className="mt-1 text-base text-slate-600">
                  Room {profile.room_label ?? 'not set'}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
