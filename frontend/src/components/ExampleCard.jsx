import { STATUS_WORDS, clockTime, dayMonth, short } from '../format'

// One outlier Reel with its receipts: link, when we read it, and the numbers behind the ratio.
// A number Instagram hides says "not shown publicly", never 0.
function Count({ value, label }) {
  return value == null ? (
    <span className="missing">{`${label} not shown publicly`}</span>
  ) : (
    <span>{`${short(value)} ${label}`}</span>
  )
}

export default function ExampleCard({ example: e }) {
  const citable = e.access_status === 'accessible'
  return (
    <article className={`example${citable ? '' : ' not-citable'}`}>
      <p className="example-head">
        <span className="tag">{e.id}</span>
        <strong>{`${e.outlier_ratio ?? '?'}x`}</strong>
        <span>{`@${e.handle}'s median`}</span>
        {!citable && <span className={`status status-${e.access_status}`}>{STATUS_WORDS[e.access_status]}</span>}
      </p>
      <p className="numbers">
        <Count value={e.views} label="views" />
        <span className="muted">{` vs ${e.creator_median_views == null ? '?' : short(e.creator_median_views)} median`}</span>
        <Count value={e.likes} label="likes" />
        <Count value={e.comments} label="comments" />
      </p>
      {e.hook_line && <p className="quote">{`“${e.hook_line}”`}</p>}
      <p className="muted small">
        {[e.audio_label && `Audio: ${e.audio_label}`, e.posted_date && `posted ${dayMonth(e.posted_date)}`]
          .filter(Boolean)
          .join(' · ')}
      </p>
      {!citable && e.status_reason && <p className="muted small">{`${e.status_reason}, so it isn't cited.`}</p>}
      <p className="receipt">
        <a href={e.source_url} target="_blank" rel="noopener noreferrer">{`Open @${e.handle}'s Reel on Instagram`}</a>
        <span className="muted small">{`retrieved ${clockTime(e.retrieved_at)}`}</span>
      </p>
    </article>
  )
}
