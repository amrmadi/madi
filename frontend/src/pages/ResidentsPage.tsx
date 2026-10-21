/**
 * Residents list: every elderly profile this caregiver may access.
 *
 * The list comes straight from `GET /elderly-profiles`, which the backend has
 * already scoped to the caller's assignments — the page does no filtering of
 * its own, because hiding rows in the browser would not be real access control.
 */

import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api/client'
import { ApiError } from '../api/errors'
import { useApi } from '../api/useApi'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { ageFromDateOfBirth, formatDate } from '../components/format'

export function ResidentsPage() {
  const profiles = useApi(() => api.listProfiles({ page_size: 100 }), [])

  const [showForm, setShowForm] = useState(false)
  const [displayName, setDisplayName] = useState('')
  const [dateOfBirth, setDateOfBirth] = useState('')
  const [roomLabel, setRoomLabel] = useState('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  async function handleCreate(event: FormEvent) {
    event.preventDefault()
    setFormError(null)

    if (!displayName.trim()) {
      setFieldErrors({ display_name: 'Please enter a name for this resident.' })
      return
    }
    setFieldErrors({})

    setSubmitting(true)
    try {
      await api.createProfile({
        display_name: displayName.trim(),
        date_of_birth: dateOfBirth || null,
        room_label: roomLabel.trim() || null,
        notes: notes.trim() || null,
      })
      // Reset and refresh the list so the new resident appears immediately.
      setDisplayName('')
      setDateOfBirth('')
      setRoomLabel('')
      setNotes('')
      setShowForm(false)
      profiles.reload()
    } catch (caught) {
      if (caught instanceof ApiError) {
        setFormError(caught.message)
        const mapped: Record<string, string> = {}
        for (const field of caught.fields) {
          mapped[field.field] = field.message
        }
        setFieldErrors(mapped)
      } else {
        setFormError('Could not create the resident. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1>Residents</h1>
          <p className="mt-2 text-slate-600">
            The people you are assigned to care for.
          </p>
        </div>
        <button
          type="button"
          className="btn-primary"
          onClick={() => setShowForm((open) => !open)}
          aria-expanded={showForm}
        >
          {showForm ? 'Cancel' : 'Add a resident'}
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="card space-y-5" noValidate>
          <h2>Add a resident</h2>
          <p className="text-base text-slate-600">
            Only care-related details are needed. Please do not enter national ID
            numbers, medical record numbers, or home addresses.
          </p>

          {formError && (
            <div
              className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-red-900"
              role="alert"
            >
              {formError}
            </div>
          )}

          <div>
            <label className="field-label" htmlFor="new-name">
              Name or label
            </label>
            <input
              id="new-name"
              className="field-input"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              aria-invalid={Boolean(fieldErrors.display_name)}
            />
            {fieldErrors.display_name && (
              <p className="field-error">{fieldErrors.display_name}</p>
            )}
          </div>

          <div className="grid gap-5 sm:grid-cols-2">
            <div>
              <label className="field-label" htmlFor="new-dob">
                Date of birth (optional)
              </label>
              <input
                id="new-dob"
                className="field-input"
                type="date"
                value={dateOfBirth}
                onChange={(e) => setDateOfBirth(e.target.value)}
                aria-invalid={Boolean(fieldErrors.date_of_birth)}
              />
              {fieldErrors.date_of_birth && (
                <p className="field-error">{fieldErrors.date_of_birth}</p>
              )}
            </div>

            <div>
              <label className="field-label" htmlFor="new-room">
                Room or location (optional)
              </label>
              <input
                id="new-room"
                className="field-input"
                value={roomLabel}
                onChange={(e) => setRoomLabel(e.target.value)}
              />
            </div>
          </div>

          <div>
            <label className="field-label" htmlFor="new-notes">
              Care notes (optional)
            </label>
            <textarea
              id="new-notes"
              className="field-input"
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>

          <button type="submit" className="btn-primary" disabled={submitting}>
            {submitting ? 'Creating…' : 'Create resident'}
          </button>
        </form>
      )}

      {profiles.loading ? (
        <LoadingState label="Loading residents…" />
      ) : profiles.error ? (
        <ErrorState error={profiles.error} onRetry={profiles.reload} />
      ) : (profiles.data?.items.length ?? 0) === 0 ? (
        <EmptyState
          icon="👥"
          title="No residents yet"
          description="You are not assigned to anyone yet. Add a resident to get started, or ask an administrator to assign you to one."
          action={
            <button type="button" className="btn-primary" onClick={() => setShowForm(true)}>
              Add a resident
            </button>
          }
        />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2">
          {profiles.data?.items.map((profile) => {
            const age = ageFromDateOfBirth(profile.date_of_birth)
            return (
              <li key={profile.id} className="card flex flex-col justify-between">
                <div>
                  <h2 className="text-xl font-semibold text-slate-900">
                    {profile.display_name}
                  </h2>
                  <dl className="mt-3 space-y-1 text-base text-slate-600">
                    <div className="flex gap-2">
                      <dt className="font-semibold">Room:</dt>
                      <dd>{profile.room_label ?? 'not set'}</dd>
                    </div>
                    <div className="flex gap-2">
                      <dt className="font-semibold">Born:</dt>
                      <dd>
                        {formatDate(profile.date_of_birth)}
                        {age !== null && ` (${age} years)`}
                      </dd>
                    </div>
                  </dl>
                </div>
                <Link to={`/residents/${profile.id}`} className="btn-primary mt-4">
                  Open record
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
