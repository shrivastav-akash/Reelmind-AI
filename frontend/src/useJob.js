import { getJob, NOT_FOUND } from './api'
import { usePolling } from './usePolling'

// Polls GET /jobs/{id} (v1 draft analysis) until the job is done or failed; see usePolling for
// the retry and error rules. Returns { job, error }.
export function useJob(jobId, attempt = 0) {
  const { data, error } = usePolling(getJob, jobId, attempt, NOT_FOUND)
  return { job: data, error }
}
