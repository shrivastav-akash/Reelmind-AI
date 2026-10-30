// Defines "done" for the UI (Fri tasks S1-S4).
// Each test does what a real user does: picks a file, types a topic, clicks, waits,
// refreshes, follows a link. Elements are found by their visible label/role, the way
// people and screen readers find them; the labels are the contract in
// docs/ui-ux-brief.md ("Test contract"). IDs refer to docs/test-cases.md.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { analyze, getJob } from './api'
import done from './mocks/job.done.json'
import failed from './mocks/job.failed.json'
import running from './mocks/job.running.json'

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal()),
  USE_MOCK: false,
  analyze: vi.fn(),
  getJob: vi.fn(),
}))

const BANNED = /\b(viral\w*|guarantee\w*|algorithm\w*|secret\w*|will get)\b/i
const JOB_ID = 'abc123def456'
const clip = (name = 'draft.mp4') => new File(['fake video'], name, { type: 'video/mp4' })
const copy = (job, changes = {}) => ({ ...structuredClone(job), ...changes })

beforeEach(() => {
  vi.useRealTimers()
  analyze.mockReset()
  getJob.mockReset()
  window.history.replaceState({}, '', '/')
})

// The user picks a file, types a topic and clicks Analyse; the backend answers with `job`.
async function analyseWith(job, { topic = 'cooking', file = clip() } = {}) {
  analyze.mockResolvedValue({ job_id: JOB_ID })
  getJob.mockResolvedValue(job)
  const user = userEvent.setup()
  render(<App />)
  if (file) await user.upload(screen.getByLabelText(/draft video/i), file)
  if (topic) await user.type(screen.getByLabelText(/topic/i), topic)
  await user.click(screen.getByRole('button', { name: /^analyse$/i }))
  return user
}

describe('uploading', () => {
  it('Analyse stays disabled until there is a video and a topic (A20, B7)', async () => {
    const user = userEvent.setup()
    render(<App />)
    const button = screen.getByRole('button', { name: /^analyse$/i })
    expect(button).toBeDisabled()
    await user.upload(screen.getByLabelText(/draft video/i), clip())
    expect(button).toBeDisabled()
    await user.type(screen.getByLabelText(/topic/i), '   ')
    expect(button).toBeDisabled()
    await user.type(screen.getByLabelText(/topic/i), 'cooking')
    expect(button).toBeEnabled()
  })

  it('only offers .mp4 and .mov in the file picker (A4)', () => {
    render(<App />)
    expect(screen.getByLabelText(/draft video/i)).toHaveAttribute('accept', expect.stringMatching(/\.mp4.*\.mov|\.mov.*\.mp4/))
  })

  it('sends exactly what the user chose (A3)', async () => {
    await analyseWith(done, { file: clip('my reel (final) ✨.MOV'), topic: '#Cooking' })
    expect(analyze).toHaveBeenCalledWith(expect.objectContaining({ name: 'my reel (final) ✨.MOV' }), '#Cooking')
  })

  it("shows the server's reason when the video is refused, and lets them retry (A9)", async () => {
    analyze.mockRejectedValue(Object.assign(new Error('Video is 75 s; the limit is 60 s.'), { status: 400 }))
    const user = userEvent.setup()
    render(<App />)
    await user.upload(screen.getByLabelText(/draft video/i), clip())
    await user.type(screen.getByLabelText(/topic/i), 'cooking')
    await user.click(screen.getByRole('button', { name: /^analyse$/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Video is 75 s; the limit is 60 s.')
    expect(screen.getByRole('button', { name: /^analyse$/i })).toBeEnabled()
    expect(getJob).not.toHaveBeenCalled()
  })

  it('a double click sends one upload (C1)', async () => {
    let finish
    analyze.mockImplementation(() => new Promise((resolve) => { finish = resolve }))
    getJob.mockResolvedValue(done)
    const user = userEvent.setup()
    render(<App />)
    await user.upload(screen.getByLabelText(/draft video/i), clip())
    await user.type(screen.getByLabelText(/topic/i), 'cooking')
    await user.dblClick(screen.getByRole('button', { name: /^analyse$/i }))
    finish({ job_id: JOB_ID })
    await screen.findByRole('region', { name: /recommendation/i })
    expect(analyze).toHaveBeenCalledTimes(1)
  })

  it('puts the job in the address bar so a refresh keeps it (C5)', async () => {
    await analyseWith(done)
    await waitFor(() => expect(window.location.search).toContain(`job=${JOB_ID}`))
  })

  it('can be used with the keyboard alone', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.tab() // the tool tabs come first: one Tab stop, arrow keys move between them
    expect(screen.getByRole('tab', { name: 'Analyse a draft' })).toHaveFocus()
    await user.tab()
    expect(screen.getByLabelText(/draft video/i)).toHaveFocus()
    await user.tab()
    expect(screen.getByLabelText(/topic/i)).toHaveFocus()
  })
})

describe('while it runs', () => {
  it('shows the live research, then the result (C2, D1)', async () => {
    analyze.mockResolvedValue({ job_id: JOB_ID })
    getJob.mockResolvedValueOnce(running).mockResolvedValue(done)
    const user = userEvent.setup()
    render(<App />)
    await user.upload(screen.getByLabelText(/draft video/i), clip())
    await user.type(screen.getByLabelText(/topic/i), 'cooking')
    await user.click(screen.getByRole('button', { name: /^analyse$/i }))
    const scout = await screen.findByRole('region', { name: /niche scout/i })
    expect(await within(scout).findByText(/Agent picked 3 creators/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /analyse/i })).toBeDisabled()
    expect(await screen.findByText(/Opening on the finished dish/, {}, { timeout: 4000 })).toBeInTheDocument()
  })

  it('links to the live browser view while the Agent works', async () => {
    await analyseWith(running)
    const link = await screen.findByRole('link', { name: /watch the agent live/i })
    expect(link).toHaveAttribute('href', running.live_view_url)
    expect(link).toHaveAttribute('target', '_blank')
  })

  it('resumes the same job after a refresh (C5)', async () => {
    window.history.replaceState({}, '', `/?job=${JOB_ID}`)
    getJob.mockResolvedValue(done)
    render(<App />)
    expect(await screen.findByRole('region', { name: /recommendation/i })).toBeInTheDocument()
    expect(getJob).toHaveBeenCalledWith(JOB_ID)
    expect(analyze).not.toHaveBeenCalled()
  })

  it("says so when an old link points nowhere (C6)", async () => {
    window.history.replaceState({}, '', '/?job=000000000000')
    getJob.mockRejectedValue(Object.assign(new Error('Not Found'), { status: 404 }))
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent("We couldn't find that analysis.")
  })

  it("says the server can't be reached and offers to try again (C4)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    window.history.replaceState({}, '', `/?job=${JOB_ID}`)
    getJob.mockRejectedValue(Object.assign(new Error('down'), { status: 0 }))
    render(<App />)
    await vi.advanceTimersByTimeAsync(4500)
    expect(await screen.findByRole('alert')).toHaveTextContent(/can't reach the server/i)
    getJob.mockResolvedValue(done)
    screen.getByRole('button', { name: /try again/i }).click()
    expect(await screen.findByRole('region', { name: /recommendation/i })).toBeInTheDocument()
  })
})

describe('the research panel', () => {
  it('says every creator status in words, not only colour (D8, G4)', async () => {
    await analyseWith(done)
    const list = await screen.findByRole('list', { name: /creators/i })
    const rows = within(list).getAllByRole('listitem')
    expect(rows).toHaveLength(3)
    expect(within(rows[0]).getByText(/@mock_kitchen_a/)).toBeInTheDocument()
    expect(within(rows[0]).getByText('Accessible')).toBeInTheDocument()
    expect(within(rows[1]).getByText('Login wall')).toBeInTheDocument()
  })

  it("shows why the Agent picked each creator, as the Agent's words (G6)", async () => {
    await analyseWith(done)
    const list = await screen.findByRole('list', { name: /creators/i })
    expect(within(list).getByText(/Agent's pick:.*Home cook posting quick everyday recipes/)).toBeInTheDocument()
  })

  it.each([
    ['blocked', 'Blocked'],
    ['not_found', 'Not found'],
    ['timeout', 'Timed out'],
  ])('shows %s as "%s"', async (status, words) => {
    const job = copy(done)
    job.creators[1].access_status = status
    await analyseWith(job)
    expect(within(await screen.findByRole('list', { name: /creators/i })).getByText(words)).toBeInTheDocument()
  })
})

describe('the result', () => {
  it('shows the four parts of the card (E1)', async () => {
    await analyseWith(done)
    const card = await screen.findByRole('region', { name: /recommendation/i })
    for (const heading of [/observed/i, /evidence/i, /hypothesis/i, /experiment/i]) {
      expect(within(card).getByRole('heading', { name: heading })).toBeInTheDocument()
    }
    expect(within(card).getByText(/Start on the finished curry/)).toBeInTheDocument()
  })

  it('opens every evidence Reel in a new tab, with when we read it (E11)', async () => {
    await analyseWith(done)
    const card = await screen.findByRole('region', { name: /recommendation/i })
    const link = within(card).getByRole('link', { name: "Open @mock_kitchen_a's Reel on Instagram" })
    expect(link).toHaveAttribute('href', 'https://www.instagram.com/reel/MOCK0000001/')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link.getAttribute('rel')).toMatch(/noopener/)
    expect(link.getAttribute('rel')).toMatch(/noreferrer/)
    expect(within(card).getAllByText(/retrieved/i).length).toBeGreaterThanOrEqual(2)
  })

  it('marks values that come from the vision model as estimated (E10)', async () => {
    await analyseWith(done)
    const panel = await screen.findByRole('region', { name: /your video/i })
    expect(within(panel).getAllByText(/6\.2\s*s/).length).toBeGreaterThanOrEqual(1)
    expect(within(panel).getAllByText(/estimated/i).length).toBeGreaterThanOrEqual(1)
  })

  it('never shows 0 for a number Instagram hides (D13)', async () => {
    await analyseWith(done)
    const card = await screen.findByRole('region', { name: /recommendation/i })
    expect(within(card).getByText(/not shown publicly/i)).toBeInTheDocument()
  })

  it('never shows hype words anywhere on the page (E3)', async () => {
    await analyseWith(done)
    await screen.findByRole('region', { name: /recommendation/i })
    expect(document.body.textContent).not.toMatch(BANNED)
  })

  it("says plainly when there wasn't enough evidence, and shows no card (E7)", async () => {
    await analyseWith(copy(done, { examples: [], recommendation: { suggestions: [], source: 'insufficient_evidence', validator_report: [] } }))
    expect(await screen.findByText(/couldn't reach enough public Reels/i)).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /hypothesis/i })).not.toBeInTheDocument()
  })

  it('explains a failed job and offers to try again (D16)', async () => {
    await analyseWith(failed)
    expect(await screen.findByRole('alert')).toHaveTextContent(/wallet can't cover this run/)
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  it('clears the old result when the user analyses another video (C7)', async () => {
    const user = await analyseWith(done)
    await user.click(await screen.findByRole('button', { name: /analyse another/i }))
    expect(screen.queryByRole('region', { name: /recommendation/i })).not.toBeInTheDocument()
    expect(screen.getByLabelText(/draft video/i).files).toHaveLength(0)
    expect(window.location.search).not.toContain('job=')
  })
})

describe('replay (demo safety)', () => {
  it('always says a replay is a replay, with when it was recorded (F1)', async () => {
    await analyseWith(copy(done, { replay: true, replay_recorded_at: '2026-10-30T15:12:00+05:30' }))
    const banner = await screen.findByText(/replay of a recorded run/i)
    expect(banner).toBeVisible()
    expect(banner.textContent).toMatch(/15:12|3:12/)
  })

  it('shows no banner for a live run', async () => {
    await analyseWith(done)
    await screen.findByRole('region', { name: /recommendation/i })
    expect(screen.queryByText(/replay of a recorded run/i)).not.toBeInTheDocument()
  })
})
