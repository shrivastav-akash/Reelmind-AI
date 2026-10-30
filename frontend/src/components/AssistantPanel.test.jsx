import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AssistantPanel from './AssistantPanel'
import { askAssistant } from '../api'

vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal()),
  askAssistant: vi.fn(),
}))

beforeEach(() => askAssistant.mockReset())

describe('Creator assistant', () => {
  it('starts from a prompt and links citations to the report', async () => {
    askAssistant.mockResolvedValue({ answer: 'Question hooks reached 4.45x your usual views.',
      keys: ['pat.hook_type.question'], reel_ids: ['r1', 'r3'], follow_ups: ['Which should I try?'] })
    const user = userEvent.setup()
    render(<AssistantPanel ready />)
    await user.click(screen.getByRole('button', { name: "What's working for me?" }))
    const answer = await screen.findByText('Question hooks reached 4.45x your usual views.')
    expect(answer).toBeInTheDocument()
    expect(askAssistant).toHaveBeenCalledWith("What's working for me?", [])
    const conversation = screen.getByRole('list', { name: 'Conversation' })
    expect(within(conversation).getByRole('link', { name: 'r1' })).toHaveAttribute('href', '#reel-r1')
    expect(within(conversation).getByText('pat.hook_type.question')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Which should I try?' })).toBeInTheDocument()
  })

  it('sends recent turns with a typed question and shows request errors', async () => {
    askAssistant.mockResolvedValueOnce({ answer: 'Try a question hook.', keys: ['pat.hook_type.question'],
      reel_ids: ['r1'], follow_ups: [] }).mockRejectedValueOnce(new Error('Assistant unavailable.'))
    const user = userEvent.setup()
    render(<AssistantPanel ready />)
    await user.type(screen.getByLabelText('Your question'), 'What next?')
    await user.click(screen.getByRole('button', { name: 'Ask' }))
    await screen.findByText('Try a question hook.')
    await user.type(screen.getByLabelText('Your question'), 'Another idea?')
    await user.click(screen.getByRole('button', { name: 'Ask' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Assistant unavailable.')
    expect(askAssistant).toHaveBeenLastCalledWith('Another idea?', [
      { role: 'user', text: 'What next?' },
      { role: 'assistant', text: 'Try a question hook.' },
    ])
  })

  it('explains that a report is needed before asking', () => {
    render(<AssistantPanel ready={false} />)
    expect(screen.getByText(/report needs to finish/i)).toBeInTheDocument()
    expect(screen.queryByLabelText('Your question')).not.toBeInTheDocument()
  })
})
