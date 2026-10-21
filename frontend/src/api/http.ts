/**
 * The single HTTP client every request goes through.
 *
 * Rules this file enforces:
 *   * The base URL comes from `VITE_API_BASE_URL` — never hard-coded.
 *   * The access token is attached automatically when present.
 *   * Every failure becomes either an `ApiError` (the server answered with an
 *     error) or a `NetworkError` (the server could not be reached), so callers
 *     never have to parse a raw `Response`.
 *
 * On a 401 the stored token is cleared and the app is told, so the user is
 * returned to the sign-in page instead of seeing a page of failures.
 */

import { ApiError, NetworkError } from './errors'
import { clearToken, getToken } from './token'
import type { ApiErrorBody } from './types'

/**
 * The API base URL. Defaults to the local backend so a developer can run
 * `npm run dev` with no `.env` file at all.
 */
export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

/** Called whenever the server rejects our token, so the app can sign out. */
let onUnauthorized: (() => void) | null = null

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE'
  /** JSON request body. Omit for GET/DELETE. */
  body?: unknown
  /** Query parameters. `undefined` and `null` values are skipped. */
  query?: Record<string, string | number | boolean | undefined | null>
  /** Set to false for endpoints that must not send a token (login/register). */
  authenticated?: boolean
}

/** Build a query string, skipping empty values. */
function buildUrl(path: string, query?: RequestOptions['query']): string {
  const url = new URL(`${API_BASE_URL}${path}`)
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value))
      }
    }
  }
  return url.toString()
}

/** Turn a failed response into the right error type. */
async function toError(response: Response): Promise<ApiError> {
  let code = 'HTTP_ERROR'
  let message = `The request failed (HTTP ${response.status}).`
  let fields: Array<{ field: string; message: string }> = []

  try {
    const payload = (await response.json()) as ApiErrorBody
    if (payload?.error) {
      code = payload.error.code ?? code
      message = payload.error.message ?? message
      const rawFields = payload.error.details?.fields
      if (Array.isArray(rawFields)) {
        fields = rawFields.map((f) => ({ field: f.field, message: f.message }))
      }
    }
  } catch {
    // A non-JSON body (a proxy error page, for example). Keep the defaults.
  }

  return new ApiError(response.status, code, message, fields)
}

/**
 * Perform an API request and return the parsed JSON body.
 *
 * Use the typed helpers in `client.ts` (`api.get`, `api.post`, ...) rather than
 * calling this directly.
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, authenticated = true } = options

  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }
  if (authenticated) {
    const token = getToken()
    if (token) {
      headers.Authorization = `Bearer ${token}`
    }
  }

  let response: Response
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new NetworkError(
      `Could not reach the ElderLife API at ${API_BASE_URL}. ` +
        'Check that the backend is running, then try again.',
    )
  }

  if (response.status === 401 && authenticated) {
    // The token is gone or expired. Clear it and let the app sign out.
    clearToken()
    onUnauthorized?.()
  }

  if (!response.ok) {
    throw await toError(response)
  }

  // 204 No Content (and an empty body) must not be parsed as JSON.
  if (response.status === 204) {
    return undefined as T
  }
  const text = await response.text()
  if (!text) {
    return undefined as T
  }
  return JSON.parse(text) as T
}
