/**
 * Tests for the presentation helpers.
 *
 * These look trivial, but two of them encode rules the project promises to
 * keep:
 *   * `describeSource` must label simulated or imported data as not measured,
 *     so the UI never presents demo data as a real reading.
 *   * `humanize` and the formatters must degrade to "—" rather than printing
 *     "Invalid Date" or "undefined" in front of a caregiver.
 */

import { describe, expect, it } from 'vitest'

import {
  activityIcon,
  ageFromDateOfBirth,
  alertStatusClasses,
  describeSource,
  formatDate,
  formatDateTime,
  formatDuration,
  humanize,
  severityClasses,
} from './format'

describe('date formatting', () => {
  it('renders an ISO timestamp readably', () => {
    const result = formatDateTime('2026-03-05T09:30:00Z')
    // Locale-dependent, so assert on the parts that must be present.
    expect(result).toContain('2026')
    expect(result).not.toContain('Invalid')
  })

  it('renders a date without a time', () => {
    const result = formatDate('2026-03-05T09:30:00Z')
    expect(result).toContain('2026')
    expect(result).not.toContain(':')
  })

  it('shows an em dash for missing or unparseable values', () => {
    expect(formatDateTime(null)).toBe('—')
    expect(formatDateTime(undefined)).toBe('—')
    expect(formatDateTime('not-a-date')).toBe('—')
    expect(formatDate('')).toBe('—')
  })
})

describe('formatDuration', () => {
  it('uses seconds below a minute', () => {
    expect(formatDuration(45)).toBe('45s')
  })

  it('uses minutes below an hour', () => {
    expect(formatDuration(90)).toBe('1m')
    expect(formatDuration(600)).toBe('10m')
  })

  it('uses hours, keeping leftover minutes', () => {
    expect(formatDuration(3600)).toBe('1h')
    expect(formatDuration(5400)).toBe('1h 30m')
    expect(formatDuration(7200)).toBe('2h')
  })

  it('returns an em dash for a missing duration rather than zero', () => {
    // Showing "0s" for unknown data would be a false statement.
    expect(formatDuration(null)).toBe('—')
    expect(formatDuration(undefined)).toBe('—')
  })
})

describe('ageFromDateOfBirth', () => {
  it('computes an age in years', () => {
    const age = ageFromDateOfBirth('1950-01-01')
    expect(age).toBeTypeOf('number')
    expect(age).toBeGreaterThanOrEqual(70)
  })

  it('does not count a birthday that has not happened yet this year', () => {
    const today = new Date()
    // Tomorrow's local date, 40 years back: the birthday is still ahead, so the
    // age must be 39, not 40. Built from local parts rather than toISOString(),
    // which would shift the date across a UTC boundary.
    const tomorrow = new Date(today.getFullYear() - 40, today.getMonth(), today.getDate() + 1)
    const isoLocal = [
      tomorrow.getFullYear(),
      String(tomorrow.getMonth() + 1).padStart(2, '0'),
      String(tomorrow.getDate()).padStart(2, '0'),
    ].join('-')

    expect(ageFromDateOfBirth(isoLocal)).toBe(39)
  })

  it('returns null rather than a wrong number for bad input', () => {
    expect(ageFromDateOfBirth(null)).toBeNull()
    expect(ageFromDateOfBirth('')).toBeNull()
    expect(ageFromDateOfBirth('garbage')).toBeNull()
  })
})

describe('humanize', () => {
  it('turns a snake_case code into a readable label', () => {
    expect(humanize('missed_medication')).toBe('Missed medication')
    expect(humanize('walking')).toBe('Walking')
  })

  it('returns an em dash for nothing', () => {
    expect(humanize(null)).toBe('—')
    expect(humanize('')).toBe('—')
  })
})

describe('activityIcon', () => {
  it('has an icon for every known activity', () => {
    expect(activityIcon('walking')).toBe('🚶')
    expect(activityIcon('sleeping')).toBe('😴')
  })

  it('falls back to a question mark for an unknown activity', () => {
    // Guards against a new backend enum value rendering as blank.
    expect(activityIcon('unknown')).toBe('❓')
    expect(activityIcon('teleporting' as never)).toBe('❓')
  })
})

describe('severity and status styling', () => {
  it('gives critical the strongest colour and info the calmest', () => {
    expect(severityClasses('critical')).toContain('red')
    expect(severityClasses('info')).toContain('slate')
  })

  it('never returns undefined for an unexpected severity', () => {
    expect(severityClasses('nonsense' as never)).toContain('slate')
  })

  it('styles each alert status distinctly', () => {
    expect(alertStatusClasses('new')).toContain('red')
    expect(alertStatusClasses('resolved')).toContain('green')
    expect(alertStatusClasses('dismissed')).toContain('slate')
  })
})

describe('describeSource — the honesty rule', () => {
  it('says loudly when data is simulated', () => {
    const result = describeSource('simulated')
    expect(result.isSimulated).toBe(true)
    expect(result.label.toLowerCase()).toContain('simulated')
  })

  it('treats imported research data as not measured from this person', () => {
    const result = describeSource('imported_dataset')
    expect(result.isSimulated).toBe(true)
  })

  it('treats a real sensor reading as measured', () => {
    const result = describeSource('sensor')
    expect(result.isSimulated).toBe(false)
  })

  it('still produces a label for an unknown source', () => {
    const result = describeSource('something_new' as never)
    expect(result.label).toBeTruthy()
    expect(result.label).not.toBe('—')
  })
})
