import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import StudioPage from './StudioPage'
import creator from './mocks/report.creator.json'
import { getReport, refreshMyReport } from './api'

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal()),
  getReport: vi.fn(),
  refreshMyReport: vi.fn(),
}))

const user = { id: 1, email: 'mock.user@example.com', ig_handle: 'mock_kitchen_a', profile_url: 'https://www.instagram.com/mock_kitchen_a/', latest_report_id: 'report123456' }

beforeEach(() => {
  getReport.mockReset()
  refreshMyReport.mockReset()
})

describe('My Studio', () => {
  it('opens the saved creator report and shows the linked profile', async () => {
    getReport.mockResolvedValue(creator)
    render(<StudioPage user={user} />)
    expect(await screen.findByRole('region', { name: 'Insights' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open Instagram profile' })).toHaveAttribute('href', user.profile_url)
    expect(screen.getByRole('region', { name: 'Cover visuals' })).toBeInTheDocument()
    expect(getReport).toHaveBeenCalledWith(user.latest_report_id)
  })

  it('starts a report when none is saved, then renders its result', async () => {
    getReport.mockResolvedValue(creator)
    refreshMyReport.mockResolvedValue({ report_id: 'fresh123456' })
    const onReportStarted = vi.fn()
    const userAction = userEvent.setup()
    render(<StudioPage user={{ ...user, latest_report_id: null }} onReportStarted={onReportStarted} />)
    expect(screen.getByText(/profile is saved/i)).toBeInTheDocument()
    await userAction.click(screen.getByRole('button', { name: 'Start my report' }))
    await screen.findByRole('region', { name: 'Insights' })
    expect(refreshMyReport).toHaveBeenCalledOnce()
    expect(onReportStarted).toHaveBeenCalledWith('fresh123456')
    await waitFor(() => expect(getReport).toHaveBeenCalledWith('fresh123456'))
    expect(within(screen.getByRole('region', { name: 'Creator profile' })).getByText('@mock_kitchen_a')).toBeInTheDocument()
  })

  it('shows the backend reason when a refresh cannot start', async () => {
    refreshMyReport.mockRejectedValue(Object.assign(new Error('No recorded report of @mock_kitchen_a to replay.'), { status: 503 }))
    const userAction = userEvent.setup()
    render(<StudioPage user={{ ...user, latest_report_id: null }} />)
    await userAction.click(screen.getByRole('button', { name: 'Start my report' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('No recorded report of @mock_kitchen_a to replay.')
  })
})
