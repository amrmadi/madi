/**
 * Resident detail page: one elderly profile and everything attached to it.
 *
 * The page is organised as tabs so a caregiver is not faced with one very long
 * page. Each tab loads its own data, so switching tabs does not re-fetch the
 * whole record.
 *
 * The profile panel shows the resident's details and an inline edit form. The
 * caregiver list is shown because *who can see this record* is important
 * information, not an implementation detail.
 */

import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api } from '../api/client'
import { ApiError } from '../api/errors'
import { useApi } from '../api/useApi'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { ageFromDateOfBirth, formatDateTime, humanize } from '../components/format'
import { ActivityHistoryTab } from './tabs/ActivityHistoryTab'
import { CarePlanTab } from './tabs/CarePlanTab'
import { CheckinsTab } from './tabs/CheckinsTab'
import { RemindersTab } from './tabs/RemindersTab'

type TabKey = 'profile' | 'care-plan' | 'reminders' | 'checkins' | 'activity'

const TABS: Array<{ key: TabKey; label: string }> = [
  { key: 'profile', label: 'Profile' },
  { key: 'care-plan', label: 'Care plan' },
  { key: 'reminders', label: 'Reminders' },
  { key: 'checkins', label: 'Check-ins' },
  { key: 'activity', label: 'Activity history' },
]

export function ResidentDetailPage() {
  const params = useParams<{ id: string }>()
  const profileId = Number(params.id)

  // Guard against a non-numeric id in the URL (e.g. /residents/abc).
  const validId = Number.isInteger(profileId) && profileId > 0

  const profile = useApi(() => api.getProfile(profileId), [profileId], {
    enabled: validId,
  })
  const caregivers = useApi(() => api.listCaregivers(profileId), [profileId], {
    enabled: validId,
  })

  const [activeTab, setActiveTab] = useState<TabKey>('profile')

  if (!validId) {
    return (
      <EmptyState
        icon="🔍"
        title="That resident page does not exist"
        description="The link you followed does not point to a resident. Try the residents list instead."
        action={
          <Link to="/residents" className="btn-primary">
            Back to residents
          </Link>
        }
      />
    )
  }

  return (
    <div className="space-y-8">
      <Link to="/residents" className="inline-flex items-center gap-2 text-base font-semibold text-brand-700 hover:underline">
        ← Back to residents
      </Link>

      {profile.loading ? (
        <LoadingState label="Loading resident…" />
      ) : profile.error ? (
        <ErrorState error={profile.error} onRetry={profile.reload} />
      ) : profile.data ? (
        <header>
          <div className="flex flex-wrap items-center gap-4">
            <h1>{profile.data.display_name}</h1>
            {!profile.data.is_active && (
              <span className="rounded-full border border-slate-300 bg-slate-100 px-3 py-1 text-sm font-semibold text-slate-700">
                Inactive
              </span>
            )}
          </div>
          <p className="mt-2 text-slate-600">
            Room {profile.data.room_label ?? 'not set'}
            {profile.data.date_of_birth && (
              <>
                {' · born '}
                {profile.data.date_of_birth}
                {ageFromDateOfBirth(profile.data.date_of_birth) !== null &&
                  ` (${ageFromDateOfBirth(profile.data.date_of_birth)} years)`}
              </>
            )}
          </p>
        </header>
      ) : null}

      {/* Tabs */}
      <nav aria-label="Resident sections" className="flex flex-wrap gap-2 border-b border-slate-200 pb-3">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            aria-current={activeTab === tab.key ? 'page' : undefined}
            className={activeTab === tab.key ? 'btn-primary' : 'btn-secondary'}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {activeTab === 'profile' && profile.data && (
        <ProfileTabContent
          profile={profile.data}
          onSaved={profile.reload}
          caregivers={caregivers.data ?? []}
          caregiversLoading={caregivers.loading}
          caregiversError={caregivers.error}
          onRetryCaregivers={caregivers.reload}
        />
      )}

      {activeTab === 'care-plan' && <CarePlanTab profileId={profileId} />}
      {activeTab === 'reminders' && <RemindersTab profileId={profileId} />}
      {activeTab === 'checkins' && <CheckinsTab profileId={profileId} />}
      {activeTab === 'activity' && <ActivityHistoryTab profileId={profileId} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Profile tab
// ---------------------------------------------------------------------------

interface ProfileTabContentProps {
  profile: import('../api/types').ElderlyProfile
  onSaved: () => void
  caregivers: import('../api/types').CaregiverAssignment[]
  caregiversLoading: boolean
  caregiversError: ApiError | import('../api/errors').NetworkError | null
  onRetryCaregivers: () => void
}

function ProfileTabContent({
  profile,
  onSaved,
  caregivers,
  caregiversLoading,
  caregiversError,
  onRetryCaregivers,
}: ProfileTabContentProps) {
  const [editing, setEditing] = useState(false)
  const [displayName, setDisplayName] = useState(profile.display_name)
  const [roomLabel, setRoomLabel] = useState(profile.room_label ?? '')
  const [dateOfBirth, setDateOfBirth] = useState(profile.date_of_birth ?? '')
  const [mobilityNotes, setMobilityNotes] = useState(profile.mobility_notes ?? '')
  const [notes, setNotes] = useState(profile.notes ?? '')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  function startEditing() {
    // Reset the form to the current saved values each time editing begins.
    setDisplayName(profile.display_name)
    setRoomLabel(profile.room_label ?? '')
    setDateOfBirth(profile.date_of_birth ?? '')
    setMobilityNotes(profile.mobility_notes ?? '')
    setNotes(profile.notes ?? '')
    setFieldErrors({})
    setFormError(null)
    setEditing(true)
  }

  async function handleSave(event: React.FormEvent) {
    event.preventDefault()
    setFormError(null)

    if (!displayName.trim()) {
      setFieldErrors({ display_name: 'Please enter a name for this resident.' })
      return
    }
    setFieldErrors({})
    setSubmitting(true)

    try {
      await api.updateProfile(profile.id, {
        display_name: displayName.trim(),
        room_label: roomLabel.trim() || null,
        date_of_birth: dateOfBirth || null,
        mobility_notes: mobilityNotes.trim() || null,
        notes: notes.trim() || null,
      })
      setEditing(false)
      onSaved()
    } catch (caught) {
      if (caught instanceof ApiError) {
        setFormError(caught.message)
        const mapped: Record<string, string> = {}
        for (const field of caught.fields) {
          mapped[field.field] = field.message
        }
        setFieldErrors(mapped)
      } else {
        setFormError('Could not save the changes. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Details, or the edit form. */}
      {!editing ? (
        <div className="card">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <h2>Details</h2>
            <button type="button" className="btn-secondary" onClick={startEditing}>
              Edit details
            </button>
          </div>

          <dl className="mt-4 space-y-3 text-base">
            <div className="flex flex-col gap-1 sm:flex-row sm:gap-3">
              <dt className="font-semibold text-slate-700 sm:w-48">Name or label</dt>
              <dd className="text-slate-900">{profile.display_name}</dd>
            </div>
            <div className="flex flex-col gap-1 sm:flex-row sm:gap-3">
              <dt className="font-semibold text-slate-700 sm:w-48">Room or location</dt>
              <dd className="text-slate-900">{profile.room_label ?? 'Not set'}</dd>
            </div>
            <div className="flex flex-col gap-1 sm:flex-row sm:gap-3">
              <dt className="font-semibold text-slate-700 sm:w-48">Date of birth</dt>
              <dd className="text-slate-900">{profile.date_of_birth ?? 'Not set'}</dd>
            </div>
            <div className="flex flex-col gap-1 sm:flex-row sm:gap-3">
              <dt className="font-semibold text-slate-700 sm:w-48">Mobility notes</dt>
              <dd className="text-slate-900">{profile.mobility_notes ?? 'None recorded'}</dd>
            </div>
            <div className="flex flex-col gap-1 sm:flex-row sm:gap-3">
              <dt className="font-semibold text-slate-700 sm:w-48">Care notes</dt>
              <dd className="text-slate-900">{profile.notes ?? 'None recorded'}</dd>
            </div>
            <div className="flex flex-col gap-1 sm:flex-row sm:gap-3">
              <dt className="font-semibold text-slate-700 sm:w-48">Last updated</dt>
              <dd className="text-slate-900">{formatDateTime(profile.updated_at)}</dd>
            </div>
          </dl>
        </div>
      ) : (
        <form onSubmit={handleSave} className="card space-y-5" noValidate>
          <h2>Edit details</h2>

          {formError && (
            <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-red-900" role="alert">
              {formError}
            </div>
          )}

          <div>
            <label className="field-label" htmlFor="edit-name">
              Name or label
            </label>
            <input
              id="edit-name"
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
              <label className="field-label" htmlFor="edit-room">
                Room or location
              </label>
              <input
                id="edit-room"
                className="field-input"
                value={roomLabel}
                onChange={(e) => setRoomLabel(e.target.value)}
                aria-invalid={Boolean(fieldErrors.room_label)}
              />
              {fieldErrors.room_label && (
                <p className="field-error">{fieldErrors.room_label}</p>
              )}
            </div>

            <div>
              <label className="field-label" htmlFor="edit-dob">
                Date of birth
              </label>
              <input
                id="edit-dob"
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
          </div>

          <div>
            <label className="field-label" htmlFor="edit-mobility">
              Mobility notes
            </label>
            <input
              id="edit-mobility"
              className="field-input"
              value={mobilityNotes}
              onChange={(e) => setMobilityNotes(e.target.value)}
              aria-invalid={Boolean(fieldErrors.mobility_notes)}
            />
            {fieldErrors.mobility_notes && (
              <p className="field-error">{fieldErrors.mobility_notes}</p>
            )}
          </div>

          <div>
            <label className="field-label" htmlFor="edit-notes">
              Care notes
            </label>
            <textarea
              id="edit-notes"
              className="field-input"
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>

          <div className="flex flex-wrap gap-3">
            <button type="submit" className="btn-primary" disabled={submitting}>
              {submitting ? 'Saving…' : 'Save changes'}
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setEditing(false)}
              disabled={submitting}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* Who can see this record. */}
      <section aria-labelledby="caregivers-heading" className="space-y-4">
        <h2 id="caregivers-heading">Caregivers with access</h2>

        {caregiversLoading ? (
          <LoadingState label="Loading caregivers…" />
        ) : caregiversError ? (
          <ErrorState error={caregiversError} onRetry={onRetryCaregivers} />
        ) : caregivers.length === 0 ? (
          <EmptyState
            icon="👤"
            title="No caregivers assigned"
            description="Nobody is currently assigned to this resident. An administrator can assign someone."
          />
        ) : (
          <ul className="space-y-3">
            {caregivers.map((assignment) => (
              <li
                key={assignment.id}
                className="card flex flex-wrap items-center justify-between gap-3"
              >
                <div>
                  <p className="text-lg font-semibold text-slate-900">
                    {assignment.caregiver_display_name ?? `User #${assignment.caregiver_id}`}
                  </p>
                  <p className="text-base text-slate-600">
                    {assignment.caregiver_email ?? 'No email on record'}
                  </p>
                </div>
                <div className="text-right">
                  <span className="rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-sm font-semibold text-brand-800">
                    {humanize(assignment.assignment_role)}
                  </span>
                  <p className="mt-1 text-base text-slate-500">
                    {assignment.is_active ? 'Active' : 'Revoked'}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
