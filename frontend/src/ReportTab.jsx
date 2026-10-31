// Tabs 2-4: Creator, Reel and Niche Pulse. Same flow for all three:
// form -> startReport(kind, body) -> ?tab=<kind>&report=<id> in the address bar -> useReport polls
// GET /reports/{id} every 2 s -> ReportView fills in as events and results arrive.
import { useRef, useState } from 'react'
import { REPORT_NOT_FOUND, USE_MOCK, startReport } from './api'
import ReportView from './components/ReportView'
import { useReport } from './useReport'

// What each tab asks for and sends. Labels are what people (and tests) find the fields by.
const FORMS = {
  creator: {
    label: 'Instagram handle or profile link',
    placeholder: '@eylems_kitchen',
    button: 'Analyse creator',
    body: (text) => ({ handle_or_url: text }),
    intro: "Paste a creator's handle. ReelMind reads their public profile and recent Reels with TinyFish, highlights the last 7 days, and shows what works for them and what doesn't: hooks, captions, hashtags, keywords, audio and posting days, each finding linked to the Reels behind it.",
  },
  reel: {
    label: 'Instagram Reel link',
    placeholder: 'https://www.instagram.com/reel/…',
    button: 'Analyse Reel',
    body: (text) => ({ url: text }),
    intro: 'Paste a public Reel link. ReelMind reads the Reel, then its creator\'s recent Reels, and shows how this one compares with their usual: views against their median, hook, audio, hashtags, caption and posting day, plus what is worth borrowing.',
  },
  niche: {
    label: 'Keywords or hashtags (up to 3, comma-separated)',
    placeholder: 'cooking, #dal',
    button: 'Run Niche Pulse',
    body: (text) => ({ keywords: text.split(',').map((k) => k.trim()).filter(Boolean) }),
    intro: "Type up to 3 keywords or hashtags. ReelMind reads each topic's public page, finds Reels that beat their own creator's usual views by 2x or more today, and adds what the web is saying. Run it again tomorrow to see what changed.",
  },
}

const TITLES = {
  creator: { title: 'Understand a creator’s recent patterns.', label: 'Creator intelligence' },
  reel: { title: 'Put one Reel in context.', label: 'Single Reel comparison' },
  niche: { title: 'See what is moving in your niche.', label: 'Public examples, today' },
}

function setReportInUrl(kind, reportId) {
  const url = new URL(window.location.href)
  url.search = reportId ? `?tab=${kind}&report=${reportId}` : `?tab=${kind}`
  window.history.replaceState({}, '', url)
}

export default function ReportTab({ kind }) {
  const form = FORMS[kind]
  const [reportId, setReportId] = useState(() => new URLSearchParams(window.location.search).get('report'))
  const [attempt, setAttempt] = useState(0)
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [submitError, setSubmitError] = useState(null)
  const busy = useRef(false) // a double click must start one report, before React re-renders
  const { report, error: pollError } = useReport(reportId, attempt)

  const finished = report?.status === 'done' || report?.status === 'failed'
  const running = Boolean(reportId) && !finished && !pollError

  async function start(event) {
    event?.preventDefault()
    if (busy.current || !text.trim()) return
    busy.current = true
    setSending(true)
    setSubmitError(null)
    try {
      const { report_id: id } = await startReport(kind, form.body(text.trim()))
      setReportInUrl(kind, id)
      setAttempt(0)
      setReportId(id)
    } catch (err) {
      setSubmitError({ message: err.message, status: err.status })
    } finally {
      busy.current = false
      setSending(false)
    }
  }

  function reset() {
    setReportId(null)
    setReportInUrl(kind, null)
    setText('')
    setSubmitError(null)
  }

  let alert = null
  if (submitError) alert = { message: submitError.message, retry: submitError.status === 400 ? null : 'resend' }
  else if (pollError) alert = { message: pollError, retry: pollError === REPORT_NOT_FOUND ? null : 'poll' }
  else if (report?.status === 'failed') alert = { message: report.error || 'This report stopped before it finished.', retry: null }

  return (
    <main className="page report-page">
      <header className="report-head">
        <div className="page-heading report-heading">
          <p className="eyebrow">{TITLES[kind].label}</p>
          <h1>{TITLES[kind].title}</h1>
          <p>{form.intro}</p>
        </div>
        <form className="upload report-form" onSubmit={finished ? (e) => { e.preventDefault(); reset() } : start}>
          <div className="field grow">
            <label htmlFor={`${kind}-input`}>{form.label}</label>
            <input
              id={`${kind}-input`}
              type="text"
              value={text}
              placeholder={form.placeholder}
              onChange={(e) => setText(e.target.value)}
              disabled={running || sending}
              autoComplete="off"
            />
          </div>
          <button type="submit" className="primary" disabled={finished ? false : !text.trim() || sending || running}>
            {finished ? 'Start another' : form.button}
          </button>
        </form>
      </header>

      {alert && (
        <div className="alert" role="alert">
          <span>{alert.message}</span>
          {alert.retry && (
            <button type="button" onClick={alert.retry === 'resend' ? () => start() : () => setAttempt((a) => a + 1)}>
              Try again
            </button>
          )}
        </div>
      )}

      {!reportId && USE_MOCK && <p className="intro">Mock mode: shows a pretend report.</p>}
      {reportId && !report && !alert && <p className="intro">Starting…</p>}
      {report && <ReportView job={report} />}
    </main>
  )
}
