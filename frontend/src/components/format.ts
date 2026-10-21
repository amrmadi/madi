/**
 * Small presentational helpers shared across pages.
 *
 * Kept together because they are all about *presenting* backend values
 * honestly and readably — dates, labels, and severity colours.
 */

import type { ActivityType, AlertStatus, EventSource, SeverityLevel } from '../api/types'

// ---------------------------------------------------------------------------
// Dates
// ---------------------------------------------------------------------------

/** Format an ISO timestamp as a readable local date and time. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Format an ISO timestamp as a date only. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

/** Turn a duration in seconds into "1h 30m" style text. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—'
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  const remaining = minutes % 60
  return remaining ? `${hours}h ${remaining}m` : `${hours}h`
}

/** A rough age in years, from a date of birth. */
export function ageFromDateOfBirth(dob: string | null | undefined): number | null {
  if (!dob) return null
  const birth = new Date(dob)
  if (Number.isNaN(birth.getTime())) return null
  const today = new Date()
  let age = today.getFullYear() - birth.getFullYear()
  const monthDiff = today.getMonth() - birth.getMonth()
  if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birth.getDate())) {
    age -= 1
  }
  return age
}

// ---------------------------------------------------------------------------
// Labels
// ---------------------------------------------------------------------------

/** Turn "missed_medication" or "walking" into "Missed medication" / "Walking". */
export function humanize(value: string | null | undefined): string {
  if (!value) return '—'
  const spaced = value.replace(/_/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

const ACTIVITY_ICONS: Record<ActivityType, string> = {
  walking: '🚶',
  standing: '🧍',
  sitting: '🪑',
  lying: '🛏️',
  eating: '🍽️',
  sleeping: '😴',
  toileting: '🚻',
  unknown: '❓',
}

export function activityIcon(type: ActivityType): string {
  return ACTIVITY_ICONS[type] ?? '❓'
}

// ---------------------------------------------------------------------------
// Badges
// ---------------------------------------------------------------------------

const SEVERITY_CLASSES: Record<SeverityLevel, string> = {
  info: 'bg-slate-100 text-slate-800 border-slate-300',
  low: 'bg-blue-50 text-blue-800 border-blue-300',
  medium: 'bg-amber-50 text-amber-900 border-amber-300',
  high: 'bg-orange-100 text-orange-900 border-orange-400',
  critical: 'bg-red-100 text-red-900 border-red-400',
}

export function severityClasses(severity: SeverityLevel): string {
  return SEVERITY_CLASSES[severity] ?? SEVERITY_CLASSES.info
}

const ALERT_STATUS_CLASSES: Record<AlertStatus, string> = {
  new: 'bg-red-100 text-red-900 border-red-300',
  acknowledged: 'bg-amber-100 text-amber-900 border-amber-300',
  resolved: 'bg-green-100 text-green-900 border-green-300',
  dismissed: 'bg-slate-100 text-slate-700 border-slate-300',
}

export function alertStatusClasses(status: AlertStatus): string {
  return ALERT_STATUS_CLASSES[status] ?? ALERT_STATUS_CLASSES.dismissed
}

/**
 * Describe where an activity event came from, in plain language.
 *
 * This exists to keep the project's honesty rule visible in the UI: data that
 * was not measured by a real device must say so, on screen, every time.
 */
export function describeSource(source: EventSource): {
  label: string
  isSimulated: boolean
} {
  switch (source) {
    case 'simulated':
      return { label: 'Simulated (demo data)', isSimulated: true }
    case 'sensor':
      return { label: 'Sensor reading', isSimulated: false }
    case 'manual_entry':
      return { label: 'Entered by hand', isSimulated: false }
    case 'imported_dataset':
      return { label: 'Imported dataset', isSimulated: true }
    case 'model':
      return { label: 'Model output', isSimulated: false }
    default:
      return { label: humanize(source), isSimulated: false }
  }
}
