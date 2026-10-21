/**
 * Tests for the HTTP client — the one place every request goes through.
 *
 * What matters here is the behaviour a user feels, not the implementation:
 *   * the token is attached when it should be, and omitted when it should be;
 *   * a 401 signs the user out instead of leaving a broken screen;
 *   * the server's error envelope becomes a typed error, so the UI can show
 *     the right message;
 *   * "the server said no" and "I could not reach the server" stay distinct.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, NetworkError } from './errors'
import { request, setUnauthorizedHandler } from './http'
import { clearToken, setToken } from './token'

/** Build a minimal Response-like object for the mocked fetch. */
function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** Read the headers the client actually sent. */
function sentHeaders(mock: ReturnType<typeof vi.fn>, callIndex = 0): Record<string, string> {
  const init = mock.mock.calls[callIndex]?.[1] as RequestInit
  return (init?.headers as Record<string, string>) ?? {}
}

beforeEach(() => {
  clearToken()
  setUnauthorizedHandler(null)
})

afterEach(() => {
  vi.restoreAllMocks()
  clearToken()
  setUnauthorizedHandler(null)
})

describe('request', () => {
  it('returns the parsed JSON body on success', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: 1, name: 'Margaret' }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await request<{ id: number; name: string }>('/elderly-profiles/1')

    expect(result).toEqual({ id: 1, name: 'Margaret' })
  })

  it('attaches the bearer token when one is stored', async () => {
    setToken('test-token-123')
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await request('/auth/me')

    expect(sentHeaders(fetchMock).Authorization).toBe('Bearer test-token-123')
  })

  it('omits the token for unauthenticated endpoints such as login', async () => {
    setToken('test-token-123')
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await request('/auth/login', { method: 'POST', body: {}, authenticated: false })

    expect(sentHeaders(fetchMock).Authorization).toBeUndefined()
  })

  it('skips null and undefined query values so URLs stay clean', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}))
    vi.stubGlobal('fetch', fetchMock)

    await request('/alerts', {
      query: { status: 'new', severity: undefined, page: 1, cursor: null },
    })

    const url = String(fetchMock.mock.calls[0]?.[0])
    expect(url).toContain('status=new')
    expect(url).toContain('page=1')
    expect(url).not.toContain('severity')
    expect(url).not.toContain('cursor')
  })

  it('turns the server error envelope into an ApiError with code and fields', async () => {
    // Each call needs a fresh Response: a Response body can only be read once,
    // so reusing one object would hide the fields on the second call.
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        jsonResponse(
          {
            error: {
              code: 'VALIDATION_ERROR',
              message: 'The request was rejected.',
              details: {
                fields: [{ field: 'display_name', message: 'This field is required.' }],
              },
            },
          },
          422,
        ),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    try {
      await request('/elderly-profiles')
      throw new Error('request should have rejected')
    } catch (caught) {
      expect(caught).toBeInstanceOf(ApiError)
      const error = caught as ApiError
      expect(error.status).toBe(422)
      expect(error.code).toBe('VALIDATION_ERROR')
      expect(error.message).toBe('The request was rejected.')
      expect(error.fields).toEqual([
        { field: 'display_name', message: 'This field is required.' },
      ])
    }
  })

  it('flags a 403 as forbidden so the UI can explain the permission problem', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        { error: { code: 'PERMISSION_DENIED', message: 'Not allowed.' } },
        403,
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    try {
      await request('/elderly-profiles/1')
      throw new Error('request should have rejected')
    } catch (caught) {
      expect(caught).toBeInstanceOf(ApiError)
      expect((caught as ApiError).isForbidden).toBe(true)
      expect((caught as ApiError).isAuthError).toBe(false)
    }
  })

  it('clears the token and notifies the app on a 401', async () => {
    setToken('expired-token')
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)

    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ error: { code: 'UNAUTHENTICATED', message: 'Token expired.' } }, 401),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(request('/auth/me')).rejects.toBeInstanceOf(ApiError)

    expect(onUnauthorized).toHaveBeenCalledTimes(1)
    // The unusable token must not survive, or every later request repeats the 401.
    const { getToken } = await import('./token')
    expect(getToken()).toBeNull()
  })

  it('raises NetworkError, not ApiError, when the server cannot be reached', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    vi.stubGlobal('fetch', fetchMock)

    await expect(request('/auth/me')).rejects.toBeInstanceOf(NetworkError)
  })

  it('handles a 204 No Content without trying to parse a body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(request('/alerts/1', { method: 'DELETE' })).resolves.toBeUndefined()
  })

  it('sends a JSON body with the right content type', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await request('/auth/login', {
      method: 'POST',
      body: { email: 'a@b.com' },
      authenticated: false,
    })

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    expect(sentHeaders(fetchMock)['Content-Type']).toBe('application/json')
    expect(init.body).toBe(JSON.stringify({ email: 'a@b.com' }))
  })

  it('survives a non-JSON error body, such as a proxy error page', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('<html>Bad gateway</html>', {
        status: 502,
        headers: { 'Content-Type': 'text/html' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    try {
      await request('/health')
      throw new Error('request should have rejected')
    } catch (caught) {
      expect(caught).toBeInstanceOf(ApiError)
      const error = caught as ApiError
      expect(error.status).toBe(502)
      expect(error.code).toBe('HTTP_ERROR')
    }
  })
})
