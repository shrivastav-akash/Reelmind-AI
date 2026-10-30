// The only file that talks to the backend. Components call analyze() and getJob().
// With VITE_USE_MOCK=1 both return the mock jobs in ./mocks, so the UI can be
// built before the API exists. The mock shapes match backend/models.py (a
// backend test fails if they drift).
//
// Errors thrown here carry a message a user can read as-is, plus `status`
// (the HTTP code, or 0 when the server couldn't be reached at all).
import mockDone from './mocks/job.done.json'
import mockRunning from './mocks/job.running.json'
import mockFailed from './mocks/job.failed.json'

// `||`, not `??`: a blank VITE_API_URL= line would otherwise send requests to the Vite server.
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
export const USE_MOCK = import.meta.env.VITE_USE_MOCK === '1'

export const UNREACHABLE = "Can't reach the server. Is the backend running?"
export const NOT_FOUND = "We couldn't find that analysis."

function apiError(message, status) {
  const err = new Error(message)
  err.status = status
  return err
}

async function request(path, init) {
  let res
  try {
    res = await fetch(`${API_URL}${path}`, init)
  } catch {
    throw apiError(UNREACHABLE, 0) // backend not started, Wi-Fi down, CORS
  }
  // FastAPI sends {"detail": "..."}; a crash may send HTML, so never trust the body.
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const fallback = res.status === 404 ? NOT_FOUND : `Something went wrong (${res.status}). Try again.`
    throw apiError(typeof data?.detail === 'string' ? data.detail : fallback, res.status)
  }
  // A 2xx that isn't JSON didn't come from our API (e.g. a dev server answering with index.html).
  if (data === null) throw apiError(`Something went wrong (${res.status}). Try again.`, res.status)
  return data
}

// POST /analyze. Resolves to { job_id }; a 400 rejects with the server's reason
// (e.g. "Video is 75 s; the limit is 60 s.").
export async function analyze(file, topic) {
  if (USE_MOCK) return { job_id: 'mock' }
  const body = new FormData()
  body.append('file', file)
  body.append('topic', topic)
  return request('/analyze', { method: 'POST', body })
}

// Mock mode plays "running" twice, then "done", so the UI sees both states.
// Add ?mock=done, ?mock=running or ?mock=failed to the page URL to pin one.
let mockPolls = 0
function mockJob() {
  const pinned = new URLSearchParams(window.location.search).get('mock')
  if (pinned) return { done: mockDone, running: mockRunning, failed: mockFailed }[pinned] ?? mockDone
  mockPolls += 1
  return mockPolls < 3 ? mockRunning : mockDone
}

// GET /jobs/{id}. Resolves to a Job (see backend/models.py).
export async function getJob(jobId) {
  if (USE_MOCK) return mockJob()
  return request(`/jobs/${encodeURIComponent(jobId)}`)
}
