import { useEffect, useState } from 'react'
import { getJob, NOT_FOUND, UNREACHABLE } from './api'

const POLL_MS = 2000
const MAX_FAILURES = 3
const EMPTY = { job: null, error: null }

// Polls GET /jobs/{id} every 2 s until the job is done or failed. The next poll is
// only scheduled after the previous one answers, so a slow server never gets a pile-up.
// Returns { job, error }:
// - one failed poll is forgiven (Wi-Fi blips); after 3 in a row, error = "Can't reach the
//   server" and polling stops so the UI can offer a retry;
// - a 404 stops at once with "We couldn't find that analysis." (old or mistyped link).
// Bump `attempt` (e.g. from a "Try again" button) to start polling the same job afresh.
export function useJob(jobId, attempt = 0) {
  // State remembers which job + attempt it belongs to, so a new job (or a retry) never
  // shows the old job or the old error.
  const key = jobId ? `${jobId}#${attempt}` : null
  const [state, setState] = useState({ key: null, ...EMPTY })

  useEffect(() => {
    if (!jobId) return undefined
    let stopped = false
    let failures = 0
    let timer

    async function poll() {
      try {
        const next = await getJob(jobId)
        if (stopped) return
        failures = 0
        setState({ key, job: next, error: null })
        if (next.status === 'done' || next.status === 'failed') return
      } catch (err) {
        if (stopped) return
        if (err?.status === 404) {
          setState({ key, job: null, error: NOT_FOUND })
          return
        }
        failures += 1
        if (failures >= MAX_FAILURES) {
          setState((s) => ({ key, job: s.key === key ? s.job : null, error: UNREACHABLE }))
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
  }, [jobId, attempt, key])

  return state.key === key ? { job: state.job, error: state.error } : EMPTY
}
