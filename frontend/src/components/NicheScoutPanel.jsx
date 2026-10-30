import { useEffect, useRef } from 'react'
import { STATUS_WORDS, short } from '../format'
import ExampleCard from './ExampleCard'

const PICKED_BY = {
  agent: (c) => (c.pick_reason ? `Agent's pick: ${c.pick_reason}` : "Agent's pick"),
  code: () => 'Picked by code: a smaller creator on the topic page',
  saved_list: () => 'From the saved list of creators for this topic',
}

function CreatorRow({ c }) {
  const word = c.access_status ? STATUS_WORDS[c.access_status] : 'Reading…'
  const facts = [
    c.followers != null && `${short(c.followers)} followers`,
    c.reels_read > 0 && `${c.reels_read} Reels read`,
    c.pinned_skipped > 0 && `${c.pinned_skipped} pinned left out`,
    c.median_views != null && `median ${short(c.median_views)} views`,
  ].filter(Boolean)
  return (
    <li className="creator">
      <p className="creator-head">
        <a href={c.reels_url} target="_blank" rel="noopener noreferrer">{`@${c.handle}`}</a>
        <span className={`status status-${c.access_status ?? 'pending'}`}>{word}</span>
      </p>
      <p className="small">{PICKED_BY[c.picked_by](c)}</p>
      {facts.length > 0 && <p className="muted small">{facts.join(' · ')}</p>}
      {c.status_reason && <p className="muted small">{c.status_reason}</p>}
    </li>
  )
}

// TinyFish at work: the live log, the Agent's live browser, each creator's status in words,
// and the outlier Reels as they are found.
export default function NicheScoutPanel({ job }) {
  const log = useRef(null)
  const running = job.status === 'running' || job.status === 'queued'

  useEffect(() => {
    // Newest line at the bottom stays in view (the log shows about 8 lines).
    if (log.current) log.current.scrollTop = log.current.scrollHeight
  }, [job.events.length])

  return (
    <section className="panel" aria-label="Niche Scout">
      <h2>
        Niche Scout <span className="by">· TinyFish</span>
      </h2>
      {job.stages.scout.status === 'failed' && <p className="status-line">{job.stages.scout.reason}</p>}

      {job.live_view_url && !job.replay && (
        <div className="live">
          <a href={job.live_view_url} target="_blank" rel="noopener noreferrer">
            Watch the agent live
          </a>
          {running && <iframe title="TinyFish Agent's live browser" src={job.live_view_url} />}
        </div>
      )}

      <ol className="log" aria-label="Research log" ref={log}>
        {job.events.map((ev, i) => (
          <li key={i} className={`log-${ev.kind}`}>
            <span className="t">{`${Math.round(ev.t)}s`}</span>
            <span>{ev.message}</span>
          </li>
        ))}
      </ol>

      {job.creators.length > 0 && (
        <>
          <h3>Creators</h3>
          <ul className="creators" aria-label="Creators">
            {job.creators.map((c) => (
              <CreatorRow key={c.handle} c={c} />
            ))}
          </ul>
        </>
      )}

      {job.examples.length > 0 && (
        <>
          <h3>Outlier Reels</h3>
          <div className="examples">
            {job.examples.map((e) => (
              <ExampleCard key={e.id} example={e} />
            ))}
          </div>
        </>
      )}
    </section>
  )
}
