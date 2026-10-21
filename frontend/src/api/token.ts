/**
 * Token storage.
 *
 * The access token is kept in `localStorage` so a refresh does not sign the
 * user out. This is a deliberate, documented trade-off:
 *
 *   * `localStorage` survives page reloads, which caregivers expect.
 *   * It is readable by JavaScript, so it is not proof against XSS. A
 *     production system would prefer an httpOnly cookie.
 *
 * This is a graduation project running on localhost, so the convenience is
 * worth it — but the choice is written down here rather than hidden.
 */

const TOKEN_KEY = 'elderlife.access_token'

export function getToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY)
  } catch {
    // Private-browsing modes can throw on localStorage access.
    return null
  }
}

export function setToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token)
  } catch {
    // Ignore: the app still works for the current page without persistence.
  }
}

export function clearToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY)
  } catch {
    // Ignore.
  }
}
