/**
 * A small data-fetching hook that guarantees every page handles all four
 * states properly: loading, error, empty, and success.
 *
 * The project rule is that "an empty dashboard must not look broken" — the
 * easiest way to honour that is to make the four states impossible to forget,
 * which is what returning all of them from one hook achieves.
 *
 * Usage:
 *   const profiles = useApi(() => api.listProfiles(), [])
 *   if (profiles.loading) return <LoadingState />
 *   if (profiles.error)   return <ErrorState error={profiles.error} onRetry={profiles.reload} />
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, NetworkError } from '../api/errors'

export interface ApiState<T> {
  data: T | null
  loading: boolean
  error: ApiError | NetworkError | null
  /** Re-run the request (used by "Try again" buttons). */
  reload: () => void
}

export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: ReadonlyArray<unknown>,
  options?: { enabled?: boolean },
): ApiState<T> {
  const enabled = options?.enabled ?? true

  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(enabled)
  const [error, setError] = useState<ApiError | NetworkError | null>(null)
  const [nonce, setNonce] = useState(0)

  // Keep the latest fetcher without making it a dependency, so callers can pass
  // an inline arrow function without causing an infinite refetch loop.
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const reload = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      return
    }

    let cancelled = false
    setLoading(true)
    setError(null)

    async function run() {
      try {
        const result = await fetcherRef.current()
        if (!cancelled) setData(result)
      } catch (caught) {
        if (!cancelled) {
          setError(
            caught instanceof ApiError || caught instanceof NetworkError
              ? caught
              : new NetworkError('Something unexpected went wrong.'),
          )
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void run()
    return () => {
      cancelled = true
    }
    // `deps` is spread so callers control refetching precisely.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, enabled])

  return { data, loading, error, reload }
}
