// Tab 1, "Analyse a draft" (v1, unchanged apart from its name). Flow: UploadForm -> analyze() -> ?job=<id> in the address bar -> useJob polls
// GET /jobs/{id} every 2 s -> the three panels fill in as events and results arrive.
// A refresh (or a shared link) with ?job= resumes that job without uploading again.
import { useRef, useState } from 'react'
import { NOT_FOUND, USE_MOCK, analyze } from './api'
import NicheScoutPanel from './components/NicheScoutPanel'
import RecommendationCard from './components/RecommendationCard'
import ReplayBanner from './components/ReplayBanner'
import UploadForm from './components/UploadForm'
import VideoBreakdown from './components/VideoBreakdown'
import { useJob } from './useJob'
import './App.css'

function setJobInUrl(jobId) {
  const url = new URL(window.location.href)
  if (jobId) url.searchParams.set('job', jobId)
  else url.searchParams.delete('job')
  window.history.replaceState({}, '', url)
}

export default function DraftTab() {
  const [jobId, setJobId] = useState(() => new URLSearchParams(window.location.search).get('job'))
  const [attempt, setAttempt] = useState(0) // bumped by "Try again" to poll the same job afresh
  const [file, setFile] = useState(null)
  const [topic, setTopic] = useState('')
  const [formKey, setFormKey] = useState(0) // a new key gives a fresh, empty file input
  const [uploading, setUploading] = useState(false)
  const [submitError, setSubmitError] = useState(null)
  const sending = useRef(false) // a double click must send one upload, before React re-renders
  const { job, error: pollError } = useJob(jobId, attempt)

  const finished = job?.status === 'done' || job?.status === 'failed'
  const running = Boolean(jobId) && !finished && !pollError

  async function start() {
    if (sending.current || !file || !topic.trim()) return
    sending.current = true
    setUploading(true)
    setSubmitError(null)
    try {
      const { job_id: id } = await analyze(file, topic)
      setJobInUrl(id)
      setAttempt(0)
      setJobId(id)
    } catch (err) {
      setSubmitError({ message: err.message, status: err.status })
    } finally {
      sending.current = false
      setUploading(false)
    }
  }

  function reset() {
    setJobId(null)
    setJobInUrl(null)
    setAttempt(0)
    setFile(null)
    setTopic('')
    setFormKey((k) => k + 1)
    setSubmitError(null)
  }

  // One alert at a time, worded for the user, with "Try again" where trying again can help:
  // resend the upload, poll the same job again, or start over.
  let alert = null
  if (submitError) {
    alert = { message: submitError.message, retry: submitError.status === 400 ? null : 'resend' }
  } else if (pollError) {
    alert = { message: pollError, retry: pollError === NOT_FOUND ? null : 'poll' }
  } else if (job?.status === 'failed') {
    alert = { message: job.error || 'This analysis stopped before it finished.', retry: file && topic.trim() ? 'resend' : 'reset' }
  }

  function retry() {
    if (alert?.retry === 'resend') start()
    else if (alert?.retry === 'poll') setAttempt((a) => a + 1)
    else reset()
  }

  const rec = job?.recommendation
  const showCard = rec?.suggestions?.length > 0

  return (
    <main className="page draft-page">
      {job?.replay && <ReplayBanner recordedAt={job.replay_recorded_at} />}
      <header className="draft-heading">
        <div>
          <p className="eyebrow">Draft lab · Private upload</p>
          <h1>Find the moment that earns the next second.</h1>
          <p>Measure your opening, then compare it with public Reels in your niche. Your uploaded draft is analysed for this report; it is not published.</p>
        </div>
        <span className="privacy-mark">Your draft stays yours</span>
      </header>
      <section className="draft-intake" aria-label="Start a draft analysis">
        <UploadForm
          key={formKey}
          topic={topic}
          onFile={setFile}
          onTopic={setTopic}
          onSubmit={finished ? reset : start}
          buttonLabel={finished ? 'Analyse another' : 'Analyse'}
          disabled={finished ? false : !file || !topic.trim() || uploading || running}
        />
      </section>
      {!jobId && <div className="draft-process" aria-label="Analysis steps">
        <span>Measure your video</span><b aria-hidden="true">→</b><span>Find public examples</span><b aria-hidden="true">→</b><span>Build one experiment</span>
      </div>}

      {alert && (
        <div className="alert" role="alert">
          <span>{alert.message}</span>
          {alert.retry && (
            <button type="button" onClick={retry}>
              Try again
            </button>
          )}
        </div>
      )}

      {!jobId && USE_MOCK && <p className="intro">Mock mode: any file shows a pretend job.</p>}
      {jobId && !job && !alert && <p className="intro">Starting the analysis…</p>}

      {job && (
        <main className="panels">
          <VideoBreakdown video={job.video} stage={job.stages.video} />
          <NicheScoutPanel job={job} />
          {showCard ? (
            <RecommendationCard recommendation={rec} examples={job.examples} />
          ) : (
            <section className="panel" aria-label="Suggestion status">
              <h2>Suggestion</h2>
              <p className="muted">
                {rec?.source === 'insufficient_evidence'
                  ? "We couldn't reach enough public Reels in this niche to back a suggestion, so there's no card. The measurements and statuses here are still real."
                  : job.stages.recommend.status === 'skipped' || job.stages.recommend.status === 'failed'
                    ? `No suggestion: ${job.stages.recommend.reason}`
                    : job.stages.recommend.status === 'running'
                      ? 'Writing a suggestion. It is checked against your measurements and the examples before it shows.'
                      : 'Waiting for the video and the research to finish…'}
              </p>
            </section>
          )}
        </main>
      )}
    </main>
  )
}
