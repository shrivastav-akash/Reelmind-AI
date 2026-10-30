// api.js as a user experiences it: what they see when uploads work, fail, or the
// server isn't there. IDs refer to docs/test-cases.md.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

async function loadApi({ mock = '0' } = {}) {
  vi.resetModules()
  vi.stubEnv('VITE_API_URL', 'http://api.test')
  vi.stubEnv('VITE_USE_MOCK', mock)
  return import('./api.js')
}

function reply(status, body, { html = false } = {}) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: html ? () => Promise.reject(new SyntaxError('Unexpected token <')) : () => Promise.resolve(body),
  })
}

beforeEach(() => vi.stubGlobal('fetch', vi.fn()))
afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
  window.history.replaceState({}, '', '/')
})

describe('analyze()', () => {
  it('sends the file and the topic as a multipart form (A1, A3)', async () => {
    const api = await loadApi()
    fetch.mockReturnValue(reply(202, { job_id: 'abc123def456' }))
    const file = new File(['x'], 'my reel (final) ✨.mp4', { type: 'video/mp4' })
    await expect(api.analyze(file, '#Cooking ')).resolves.toEqual({ job_id: 'abc123def456' })
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('http://api.test/analyze')
    expect(init.method).toBe('POST')
    expect(init.body.get('file').name).toBe('my reel (final) ✨.mp4')
    expect(init.body.get('topic')).toBe('#Cooking ')
  })

  it("shows the server's reason when the upload is refused (A9)", async () => {
    const api = await loadApi()
    fetch.mockReturnValue(reply(400, { detail: 'Video is 75 s; the limit is 60 s.' }))
    await expect(api.analyze(new File(['x'], 'long.mp4'), 'cooking')).rejects.toMatchObject({
      message: 'Video is 75 s; the limit is 60 s.',
      status: 400,
    })
  })

  it('gives a plain message when the server crashes with an HTML page', async () => {
    const api = await loadApi()
    fetch.mockReturnValue(reply(500, null, { html: true }))
    await expect(api.analyze(new File(['x'], 'a.mp4'), 'cooking')).rejects.toMatchObject({
      message: 'Something went wrong (500). Try again.',
    })
  })

  it("says the server can't be reached when the backend isn't running (C4)", async () => {
    const api = await loadApi()
    fetch.mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(api.analyze(new File(['x'], 'a.mp4'), 'cooking')).rejects.toMatchObject({
      message: "Can't reach the server. Is the backend running?",
      status: 0,
    })
  })

  it('passes on the replay message when no run was recorded (F2)', async () => {
    const api = await loadApi()
    fetch.mockReturnValue(reply(503, { detail: 'No recorded run found.' }))
    await expect(api.analyze(new File(['x'], 'a.mp4'), 'cooking')).rejects.toThrow('No recorded run found.')
  })

  it('ignores a validation error object and still shows words', async () => {
    const api = await loadApi()
    fetch.mockReturnValue(reply(422, { detail: [{ loc: ['body', 'file'], msg: 'Field required' }] }))
    await expect(api.analyze(new File(['x'], 'a.mp4'), 'cooking')).rejects.toThrow('Something went wrong (422). Try again.')
  })
})

describe('getJob()', () => {
  it('returns the job', async () => {
    const api = await loadApi()
    fetch.mockReturnValue(reply(200, { id: 'abc123def456', status: 'running' }))
    await expect(api.getJob('abc123def456')).resolves.toMatchObject({ status: 'running' })
    expect(fetch.mock.calls[0][0]).toBe('http://api.test/jobs/abc123def456')
  })

  it("says the analysis can't be found for an old or mistyped link (C6)", async () => {
    const api = await loadApi()
    fetch.mockReturnValue(reply(404, { detail: 'Not Found' }))
    await expect(api.getJob('nope')).rejects.toMatchObject({ status: 404 })
  })

  it('never lets a job id change the path (B12-style input)', async () => {
    const api = await loadApi()
    fetch.mockReturnValue(reply(404, {}))
    await api.getJob('../../admin?x=1').catch(() => {})
    expect(fetch.mock.calls[0][0]).toBe('http://api.test/jobs/..%2F..%2Fadmin%3Fx%3D1')
  })
})

describe('account API', () => {
  const user = { id: 1, email: 'creator@example.com', ig_handle: 'creator_one', profile_url: 'https://www.instagram.com/creator_one/', latest_report_id: null }

  it('stores the sign-up token and sends the expected body', async () => {
    const api = await loadApi()
    fetch.mockReturnValue(reply(201, { token: 'secret-session-token', user }))
    await expect(api.signUp({ email: user.email, password: 'correct-horse-battery', instagram_url: '@creator_one' }))
      .resolves.toMatchObject({ token: 'secret-session-token', user })
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('http://api.test/auth/signup')
    expect(JSON.parse(init.body)).toEqual({ email: user.email, password: 'correct-horse-battery', instagram_url: '@creator_one' })
    expect(localStorage.getItem('reelmind_token')).toBe('secret-session-token')
  })

  it('uses the saved bearer token for GET /me', async () => {
    const api = await loadApi()
    localStorage.setItem('reelmind_token', 'saved-token')
    fetch.mockReturnValue(reply(200, user))
    await expect(api.getMe()).resolves.toEqual(user)
    expect(fetch.mock.calls[0][0]).toBe('http://api.test/me')
    expect(fetch.mock.calls[0][1].headers).toEqual({ Authorization: 'Bearer saved-token' })
  })

  it('logs in with the same session shape as sign-up', async () => {
    const api = await loadApi()
    fetch.mockReturnValue(reply(200, { token: 'login-token', user }))
    await expect(api.signIn({ email: user.email, password: 'correct-horse-battery' }))
      .resolves.toMatchObject({ token: 'login-token', user })
    expect(fetch.mock.calls[0][0]).toBe('http://api.test/auth/login')
    expect(localStorage.getItem('reelmind_token')).toBe('login-token')
  })

  it('refreshes the current creator report with the saved bearer token', async () => {
    const api = await loadApi()
    localStorage.setItem('reelmind_token', 'saved-token')
    fetch.mockReturnValue(reply(202, { report_id: 'report123456' }))
    await expect(api.refreshMyReport()).resolves.toEqual({ report_id: 'report123456' })
    expect(fetch.mock.calls[0][0]).toBe('http://api.test/me/refresh')
    expect(fetch.mock.calls[0][1].headers).toEqual({ Authorization: 'Bearer saved-token' })
  })

  it('sends the assistant question, recent history, and bearer token', async () => {
    const api = await loadApi()
    localStorage.setItem('reelmind_token', 'saved-token')
    const answer = { answer: 'Question hooks reached 4x.', keys: ['pat.hook_type.question'], reel_ids: ['r1'], follow_ups: [] }
    fetch.mockReturnValue(reply(200, answer))
    await expect(api.askAssistant('What next?', [{ role: 'user', text: 'What works?' }])).resolves.toEqual(answer)
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('http://api.test/assistant')
    expect(init.headers.Authorization).toBe('Bearer saved-token')
    expect(JSON.parse(init.body)).toEqual({ message: 'What next?', history: [{ role: 'user', text: 'What works?' }] })
  })

  it('clears the local token after a 204 logout response', async () => {
    const api = await loadApi()
    localStorage.setItem('reelmind_token', 'saved-token')
    fetch.mockReturnValue(reply(204, null))
    await expect(api.signOut()).resolves.toBeUndefined()
    expect(fetch.mock.calls[0][0]).toBe('http://api.test/auth/logout')
    expect(localStorage.getItem('reelmind_token')).toBeNull()
  })

  it('clears the local token even when logout cannot reach the backend', async () => {
    const api = await loadApi()
    localStorage.setItem('reelmind_token', 'saved-token')
    fetch.mockRejectedValue(new TypeError('offline'))
    await expect(api.signOut()).rejects.toMatchObject({ status: 0 })
    expect(localStorage.getItem('reelmind_token')).toBeNull()
  })
})

describe('mock mode (building the UI before the API exists)', () => {
  it('never touches the network', async () => {
    const api = await loadApi({ mock: '1' })
    await expect(api.analyze(new File(['x'], 'a.mp4'), 'cooking')).resolves.toEqual({ job_id: 'mock' })
    await api.getJob('mock')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('plays running, running, then done', async () => {
    const api = await loadApi({ mock: '1' })
    const statuses = []
    for (let i = 0; i < 4; i += 1) statuses.push((await api.getJob('mock')).status)
    expect(statuses).toEqual(['running', 'running', 'done', 'done'])
  })

  it('?mock=failed pins the failed job', async () => {
    window.history.replaceState({}, '', '/?mock=failed')
    const api = await loadApi({ mock: '1' })
    expect((await api.getJob('mock')).status).toBe('failed')
  })
})
