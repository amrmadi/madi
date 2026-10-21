/**
 * Check-ins tab: record a daily wellbeing or safety check-in, and see history.
 *
 * The API was designed so that a completed check-in with no explicit time
 * defaults to "now" on the server, so this form does not have to send one.
 */

import { useState, type FormEvent } from 'react'

import { api } from '../../api/client'
import { ApiError } from '../../api/errors'
import { useApi } from '../../api/useApi'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { formatDateTime, humanize } from '../../components/format'
import type { CheckinType } from '../../api/types'

const TYPES: CheckinType[] = ['wellbeing', 'safety', 'manual', 'automatic']

export function CheckinsTab({ profileId }: { profileId: number }) {
  const checkins = useApi(() => api.listCheckins(profileId, { page_size: 50 }), [profileId])

  const [checkinType, setCheckinType] = useState<CheckinType>('wellbeing')
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setFormError(null)
    setSuccess(null)
    setSubmitting(true)

    try {
      await api.createCheckin(profileId, {
        checkin_type: checkinType,
        status: 'taken',
        wellbeing_note: note.trim() || null,
      })
      setNote('')
      setSuccess('Check-in recorded.')
      checkins.reload()
    } catch (caught) {
      if (caught instanceof ApiError) {
        setFormError(caught.message)
      } else {
        setFormError('Could not record the check-in. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-6">
      <form onSubmit={handleSubmit} className="card space-y-4" noValidate>
        <h3>Record a check-in</h3>
        <p className="text-base text-slate-600">
          A check-in records that you contacted or visited this resident. The note
          is free text — this system does not diagnose or score wellbeing.
        </p>

        {formError && (
          <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-red-900" role="alert">
            {formError}
          </div>
        )}
        {success && (
          <div
            className="rounded-lg border border-green-300 bg-green-50 px-4 py-3 text-green-900"
            role="status"
          >
            {success}
          </div>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="field-label" htmlFor="checkin-type">
              Type
            </label>
            <select
              id="checkin-type"
              className="field-input"
              value={checkinType}
              onChange={(e) => setCheckinType(e.target.value as CheckinType)}
            >
              {TYPES.map((value) => (
                <option key={value} value={value}>
                  {humanize(value)}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="field-label" htmlFor="checkin-note">
              How are they? (optional)
            </label>
            <input
              id="checkin-note"
              className="field-input"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. Cheerful, ate a full breakfast"
            />
          </div>
        </div>

        <button type="submit" className="btn-primary" disabled={submitting}>
          {submitting ? 'Recording…' : 'Record check-in'}
        </button>
      </form>

      {checkins.loading ? (
        <LoadingState label="Loading check-in history…" />
      ) : checkins.error ? (
        <ErrorState error={checkins.error} onRetry={checkins.reload} />
      ) : (checkins.data?.items.length ?? 0) === 0 ? (
        <EmptyState
          icon="✅"
          title="No check-ins recorded"
          description="Use the form above to record the first check-in for this resident."
        />
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-left">
            <caption className="sr-only">Check-in history, newest first</caption>
            <thead>
              <tr className="border-b border-slate-200">
                <th scope="col" className="py-3 pr-4 font-semibold">
                  When
                </th>
                <th scope="col" className="py-3 pr-4 font-semibold">
                  Type
                </th>
                <th scope="col" className="py-3 pr-4 font-semibold">
                  Status
                </th>
                <th scope="col" className="py-3 font-semibold">
                  Note
                </th>
              </tr>
            </thead>
            <tbody>
              {checkins.data?.items.map((checkin) => (
                <tr key={checkin.id} className="border-b border-slate-100">
                  <td className="py-3 pr-4 text-base">
                    {formatDateTime(checkin.performed_at ?? checkin.created_at)}
                  </td>
                  <td className="py-3 pr-4 text-base">{humanize(checkin.checkin_type)}</td>
                  <td className="py-3 pr-4 text-base">{humanize(checkin.status)}</td>
                  <td className="py-3 text-base text-slate-600">
                    {checkin.wellbeing_note ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
