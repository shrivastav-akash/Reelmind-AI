// Defines "done" for the v2 tabs (Creator, Reel, Niche Pulse). Like App.test.jsx, each test does
// what a user does, finds things by label and role, and the backend is faked with the mocks
// that backend/tests/test_report_models.py keeps in step with backend/report_models.py.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { getReport, startReport } from './api'
import creator from './mocks/report.creator.json'
import niche from './mocks/report.niche.json'
import reel from './mocks/report.reel.json'

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal()),
  USE_MOCK: false,
  startReport: vi.fn(),
  getReport: vi.fn(),
}))

const BANNED = /\b(viral\w*|guarantee\w*|algorithm\w*|secret\w*|will get)\b/i
const ID = 'abcdefabcdef'

beforeEach(() => {
  startReport.mockReset()
  getReport.mockReset()
  window.history.replaceState({}, '', '/?tab=draft')
})

async function openTab(user, name) {
  render(<App />)
  await user.click(screen.getByRole('tab', { name }))
}

async function run(tab, label, text, report) {
  const user = userEvent.setup()
  startReport.mockResolvedValue({ report_id: ID })
  getReport.mockResolvedValue(report)
  await openTab(user, tab)
  await user.type(screen.getByLabelText(label), text)
  await user.click(screen.getByRole('button', { name: new RegExp(`^${report.kind === 'niche' ? 'run niche pulse' : `analyse ${report.kind}`}$`, 'i') }))
  return user
}

describe('tabs', () => {
  it('opens on the draft tool and switches tools without a page load', async () => {
    const user = userEvent.setup()
    await openTab(user, 'Creator')
    expect(screen.getByRole('tab', { name: 'Creator' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByLabelText(/instagram handle or profile link/i)).toBeInTheDocument()
    expect(window.location.search).toBe('?tab=creator')
    await user.click(screen.getByRole('tab', { name: 'Analyse a draft' }))
    expect(screen.getByLabelText(/draft video/i)).toBeInTheDocument()
  })

  it('moves between tabs with the arrow keys', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.tab()
    await user.tab() // home link precedes the tool tablist
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Creator' })).toHaveFocus()
    expect(screen.getByRole('tab', { name: 'Creator' })).toHaveAttribute('aria-selected', 'true')
  })

  it('reopens a report from a shared link', async () => {
    window.history.replaceState({}, '', `/?tab=reel&report=${ID}`)
    getReport.mockResolvedValue(reel)
    render(<App />)
    expect(await screen.findByRole('region', { name: 'This Reel' })).toBeInTheDocument()
    expect(getReport).toHaveBeenCalledWith(ID)
  })
})

describe('creator report', () => {
  it('sends the handle and shows profile, insights, Reels and patterns', async () => {
    await run('Creator', /instagram handle or profile link/i, '@mock_kitchen_a', creator)
    expect(startReport).toHaveBeenCalledWith('creator', { handle_or_url: '@mock_kitchen_a' })
    await waitFor(() => expect(window.location.search).toBe(`?tab=creator&report=${ID}`))
    const profile = await screen.findByRole('region', { name: 'Creator profile' })
    expect(within(profile).getByText('Reels in the last 7 days')).toBeInTheDocument()
    expect(within(profile).getByText('4')).toBeInTheDocument()
    expect(within(profile).getByText(/Video length isn't on public Reel pages/)).toBeInTheDocument()
    const insights = screen.getByRole('region', { name: 'Insights' })
    for (const heading of ['Working', 'Not working', 'Try next']) {
      expect(within(insights).getByRole('heading', { name: heading })).toBeInTheDocument()
    }
    expect(screen.getByRole('region', { name: 'Patterns' })).toBeInTheDocument()
    const covers = screen.getByRole('region', { name: 'Cover visuals' })
    expect(within(covers).getByText('Estimated from public cover images')).toBeInTheDocument()
    expect(within(covers).getByText(/3 CHUTNEYS IN 5 MIN/)).toBeInTheDocument()
    expect(within(covers).getByRole('img', { name: 'Cover image for r1' })).toHaveAttribute('loading', 'lazy')
    expect(screen.getByRole('table')).toBeInTheDocument()
  })

  it('links every cited Reel to its row, which opens on Instagram', async () => {
    await run('Creator', /instagram handle or profile link/i, 'mock_kitchen_a', creator)
    const insights = await screen.findByRole('region', { name: 'Insights' })
    for (const chip of within(insights).getAllByRole('link')) {
      const row = document.querySelector(chip.getAttribute('href'))
      expect(row).not.toBeNull()
      expect(within(row).getByRole('link', { name: /open reel r\d+ on instagram/i })).toHaveAttribute('target', '_blank')
    }
  })

  it('marks the last 7 days and says so in words', async () => {
    await run('Creator', /instagram handle or profile link/i, 'mock_kitchen_a', creator)
    const reels = await screen.findByRole('region', { name: 'Recent Reels' })
    const inWindow = creator.result.reels.filter((r) => r.in_window).length
    expect(within(reels).getAllByText('7 days')).toHaveLength(inWindow)
  })

  it('shows what still runs, with the reason a step was skipped', async () => {
    const running = structuredClone(creator)
    running.status = 'running'
    running.stages.insights = { status: 'skipped', reason: 'Not built yet (task 1.4)' }
    running.result.insights = []
    await run('Creator', /instagram handle or profile link/i, 'mock_kitchen_a', running)
    const progress = await screen.findByRole('region', { name: 'Progress' })
    expect(within(progress).getAllByText('Not built yet (task 1.4)').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /analyse creator/i })).toBeDisabled()
  })

  it("shows the server's reason for a handle it can't read, with no retry", async () => {
    const user = userEvent.setup()
    const err = Object.assign(new Error('Enter an Instagram handle like @cookwithx'), { status: 400 })
    startReport.mockRejectedValue(err)
    await openTab(user, 'Creator')
    await user.type(screen.getByLabelText(/instagram handle or profile link/i), 'has space')
    await user.click(screen.getByRole('button', { name: /analyse creator/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter an Instagram handle like @cookwithx')
    expect(screen.queryByRole('button', { name: /try again/i })).toBeNull()
  })

  it('shows a failed report in words', async () => {
    const failed = { ...structuredClone(creator), status: 'failed', error: "@private_one: Login wall: this account's Reels aren't public" }
    await run('Creator', /instagram handle or profile link/i, 'private_one', failed)
    expect(await screen.findByRole('alert')).toHaveTextContent("Login wall: this account's Reels aren't public")
  })
})

describe('Reel report', () => {
  it("compares the Reel with its creator's usual", async () => {
    await run('Reel', /instagram reel link/i, 'https://www.instagram.com/reel/MOCK0000000/', reel)
    expect(startReport).toHaveBeenCalledWith('reel', { url: 'https://www.instagram.com/reel/MOCK0000000/' })
    const table = await screen.findByRole('table', { name: "Compared with @mock_kitchen_a's usual" })
    expect(within(table).getByRole('rowheader', { name: 'Hook type' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: "@mock_kitchen_a's recent Reels" })).toBeInTheDocument()
    expect(document.getElementById('reel-r0')).not.toBeNull() // insights cite r0
  })
})

describe('Niche Pulse', () => {
  it('sends up to 3 keywords and shows outliers, changes and web results', async () => {
    await run('Niche Pulse', /keywords or hashtags/i, 'cooking, #dal', niche)
    expect(startReport).toHaveBeenCalledWith('niche', { keywords: ['cooking', '#dal'] })
    const outliers = await screen.findByRole('region', { name: 'Outliers today' })
    expect(within(outliers).getAllByText(/@mock_kitchen_/).length).toBe(niche.result.reels.length)
    const summary = screen.getByRole('region', { name: 'Niche Pulse' })
    expect(within(summary).getByText(niche.result.since_last_run[0])).toBeInTheDocument()
    const web = screen.getByRole('region', { name: 'On the web' })
    expect(within(web).getAllByRole('link')).toHaveLength(niche.result.web.length)
  })
})

describe('honesty', () => {
  it.each([['Creator', creator], ['Reel', reel], ['Niche Pulse', niche]])('%s report shows no banned words', async (tab, report) => {
    window.history.replaceState({}, '', `/?tab=${report.kind}&report=${ID}`)
    getReport.mockResolvedValue(report)
    render(<App />)
    const insights = await screen.findByRole('region', { name: 'Insights' })
    expect(within(insights).queryByText(BANNED)).toBeNull()
  })

  it('labels a replay so it never passes for live', async () => {
    window.history.replaceState({}, '', `/?tab=creator&report=${ID}`)
    getReport.mockResolvedValue({ ...creator, replay: true, replay_recorded_at: '2026-10-30T06:54:13Z' })
    render(<App />)
    expect(await screen.findByText(/Replay of a recorded run.*Nothing on this page is live/)).toBeInTheDocument()
  })
})
