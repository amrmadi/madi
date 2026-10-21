/**
 * Alerts page: everything that needs a caregiver's attention.
 *
 * The list is scoped by the backend to the residents this caregiver is assigned
 * to. Acknowledge and status changes go straight to the API — the page never
 * changes an alert's appearance without the server confirming the change, so
 * what you see always matches what is stored.
 */

import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import { ApiError } from '../api/errors'
import { useApi } from '../api/useApi'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import {
  alertStatusClasses,
  formatDateTime,
  humanize,
  severityClasses,
} from '../components/format'
import type { AlertStatus } from '../api/types'

const STATUS_FILTERS: Array<{ value: '' | AlertStatus; label: string }> = [
  { value: '', label: 'All' },
  { value: 'new', label: 'New' },
  { value: 'acknowledged', label: 'Acknowledged' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'dismissed', label: 'Dismissed' },
]

export function AlertsPage() {
  const [statusFilter, setStatusFilter] = useState<'' | AlertStatus>('')
  const [busyId, setBusyId] = useState<number | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const alerts = useApi(
    () =>
      api.listAlerts({
        page_size: 100,
        status: statusFilter || undefined,
      }),
    [statusFilter],
  )

  async function runAction(
    alertId: number,
    action: () => Promise<unknown>,
    failureMessage: string,
  ) {
    setBusyId(alertId)
    setActionError(null)
    try {
      await action()
      alerts.reload()
    } catch (caught) {
      setActionError(
        caught instanceof ApiError ? caught.message : failureMessage,
      )
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1>Alerts</h1>
        <p className="mt-2 text-slate-600">
          Alerts raised for the residents you look after.
        </p>
      </div>

      {/* Status filter. Buttons, not a dropdown: one tap, and the current
          choice is always visible. */}
      <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by status">
        {STATUS_FILTERS.map((filter) => (
          <button
            key={filter.value || 'all'}
            type="button"
            aria-pressed={statusFilter === filter.value}
            className={statusFilter === filter.value ? 'btn-primary' : 'btn-secondary'}
            onClick={() => setStatusFilter(filter.value)}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {actionError && (
        <div
          className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-red-900"
          role="alert"
        >
          {actionError}
        </div>
      )}

      {alerts.loading ? (
        <LoadingState label="Loading alerts…" />
      ) : alerts.error ? (
        <ErrorState error={alerts.error} onRetry={alerts.reload} />
      ) : (alerts.data?.items.length ?? 0) === 0 ? (
        <EmptyState
          icon="✅"
          title={statusFilter ? 'No alerts with that status' : 'No alerts'}
          description={
            statusFilter
              ? 'Try a different status filter to see other alerts.'
              : 'Nothing needs your attention right now. New alerts will appear here.'
          }
        />
      ) : (
        <ul className="space-y-4">
          {alerts.data?.items.map((alert) => {
            const isClosed = alert.status === 'resolved' || alert.status === 'dismissed'
            const busy = busyId === alert.id

            return (
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
                      <span className="text-base text-slate-500">
                        {humanize(alert.alert_type)}
                      </span>
                    </div>

                    <h2 className="mt-3 text-xl font-semibold text-slate-900">
                      {alert.title}
                    </h2>
                    {alert.message && (
                      <p className="mt-1 text-base text-slate-700">{alert.message}</p>
                    )}

                    <p className="mt-2 text-base text-slate-500">
                      {alert.elderly_profile_id !== null && (
                        <Link
                          to={`/residents/${alert.elderly_profile_id}`}
                          className="font-semibold text-brand-700 hover:underline"
                        >
                          {alert.elderly_profile_name ?? 'View resident'}
                        </Link>
                      )}
                      {' · raised '}
                      {formatDateTime(alert.created_at)}
                    </p>

                    {alert.acknowledged_at && (
                      <p className="mt-1 text-base text-slate-500">
                        Acknowledged {formatDateTime(alert.acknowledged_at)}
                        {alert.acknowledged_by_user_id !== null &&
                          ` by user #${alert.acknowledged_by_user_id}`}
                      </p>
                    )}
                    {alert.resolved_at && (
                      <p className="mt-1 text-base text-slate-500">
                        Resolved {formatDateTime(alert.resolved_at)}
                      </p>
                    )}
                  </div>

                  {/* Actions. Only valid transitions are offered, and the
                      backend re-checks every one of them. */}
                  <div className="flex flex-col gap-2">
                    {alert.status === 'new' && (
                      <button
                        type="button"
                        className="btn-primary"
                        disabled={busy}
                        onClick={() =>
                          runAction(
                            alert.id,
                            () => api.acknowledgeAlert(alert.id),
                            'Could not acknowledge the alert.',
                          )
                        }
                      >
                        {busy ? 'Working…' : 'Acknowledge'}
                      </button>
                    )}

                    {!isClosed && (
                      <button
                        type="button"
                        className="btn-secondary"
                        disabled={busy}
                        onClick={() =>
                          runAction(
                            alert.id,
                            () => api.updateAlertStatus(alert.id, 'resolved'),
                            'Could not resolve the alert.',
                          )
                        }
                      >
                        Mark resolved
                      </button>
                    )}

                    {!isClosed && (
                      <button
                        type="button"
                        className="btn-secondary"
                        disabled={busy}
                        onClick={() =>
                          runAction(
                            alert.id,
                            () => api.updateAlertStatus(alert.id, 'dismissed'),
                            'Could not dismiss the alert.',
                          )
                        }
                      >
                        Dismiss
                      </button>
                    )}

                    {isClosed && (
                      <span className="text-base text-slate-500">
                        No further action needed.
                      </span>
                    )}
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
