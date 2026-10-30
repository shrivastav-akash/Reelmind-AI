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
import mockCreator from './mocks/report.creator.json'
import mockCreatorRunning from './mocks/report.creator.running.json'
import mockNiche from './mocks/report.niche.json'
import mockReel from './mocks/report.reel.json'

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

// ---------------------------------------------------------------- v2 reports (backend/report_models.py)

export const REPORT_NOT_FOUND = "We couldn't find that report."
const MOCK_REPORTS = { creator: mockCreator, reel: mockReel, niche: mockNiche }

// POST /reports/{kind} with { handle_or_url } | { url } | { keywords: [...] }. Resolves to
// { report_id }; a 400 rejects with the server's reason (e.g. "Paste an Instagram Reel link…").
export async function startReport(kind, body) {
  if (USE_MOCK) return { report_id: `mock-${kind}` }
  return request(`/reports/${kind}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

// GET /reports/{id}. Resolves to a ReportJob. Mock mode: the creator mock runs once, then is done.
let mockReportPolls = 0
export async function getReport(reportId) {
  if (USE_MOCK) {
    const kind = String(reportId).replace('mock-', '')
    mockReportPolls += 1
    if (kind === 'creator' && mockReportPolls < 2) return mockCreatorRunning
    return MOCK_REPORTS[kind] ?? mockCreator
  }
  if (!reportId || reportId.startsWith('mock-')) throw apiError(REPORT_NOT_FOUND, 404)
  return request(`/reports/${encodeURIComponent(reportId)}`)
}
