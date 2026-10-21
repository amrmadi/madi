/**
 * A typed error raised for any failed API call.
 *
 * The backend returns one consistent error envelope, so the whole frontend can
 * rely on a single error type instead of guessing per endpoint. `code` is a
 * stable machine string the UI may branch on; `message` is safe to show to a
 * user.
 */
export class ApiError extends Error {
  /** HTTP status, e.g. 403. */
  readonly status: number
  /** Stable machine-readable code, e.g. "PERMISSION_DENIED". */
  readonly code: string
  /** Per-field validation problems, when the failure was a 422. */
  readonly fields: Array<{ field: string; message: string }>

  constructor(
    status: number,
    code: string,
    message: string,
    fields: Array<{ field: string; message: string }> = [],
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.fields = fields
  }

  /** True when the user simply is not signed in (or the token expired). */
  get isAuthError(): boolean {
    return this.status === 401
  }

  /** True when the user is signed in but not allowed to do this. */
  get isForbidden(): boolean {
    return this.status === 403
  }
}

/**
 * Raised when the API could not be reached at all (server down, no network).
 *
 * This is deliberately distinct from `ApiError`: "the server said no" and
 * "I could not ask the server" look identical to a user unless the UI says
 * which one happened.
 */
export class NetworkError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'NetworkError'
  }
}
