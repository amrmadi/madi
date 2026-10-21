/**
 * Activity history tab: what the resident has been doing, newest first.
 *
 * Honesty rule enforced on this page: every row shows where its data came
 * from. The backend defaults `source` to `"simulated"`, and this page renders
 * that fact as a visible badge rather than hiding it, so demo data can never be
 * mistaken for a real sensor reading.
 *
 * The time filter uses the `start`/`end` query parameters. `URLSearchParams`
 * (inside the API client) percent-encodes them, so the `+` in a UTC offset is
 * not turned into a space.
 */

import { useState } from 'react'

import { api } from '../../api/client'
import { useApi } from '../../api/useApi'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import {
  activityIcon,
  describeSource,
  formatDateTime,
  formatDuration,
  humanize,
} from '../../components/format'

/** Convert a `datetime-local` value into an ISO 8601 UTC string. */
function toIso(local: string): string | undefined {
  if (!local) return undefined
  const date = new Date(local)
  if (Number.isNaN(date.getTime())) return undefined
  return date.toISOString()
}

export function ActivityHistoryTab({ profileId }: { profileId: number }) {
  const [startInput, setStartInput] = useState('')
  const [endInput, setEndInput] = useState('')

  // These are the values actually sent. They only change when the caregiver
  // presses "Apply filter", so typing does not fire a request per keystroke.
  const [appliedStart, setAppliedStart] = useState<string | undefined>(undefined)
  const [appliedEnd, setAppliedEnd] = useState<string | undefined>(undefined)

  const events = useApi(
    () =>
      api.listActivityEvents(profileId, {
        page_size: 100,
        start: appliedStart,
        end: appliedEnd,
      }),
    [profileId, appliedStart, appliedEnd],
  )

  function applyFilter() {
    setAppliedStart(toIso(startInput))
    setAppliedEnd(toIso(endInput))
  }

  function clearFilter() {
    setStartInput('')
    setEndInput('')
    setAppliedStart(undefined)
    setAppliedEnd(undefined)
  }

  return (
    <div className="space-y-6">
      <div className="card space-y-4">
        <h3>Filter by time</h3>
        <p className="text-base text-slate-600">
          Leave both fields empty to see the full history.
        </p>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="field-label" htmlFor="activity-start">
              From
            </label>
            <input
              id="activity-start"
              className="field-input"
              type="datetime-local"
              value={startInput}
              onChange={(e) => setStartInput(e.target.value)}
            />
          </div>

          <div>
            <label className="field-label" htmlFor="activity-end">
              Until
            </label>
            <input
              id="activity-end"
              className="field-input"
              type="datetime-local"
              value={endInput}
              onChange={(e) => setEndInput(e.target.value)}
            />
          </div>
        </div>

        <div className="flex flex-wrap gap-3">
          <button type="button" className="btn-primary" onClick={applyFilter}>
            Apply filter
          </button>
          <button type="button" className="btn-secondary" onClick={clearFilter}>
            Clear filter
          </button>
        </div>
      </div>

      {events.loading ? (
        <LoadingState label="Loading activity history…" />
      ) : events.error ? (
        <ErrorState error={events.error} onRetry={events.reload} />
      ) : (events.data?.items.length ?? 0) === 0 ? (
        <EmptyState
          icon="📅"
          title="No activity recorded"
          description={
            appliedStart || appliedEnd
              ? 'No activity was recorded in the time window you chose. Try widening the dates.'
              : 'There is no activity history for this resident yet.'
          }
        />
      ) : (
        <>
          <p className="text-base text-slate-600">
            Showing {events.data?.items.length ?? 0} of {events.data?.total ?? 0}{' '}
            recorded events.
          </p>

          <ul className="space-y-3">
            {events.data?.items.map((event) => {
              const source = describeSource(event.source)
              return (
                <li key={event.id} className="card">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="flex items-start gap-4">
                      <span className="text-3xl" aria-hidden="true">
                        {activityIcon(event.activity_type)}
                      </span>
                      <div>
                        <h3 className="text-lg font-semibold text-slate-900">
                          {humanize(event.activity_type)}
                        </h3>
                        <p className="text-base text-slate-600">
                          {formatDateTime(event.started_at)}
                          {event.duration_seconds !== null &&
                            ` · ${formatDuration(event.duration_seconds)}`}
                          {event.room_label && ` · ${event.room_label}`}
                        </p>
                        {event.note && (
                          <p className="mt-1 text-base text-slate-500">{event.note}</p>
                        )}
                      </div>
                    </div>

                    {/* The honesty badge. Demo/simulated data says so, loudly. */}
                    <span
                      className={`rounded-full border px-3 py-1 text-sm font-semibold ${
                        source.isSimulated
                          ? 'border-amber-400 bg-amber-100 text-amber-900'
                          : 'border-slate-300 bg-slate-100 text-slate-700'
                      }`}
                    >
                      {source.label}
                    </span>
                  </div>

                  {event.confidence !== null && (
                    <p className="mt-2 text-base text-slate-500">
                      Model confidence: {Math.round(event.confidence * 100)}%
                    </p>
                  )}
                </li>
              )
            })}
          </ul>
        </>
      )}
    </div>
  )
}
