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
  if (res.status === 204) return null
  // A 2xx that isn't JSON didn't come from our API (e.g. a dev server answering with index.html).
  if (data === null) throw apiError(`Something went wrong (${res.status}). Try again.`, res.status)
  return data
}

const TOKEN_KEY = 'reelmind_token'

function authHeaders() {
  const token = localStorage.getItem(TOKEN_KEY)
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function saveSession(session) {
  if (!session?.token || !session?.user) throw apiError('The server returned an incomplete sign-in response.', 500)
  localStorage.setItem(TOKEN_KEY, session.token)
  return session
}

export function hasSession() {
  return Boolean(localStorage.getItem(TOKEN_KEY))
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
}

export async function signUp(body) {
  if (USE_MOCK) return saveSession({ token: 'mock-token', user: { id: 1, email: body.email, ig_handle: body.instagram_url.replace(/^@/, ''), profile_url: `https://www.instagram.com/${body.instagram_url.replace(/^@/, '')}/`, latest_report_id: 'mockcreator1' } })
  return saveSession(await request('/auth/signup', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }))
}

export async function signIn(body) {
  if (USE_MOCK) return saveSession({ token: 'mock-token', user: { id: 1, email: body.email, ig_handle: 'mock_kitchen_a', profile_url: 'https://www.instagram.com/mock_kitchen_a/', latest_report_id: 'mockcreator1' } })
  return saveSession(await request('/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }))
}

export async function getMe() {
  if (USE_MOCK) return { id: 1, email: 'mock.user@example.com', ig_handle: 'mock_kitchen_a', profile_url: 'https://www.instagram.com/mock_kitchen_a/', latest_report_id: 'mockcreator1' }
  return request('/me', { headers: authHeaders() })
}

export async function signOut() {
  try {
    if (!USE_MOCK && hasSession()) await request('/auth/logout', { method: 'POST', headers: authHeaders() })
  } finally {
    clearSession()
  }
}

export async function refreshMyReport() {
  if (USE_MOCK) return { report_id: 'mockcreator1' }
  return request('/me/refresh', { method: 'POST', headers: authHeaders() })
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
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
  })
}

export async function askAssistant(message, history) {
  if (USE_MOCK) return {
    answer: 'Question hooks reached 4.1x your usual views across two recent Reels.',
    keys: ['pat.hook_type.question'], reel_ids: ['r1', 'r3'], follow_ups: ['Which question hooks should I try?'],
  }
  return request('/assistant', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ message, history }),
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
