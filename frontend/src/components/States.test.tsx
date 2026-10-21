/**
 * Tests for the three standard page states.
 *
 * The assertions focus on what a caregiver would actually see and need:
 *   * a loading state announces itself politely;
 *   * "cannot reach the server" reads differently from "the server refused";
 *   * a 403 explains the caregiver-assignment problem instead of just failing;
 *   * rejected fields are listed, with the retry action available.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ApiError, NetworkError } from '../api/errors'
import { EmptyState, ErrorState, LoadingState } from './States'

describe('LoadingState', () => {
  it('announces that work is in progress', () => {
    render(<LoadingState />)

    const status = screen.getByRole('status')
    expect(status).toHaveAttribute('aria-live', 'polite')
    expect(status).toHaveTextContent('Loading')
  })

  it('uses a caller-supplied label', () => {
    render(<LoadingState label="Signing you in…" />)
    expect(screen.getByText('Signing you in…')).toBeInTheDocument()
  })
})

describe('ErrorState', () => {
  it('tells the user the server cannot be reached for a NetworkError', () => {
    render(<ErrorState error={new NetworkError('Could not reach the API.')} />)

    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText('Cannot reach the server')).toBeInTheDocument()
    expect(screen.getByText('Could not reach the API.')).toBeInTheDocument()
  })

  it('uses a different heading for a server error', () => {
    render(
      <ErrorState error={new ApiError(500, 'INTERNAL_ERROR', 'The server failed.')} />,
    )

    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    expect(screen.queryByText('Cannot reach the server')).not.toBeInTheDocument()
  })

  it('explains a 403 as a caregiver-assignment problem', () => {
    render(
      <ErrorState
        error={new ApiError(403, 'PERMISSION_DENIED', 'Your role does not permit this.')}
      />,
    )

    // The permission hint is the difference between a dead end and a next step.
    expect(screen.getByText(/do not have permission/i)).toBeInTheDocument()
    expect(screen.getByText(/caregiver assignments/i)).toBeInTheDocument()
  })

  it('does not show the permission hint for a different failure', () => {
    render(<ErrorState error={new ApiError(500, 'INTERNAL_ERROR', 'Boom.')} />)
    expect(screen.queryByText(/do not have permission/i)).not.toBeInTheDocument()
  })

  it('lists the fields the server rejected', () => {
    render(
      <ErrorState
        error={
          new ApiError(422, 'VALIDATION_ERROR', 'One or more fields were invalid.', [
            { field: 'display_name', message: 'This field is required.' },
            { field: 'email', message: 'That email is already registered.' },
          ])
        }
      />,
    )

    // The field name and its message are separate elements inside one <li>,
    // so match on the list item's combined text.
    const items = screen.getAllByRole('listitem').map((li) => li.textContent)
    expect(items).toEqual([
      'display_name: This field is required.',
      'email: That email is already registered.',
    ])
  })

  it('offers a working retry action when one is supplied', async () => {
    const onRetry = vi.fn()
    render(
      <ErrorState error={new NetworkError('Offline.')} onRetry={onRetry} />,
    )

    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))

    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('shows no retry button when there is nothing to retry', () => {
    render(<ErrorState error={new NetworkError('Offline.')} />)
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
  })
})

describe('EmptyState', () => {
  it('shows a title and a plain explanation', () => {
    render(
      <EmptyState title="No alerts yet" description="Nothing needs your attention." />,
    )

    expect(screen.getByText('No alerts yet')).toBeInTheDocument()
    expect(screen.getByText('Nothing needs your attention.')).toBeInTheDocument()
  })

  it('renders an optional next-step action', () => {
    render(
      <EmptyState
        title="No care plans"
        description="Create one to get started."
        action={<button type="button">Create a plan</button>}
      />,
    )

    expect(screen.getByRole('button', { name: 'Create a plan' })).toBeInTheDocument()
  })
})
