/**
 * Reminders tab: repeating reminders such as hydration or a daily walk.
 *
 * The form reflects a real backend rule: a `weekly` reminder must include a
 * weekday, so the day picker only appears for weekly reminders and the submit
 * button explains what is missing.
 */

import { useState, type FormEvent } from 'react'

import { api } from '../../api/client'
import { ApiError } from '../../api/errors'
import { useApi } from '../../api/useApi'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { humanize } from '../../components/format'
import type { RecurrencePattern } from '../../api/types'

const RECURRENCES: RecurrencePattern[] = ['once', 'daily', 'weekly', 'monthly', 'as_needed']

const WEEKDAYS = [
  { value: 1, label: 'Monday' },
  { value: 2, label: 'Tuesday' },
  { value: 3, label: 'Wednesday' },
  { value: 4, label: 'Thursday' },
  { value: 5, label: 'Friday' },
  { value: 6, label: 'Saturday' },
  { value: 7, label: 'Sunday' },
]

/** A blank time is allowed, but if given it must look like HH:MM. */
function validateTime(value: string): string | null {
  if (!value) return null
  if (!/^([01][0-9]|2[0-3]):[0-5][0-9]$/.test(value)) {
    return 'Enter a 24-hour time like 08:30.'
  }
  return null
}

export function RemindersTab({ profileId }: { profileId: number }) {
  const reminders = useApi(() => api.listReminders(profileId), [profileId])

  const [title, setTitle] = useState('')
  const [message, setMessage] = useState('')
  const [recurrence, setRecurrence] = useState<RecurrencePattern>('daily')
  const [timeOfDay, setTimeOfDay] = useState('')
  const [dayOfWeek, setDayOfWeek] = useState(1)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setFormError(null)

    const problems: Record<string, string> = {}
    if (!title.trim()) problems.title = 'Please give the reminder a title.'
    const timeProblem = validateTime(timeOfDay)
    if (timeProblem) problems.time_of_day = timeProblem

    setFieldErrors(problems)
    if (Object.keys(problems).length > 0) return

    setSubmitting(true)
    try {
      await api.createReminder(profileId, {
        title: title.trim(),
        message: message.trim() || null,
        recurrence,
        time_of_day: timeOfDay || null,
        day_of_week: recurrence === 'weekly' ? dayOfWeek : null,
      })
      setTitle('')
      setMessage('')
      setTimeOfDay('')
      reminders.reload()
    } catch (caught) {
      if (caught instanceof ApiError) {
        setFormError(caught.message)
        const mapped: Record<string, string> = {}
        for (const field of caught.fields) {
          mapped[field.field] = field.message
        }
        setFieldErrors(mapped)
      } else {
        setFormError('Could not create the reminder. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-6">
      <form onSubmit={handleSubmit} className="card space-y-4" noValidate>
        <h3>Add a reminder</h3>

        {formError && (
          <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-red-900" role="alert">
            {formError}
          </div>
        )}

        <div>
          <label className="field-label" htmlFor="reminder-title">
            Title
          </label>
          <input
            id="reminder-title"
            className="field-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            aria-invalid={Boolean(fieldErrors.title)}
          />
          {fieldErrors.title && <p className="field-error">{fieldErrors.title}</p>}
        </div>

        <div>
          <label className="field-label" htmlFor="reminder-message">
            Message (optional)
          </label>
          <input
            id="reminder-message"
            className="field-input"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <label className="field-label" htmlFor="reminder-recurrence">
              Repeats
            </label>
            <select
              id="reminder-recurrence"
              className="field-input"
              value={recurrence}
              onChange={(e) => setRecurrence(e.target.value as RecurrencePattern)}
            >
              {RECURRENCES.map((value) => (
                <option key={value} value={value}>
                  {humanize(value)}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="field-label" htmlFor="reminder-time">
              Time (optional)
            </label>
            <input
              id="reminder-time"
              className="field-input"
              type="time"
              value={timeOfDay}
              onChange={(e) => setTimeOfDay(e.target.value)}
              aria-invalid={Boolean(fieldErrors.time_of_day)}
            />
            {fieldErrors.time_of_day && (
              <p className="field-error">{fieldErrors.time_of_day}</p>
            )}
          </div>

          {/* Only weekly reminders need a weekday — matching the backend rule. */}
          {recurrence === 'weekly' && (
            <div>
              <label className="field-label" htmlFor="reminder-day">
                Day of week
              </label>
              <select
                id="reminder-day"
                className="field-input"
                value={dayOfWeek}
                onChange={(e) => setDayOfWeek(Number(e.target.value))}
              >
                {WEEKDAYS.map((day) => (
                  <option key={day.value} value={day.value}>
                    {day.label}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        <button type="submit" className="btn-primary" disabled={submitting}>
          {submitting ? 'Creating…' : 'Create reminder'}
        </button>
      </form>

      {reminders.loading ? (
        <LoadingState label="Loading reminders…" />
      ) : reminders.error ? (
        <ErrorState error={reminders.error} onRetry={reminders.reload} />
      ) : (reminders.data?.length ?? 0) === 0 ? (
        <EmptyState
          icon="⏰"
          title="No reminders yet"
          description="Reminders prompt everyday activities such as drinking water or going for a walk."
        />
      ) : (
        <ul className="space-y-3">
          {reminders.data?.map((reminder) => (
            <li key={reminder.id} className="card flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-lg font-semibold text-slate-900">{reminder.title}</h3>
                {reminder.message && (
                  <p className="text-base text-slate-600">{reminder.message}</p>
                )}
              </div>
              <div className="text-right text-base text-slate-600">
                <p className="font-semibold">{humanize(reminder.recurrence)}</p>
                <p>{reminder.time_of_day ?? 'No set time'}</p>
                {reminder.day_of_week !== null && (
                  <p>{WEEKDAYS.find((d) => d.value === reminder.day_of_week)?.label}</p>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
