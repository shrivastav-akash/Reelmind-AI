// The only file that talks to the backend. Components call analyze() and getJob().
// With VITE_USE_MOCK=1 both return the mock jobs in ./mocks, so the UI can be
// built before the API exists. The mock shapes match backend/models.py (a
// backend test fails if they drift).
import mockDone from './mocks/job.done.json'
import mockRunning from './mocks/job.running.json'
import mockFailed from './mocks/job.failed.json'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
export const USE_MOCK = import.meta.env.VITE_USE_MOCK === '1'

// POST /analyze. Resolves to { job_id }; throws with the server's reason on a 400.
export async function analyze(file, topic) {
  if (USE_MOCK) return { job_id: 'mock' }
  const body = new FormData()
  body.append('file', file)
  body.append('topic', topic)
  const res = await fetch(`${API_URL}/analyze`, { method: 'POST', body })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail ?? `Upload failed (${res.status})`)
  return data
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
  const res = await fetch(`${API_URL}/jobs/${jobId}`)
  if (!res.ok) throw new Error(`Couldn't load the job (${res.status})`)
  return res.json()
}
