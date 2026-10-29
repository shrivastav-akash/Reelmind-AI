import { useEffect, useState } from 'react'
import { getJob } from './api'

const POLL_MS = 2000
const MAX_FAILURES = 3
const EMPTY = { job: null, error: null }

// Polls GET /jobs/{id} every 2 s until the job is done or failed.
// Returns { job, error }: `error` is set after 3 failed polls in a row
// (backend down), and polling stops so the UI can offer a retry.
export function useJob(jobId) {
  // State remembers which job it belongs to, so a new jobId never shows the old job.
  const [state, setState] = useState({ jobId: null, ...EMPTY })

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
        setState({ jobId, job: next, error: null })
        if (next.status === 'done' || next.status === 'failed') return
      } catch {
        if (stopped) return
        failures += 1
        if (failures >= MAX_FAILURES) {
          setState((s) => ({ ...s, jobId, error: "Can't reach the server" }))
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
  }, [jobId])

  return state.jobId === jobId ? { job: state.job, error: state.error } : EMPTY
}
