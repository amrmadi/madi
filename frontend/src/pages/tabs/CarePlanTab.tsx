/**
 * Care plan tab: plans for one resident, with a create form.
 *
 * The plan status values come from the backend enum, so what the caregiver can
 * choose is exactly what the server accepts.
 */

import { useState, type FormEvent } from 'react'

import { api } from '../../api/client'
import { ApiError } from '../../api/errors'
import { useApi } from '../../api/useApi'
import { EmptyState, ErrorState, LoadingState } from '../../components/States'
import { formatDate, humanize } from '../../components/format'
import type { CarePlanStatus } from '../../api/types'

const STATUSES: CarePlanStatus[] = ['draft', 'active', 'paused', 'completed', 'cancelled']

export function CarePlanTab({ profileId }: { profileId: number }) {
  const plans = useApi(() => api.listCarePlans(profileId, { page_size: 50 }), [profileId])

  const [title, setTitle] = useState('')
  const [summary, setSummary] = useState('')
  const [status, setStatus] = useState<CarePlanStatus>('active')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setFormError(null)

    if (!title.trim()) {
      setFieldErrors({ title: 'Please give the plan a title.' })
      return
    }
    setFieldErrors({})

    setSubmitting(true)
    try {
      await api.createCarePlan(profileId, {
        title: title.trim(),
        summary: summary.trim() || null,
        status,
        start_date: startDate || null,
        end_date: endDate || null,
      })
      setTitle('')
      setSummary('')
      setStartDate('')
      setEndDate('')
      plans.reload()
    } catch (caught) {
      if (caught instanceof ApiError) {
        setFormError(caught.message)
        const mapped: Record<string, string> = {}
        for (const field of caught.fields) {
          mapped[field.field] = field.message
        }
        setFieldErrors(mapped)
      } else {
        setFormError('Could not create the care plan. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-6">
      <form onSubmit={handleSubmit} className="card space-y-4" noValidate>
        <h3>Add a care plan</h3>

        {formError && (
          <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-red-900" role="alert">
            {formError}
          </div>
        )}

        <div>
          <label className="field-label" htmlFor="plan-title">
            Title
          </label>
          <input
            id="plan-title"
            className="field-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            aria-invalid={Boolean(fieldErrors.title)}
          />
          {fieldErrors.title && <p className="field-error">{fieldErrors.title}</p>}
        </div>

        <div>
          <label className="field-label" htmlFor="plan-summary">
            Summary (optional)
          </label>
          <textarea
            id="plan-summary"
            className="field-input"
            rows={2}
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <label className="field-label" htmlFor="plan-status">
              Status
            </label>
            <select
              id="plan-status"
              className="field-input"
              value={status}
              onChange={(e) => setStatus(e.target.value as CarePlanStatus)}
            >
              {STATUSES.map((value) => (
                <option key={value} value={value}>
                  {humanize(value)}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="field-label" htmlFor="plan-start">
              Start date (optional)
            </label>
            <input
              id="plan-start"
              className="field-input"
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              aria-invalid={Boolean(fieldErrors.end_date)}
            />
          </div>

          <div>
            <label className="field-label" htmlFor="plan-end">
              End date (optional)
            </label>
            <input
              id="plan-end"
              className="field-input"
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              aria-invalid={Boolean(fieldErrors.end_date)}
            />
          </div>
        </div>
        {fieldErrors.end_date && <p className="field-error">{fieldErrors.end_date}</p>}

        <button type="submit" className="btn-primary" disabled={submitting}>
          {submitting ? 'Creating…' : 'Create plan'}
        </button>
      </form>

      {plans.loading ? (
        <LoadingState label="Loading care plans…" />
      ) : plans.error ? (
        <ErrorState error={plans.error} onRetry={plans.reload} />
      ) : (plans.data?.items.length ?? 0) === 0 ? (
        <EmptyState
          icon="📝"
          title="No care plans yet"
          description="Care plans record goals and routines for this resident. Use the form above to add the first one."
        />
      ) : (
        <ul className="space-y-4">
          {plans.data?.items.map((plan) => (
            <li key={plan.id} className="card">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="text-xl font-semibold text-slate-900">{plan.title}</h3>
                  <p className="mt-1 text-base text-slate-600">
                    {plan.summary ?? 'No summary provided.'}
                  </p>
                  <p className="mt-2 text-base text-slate-500">
                    {formatDate(plan.start_date)} → {formatDate(plan.end_date)}
                  </p>
                </div>
                <span className="rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-sm font-semibold text-brand-800">
                  {humanize(plan.status)}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
