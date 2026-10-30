import { useRef, useState } from 'react'
import { REPORT_NOT_FOUND, refreshMyReport } from './api'
import AssistantPanel from './components/AssistantPanel'
import ReportView from './components/ReportView'
import { useReport } from './useReport'

export default function StudioPage({ user, onReportStarted, onUnauthorized }) {
  const [reportId, setReportId] = useState(user.latest_report_id)
  const [attempt, setAttempt] = useState(0)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState(null)
  const busy = useRef(false)
  const { report, error: pollError } = useReport(reportId, attempt)
  const running = report?.status === 'running' || report?.status === 'queued'

  async function refresh() {
    if (busy.current) return
    busy.current = true
    setSending(true)
    setError(null)
    try {
      const next = await refreshMyReport()
      setReportId(next.report_id)
      setAttempt((value) => value + 1)
      onReportStarted?.(next.report_id)
    } catch (err) {
      if (err?.status === 401) onUnauthorized?.()
      else setError(err.message || 'Could not start your report. Try again.')
    } finally {
      busy.current = false
      setSending(false)
    }
  }

  const visibleError = error || (pollError && pollError !== REPORT_NOT_FOUND ? pollError : null)

  return (
    <main className="studio-page page">
      <header className="studio-header">
        <div>
          <p className="muted">My Studio</p>
          <h1>{`@${user.ig_handle}`}</h1>
          <a href={user.profile_url} target="_blank" rel="noopener noreferrer">Open Instagram profile</a>
        </div>
        <button type="button" className="primary" onClick={refresh} disabled={sending || running}>
          {sending ? 'Starting…' : running ? 'Report is running…' : reportId ? 'Refresh my report' : 'Start my report'}
        </button>
      </header>
      {visibleError && <p role="alert" className="alert">{visibleError}</p>}
      {pollError === REPORT_NOT_FOUND && (
        <p role="alert" className="alert">We couldn't find your saved report. Start a fresh one to update your studio.</p>
      )}
      {report && <ReportView job={report} />}
      <AssistantPanel ready={report?.status === 'done' && report.kind === 'creator'} onUnauthorized={onUnauthorized} />
      {reportId && !report && !pollError && !error && <p className="intro" role="status">Opening your report…</p>}
      {!reportId && !error && (
        <p className="intro">Your Instagram profile is saved. Start a report to see your recent Reels and patterns here.</p>
      )}
    </main>
  )
}
