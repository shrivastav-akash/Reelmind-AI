import { useEffect, useState } from 'react'
import { UNREACHABLE } from './api'

const POLL_MS = 2000
const MAX_FAILURES = 3
const EMPTY = { data: null, error: null }

// Polls fetchOne(id) every 2 s until it returns status "done" or "failed". Shared by useJob (v1
// draft analysis) and useReport (v2 reports). The next poll is only scheduled after the previous
// one answers, so a slow server never gets a pile-up. Returns { data, error }:
// - one failed poll is forgiven (Wi-Fi blips); after 3 in a row, error = "Can't reach the
//   server" and polling stops so the UI can offer a retry;
// - a 404 stops at once with `notFound` (an old or mistyped link).
// Bump `attempt` (e.g. from a "Try again" button) to start polling the same id afresh.
export function usePolling(fetchOne, id, attempt, notFound) {
  // State remembers which id + attempt it belongs to, so a new id (or a retry) never
  // shows the old data or the old error.
  const key = id ? `${id}#${attempt}` : null
  const [state, setState] = useState({ key: null, ...EMPTY })

  useEffect(() => {
    if (!id) return undefined
    let stopped = false
    let failures = 0
    let timer

    async function poll() {
      try {
        const next = await fetchOne(id)
        if (stopped) return
        failures = 0
        setState({ key, data: next, error: null })
        if (next.status === 'done' || next.status === 'failed') return
      } catch (err) {
        if (stopped) return
        if (err?.status === 404) {
          setState({ key, data: null, error: notFound })
          return
        }
        failures += 1
        if (failures >= MAX_FAILURES) {
          setState((s) => ({ key, data: s.key === key ? s.data : null, error: UNREACHABLE }))
          return
        }
      }
      timer = setTimeout(poll, POLL_MS)
    }

    poll()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [fetchOne, id, attempt, key, notFound])

  return state.key === key ? state : { key, ...EMPTY }
}
