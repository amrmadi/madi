/**
 * The three "not normal content" states every data page needs.
 *
 * They are components rather than ad-hoc JSX precisely so that they cannot be
 * forgotten: a page that handles loading and error is the difference between a
 * professional app and one that shows a blank white screen.
 */

import type { ReactNode } from 'react'

import { ApiError, NetworkError } from '../api/errors'

// ---------------------------------------------------------------------------
// Loading
// ---------------------------------------------------------------------------

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div
      className="flex flex-col items-center justify-center gap-4 py-16 text-center"
      // Announce to screen readers that something is happening, without
      // stealing focus.
      role="status"
      aria-live="polite"
    >
      <span
        className="h-10 w-10 animate-spin rounded-full border-4 border-brand-200 border-t-brand-600"
        aria-hidden="true"
      />
      <p className="text-lg text-slate-600">{label}</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Error
// ---------------------------------------------------------------------------

interface ErrorStateProps {
  error: ApiError | NetworkError
  /** Show a "Try again" button when provided. */
  onRetry?: () => void
}

export function ErrorState({ error, onRetry }: ErrorStateProps) {
  // Distinguish "the server said no" from "I could not reach the server".
  // They call for different actions from the user.
  const isNetwork = error instanceof NetworkError

  return (
    <div
      className="card border-red-200 bg-red-50"
      role="alert"
      // Errors are important enough to interrupt a screen reader.
      aria-live="assertive"
    >
      <div className="flex items-start gap-4">
        <span className="text-3xl" aria-hidden="true">
          {isNetwork ? '🔌' : '⚠️'}
        </span>
        <div className="flex-1">
          <h2 className="text-xl font-semibold text-red-900">
            {isNetwork ? 'Cannot reach the server' : 'Something went wrong'}
          </h2>
          <p className="mt-2 text-red-800">{error.message}</p>

          {error instanceof ApiError && error.isForbidden && (
            <p className="mt-2 text-red-800">
              You do not have permission to see this. If you believe this is a
              mistake, ask an administrator to check your caregiver assignments.
            </p>
          )}

          {/* Show which fields were rejected, when it was a validation error. */}
          {error instanceof ApiError && error.fields.length > 0 && (
            <ul className="mt-3 list-inside list-disc space-y-1 text-red-800">
              {error.fields.map((field) => (
                <li key={field.field}>
                  <span className="font-semibold">{field.field}</span>: {field.message}
                </li>
              ))}
            </ul>
          )}

          {onRetry && (
            <button type="button" className="btn-secondary mt-4" onClick={onRetry}>
              Try again
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Empty
// ---------------------------------------------------------------------------

interface EmptyStateProps {
  title: string
  description: string
  icon?: string
  /** An optional action, e.g. a "Create the first plan" button. */
  action?: ReactNode
}

export function EmptyState({ title, description, icon = '📋', action }: EmptyStateProps) {
  return (
    <div className="card flex flex-col items-center gap-4 py-12 text-center">
      <span className="text-5xl" aria-hidden="true">
        {icon}
      </span>
      <h2 className="text-xl font-semibold text-slate-800">{title}</h2>
      <p className="max-w-md text-slate-600">{description}</p>
      {action}
    </div>
  )
}
