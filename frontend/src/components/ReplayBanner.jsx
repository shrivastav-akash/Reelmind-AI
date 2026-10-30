import { clockTime } from '../format'

// Shown whenever job.replay is true and can't be dismissed: a replay must never pass for live.
export default function ReplayBanner({ recordedAt }) {
  return (
    <div className="replay-banner" role="status">
      {`Replay of a recorded run, ${recordedAt ? clockTime(recordedAt) : 'time unknown'}. Nothing on this page is live.`}
    </div>
  )
}
