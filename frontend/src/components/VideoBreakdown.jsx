import { seconds } from '../format'

// What code measured in the draft, plus the vision model's judgements marked "(estimated)".
export default function VideoBreakdown({ video, stage }) {
  // Measurements arrive before the vision step finishes: say it's still looking, not "not checked".
  const pending = stage?.status === 'running' ? 'Gemini is still looking at the frames…' : 'Not checked'
  return (
    <section className="panel" aria-label="Your video">
      <h2>Your video</h2>
      {!video ? (
        <p className="muted">
          {stage?.status === 'failed' ? stage.reason : 'Measuring cuts, speech and the opening frames…'}
        </p>
      ) : (
        <dl className="facts">
          <div>
            <dt>Length</dt>
            <dd>{`${seconds(video.duration_s)} · ${video.cut_times_s.length} cuts`}</dd>
          </div>
          <div>
            <dt>Cuts in the first 3 s</dt>
            <dd>{video.cuts_first_3s}</dd>
          </div>
          <div>
            <dt>First word</dt>
            <dd>
              {video.first_word_at_s != null
                ? `at ${seconds(video.first_word_at_s)}`
                : video.null_reasons.first_word_at_s ?? 'No speech'}
            </dd>
          </div>
          {video.words_first_3s && (
            <div>
              <dt>Said in the first 3 s</dt>
              <dd className="quote">{`“${video.words_first_3s}”`}</dd>
            </div>
          )}
          <div>
            <dt>On-screen text, first 3 s</dt>
            <dd>
              {video.text_overlay_first_3s
                ? `“${video.text_overlay_first_3s}” (estimated)`
                : video.null_reasons.text_overlay_first_3s ?? pending}
            </dd>
          </div>
          <div>
            <dt>Payoff</dt>
            <dd>
              {video.payoff_at_s != null ? (
                <>
                  <span className="big">{`~${seconds(video.payoff_at_s)} (estimated)`}</span>
                  {video.payoff_reason && <span className="muted small">{video.payoff_reason}</span>}
                </>
              ) : (
                video.null_reasons.payoff_at_s ?? pending
              )}
            </dd>
          </div>
          {video.opening_description && (
            <div>
              <dt>Opening</dt>
              <dd>{`${video.opening_description} (estimated)`}</dd>
            </div>
          )}
        </dl>
      )}
    </section>
  )
}
