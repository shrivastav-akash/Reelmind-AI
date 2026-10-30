import { getReport, REPORT_NOT_FOUND } from './api'
import { usePolling } from './usePolling'

// Polls GET /reports/{id} (v2 creator, Reel and Niche Pulse reports) until done or failed; see
// usePolling for the retry and error rules. Returns { report, error }.
export function useReport(reportId, attempt = 0) {
  const { data, error } = usePolling(getReport, reportId, attempt, REPORT_NOT_FOUND)
  return { report: data, error }
}
