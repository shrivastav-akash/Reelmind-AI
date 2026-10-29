// useJob as a user experiences it: waiting, Wi-Fi blips, a dead server, old links,
// leaving the page. Fake timers stand in for the 2 s polling. IDs refer to docs/test-cases.md.
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { getJob } from './api'
import { useJob } from './useJob'

vi.mock('./api', async (importOriginal) => ({ ...(await importOriginal()), getJob: vi.fn() }))

const running = { id: 'j1', status: 'running' }
const done = { id: 'j1', status: 'done' }
const failed = { id: 'j1', status: 'failed', error: 'TinyFish key or credits problem' }

async function tick(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

beforeEach(() => {
  vi.useFakeTimers()
  getJob.mockReset()
})
afterEach(() => vi.useRealTimers())

it('does nothing until there is a job id', async () => {
  const { result } = renderHook(() => useJob(null))
  await tick(10_000)
  expect(getJob).not.toHaveBeenCalled()
  expect(result.current).toEqual({ job: null, error: null })
})

it('polls every 2 s and stops when the job is done (C2)', async () => {
  getJob.mockResolvedValueOnce(running).mockResolvedValueOnce(running).mockResolvedValue(done)
  const { result } = renderHook(() => useJob('j1'))
  await tick()
  expect(result.current.job.status).toBe('running')
  await tick(2000)
  expect(getJob).toHaveBeenCalledTimes(2)
  await tick(2000)
  expect(result.current.job.status).toBe('done')
  await tick(20_000)
  expect(getJob).toHaveBeenCalledTimes(3)
})

it('stops when the job failed, and shows it', async () => {
  getJob.mockResolvedValue(failed)
  const { result } = renderHook(() => useJob('j1'))
  await tick(10_000)
  expect(getJob).toHaveBeenCalledTimes(1)
  expect(result.current.job.error).toMatch(/credits/)
})

it('waits for a slow answer before asking again (C2)', async () => {
  let answer
  getJob.mockImplementationOnce(() => new Promise((resolve) => { answer = resolve })).mockResolvedValue(done)
  renderHook(() => useJob('j1'))
  await tick(9000)
  expect(getJob).toHaveBeenCalledTimes(1) // no pile-up while the server is slow
  await act(async () => answer(running))
  await tick(2000)
  expect(getJob).toHaveBeenCalledTimes(2)
})

it('forgives one failed poll (C3)', async () => {
  getJob.mockRejectedValueOnce(Object.assign(new Error('blip'), { status: 0 })).mockResolvedValue(done)
  const { result } = renderHook(() => useJob('j1'))
  await tick()
  expect(result.current.error).toBeNull()
  await tick(2000)
  expect(result.current).toEqual({ job: done, error: null })
})

it("after three failures in a row says the server can't be reached and stops (C4)", async () => {
  getJob.mockRejectedValue(Object.assign(new Error('down'), { status: 0 }))
  const { result } = renderHook(() => useJob('j1'))
  await tick(4100)
  expect(result.current.error).toBe("Can't reach the server. Is the backend running?")
  await tick(20_000)
  expect(getJob).toHaveBeenCalledTimes(3)
})

it('keeps showing the last good job while the server is down', async () => {
  getJob.mockResolvedValueOnce(running).mockRejectedValue(Object.assign(new Error('down'), { status: 0 }))
  const { result } = renderHook(() => useJob('j1'))
  await tick(6100)
  expect(result.current.job).toEqual(running)
  expect(result.current.error).toMatch(/Can't reach/)
})

it("stops at once for an unknown job and says so (C6)", async () => {
  getJob.mockRejectedValue(Object.assign(new Error('Not Found'), { status: 404 }))
  const { result } = renderHook(() => useJob('old-link'))
  await tick(10_000)
  expect(getJob).toHaveBeenCalledTimes(1)
  expect(result.current).toEqual({ job: null, error: "We couldn't find that analysis." })
})

it('stops polling when the user leaves the page (C9)', async () => {
  getJob.mockResolvedValue(running)
  const { unmount } = renderHook(() => useJob('j1'))
  await tick()
  unmount()
  await tick(20_000)
  expect(getJob).toHaveBeenCalledTimes(1)
})

it('never shows the previous job after starting a new one (C7)', async () => {
  getJob.mockImplementation((id) => Promise.resolve({ id, status: 'done' }))
  const { result, rerender } = renderHook(({ id }) => useJob(id), { initialProps: { id: 'first' } })
  await tick()
  expect(result.current.job.id).toBe('first')
  rerender({ id: 'second' })
  expect(result.current.job).toBeNull() // not the old job, even for one render
  await tick()
  expect(result.current.job.id).toBe('second')
})

it('"Try again" after giving up polls the same job afresh (C4)', async () => {
  getJob.mockRejectedValue(Object.assign(new Error('down'), { status: 0 }))
  const { result, rerender } = renderHook(({ attempt }) => useJob('j1', attempt), { initialProps: { attempt: 0 } })
  await tick(4100)
  expect(result.current.error).toMatch(/Can't reach/)
  getJob.mockResolvedValue(done)
  rerender({ attempt: 1 })
  expect(result.current.error).toBeNull() // the old error goes away at once
  await tick()
  expect(result.current).toEqual({ job: done, error: null })
})
