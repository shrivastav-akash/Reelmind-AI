// One v2 report on screen (backend/report_models.py ReportJob). The same pieces serve all three kinds:
//   creator  Progress, Profile, Insights, Recent Reels, Patterns
//   reel     Progress, This Reel + comparison, Insights, then the creator's Profile / Reels / Patterns
//   niche    Progress, Pulse summary, Insights, Outliers, Patterns, On the web
// Every insight links to the Reels it cites (#reel-<id>), and every missing number says why.
import { STATUS_WORDS, clockTime, dayMonth, short } from '../format'
import ReplayBanner from './ReplayBanner'

const STAGE_WORDS = { pending: 'Waiting', running: 'Running…', done: 'Done', failed: 'Failed', skipped: 'Skipped' }
const STAGE_NAMES = {
  fetch: 'Read profile + Reels', analyse: 'Numbers + patterns', visuals: 'Covers', insights: 'Insights',
  reel: 'Read the Reel', creator: "Creator's baseline", research: 'Topic pages + web', patterns: 'Patterns',
}
const SOURCE_WORDS = {
  llm: 'Written by Gemini from these numbers; every claim was checked against them before showing.',
  llm_retry: 'Written by Gemini (second try) from these numbers; every claim was checked against them.',
  template: "Rule-based: Gemini's answer didn't pass the checks or Gemini was unavailable.",
  insufficient_evidence: 'Not enough readable Reels to back an insight, so only the numbers are shown.',
}
const KINDS = [
  { id: 'working', title: 'Working' },
  { id: 'not_working', title: 'Not working' },
  { id: 'try_next', title: 'Try next' },
]
const DIMENSIONS = {
  hook_type: 'Hook type', audio: 'Audio', caption_length: 'Caption length', hashtag: 'Hashtags',
  keyword: 'Keywords', weekday: 'Posting day', cover_text: 'Cover',
}
const HOOKS = {
  question: 'Question', number_list: 'Numbered list', pov: 'POV', how_to: 'How-to', warning: 'Warning',
  story: 'Story', statement: 'Statement', none: 'Hashtags only',
}

function Ratio({ value }) {
  if (value == null) return <span className="muted">–</span>
  const tone = value >= 2 ? 'ratio-high' : value >= 1 ? 'ratio-up' : 'ratio-down'
  return <span className={`ratio ${tone}`}>{`${value}x`}</span>
}

function Missing({ why }) {
  return <span className="missing" title={why || 'Not shown on the public page'}>not shown publicly</span>
}

function Progress({ job }) {
  const running = job.status === 'running' || job.status === 'queued'
  return (
    <section className="panel" aria-label="Progress">
      <h2>{running ? 'Working on it…' : 'How this report was made'}</h2>
      <ol className="stages">
        {Object.entries(job.stages).map(([name, s]) => (
          <li key={name} className={`stage stage-${s.status}`}>
            <strong>{STAGE_NAMES[name] ?? name}</strong>
            <span className={`status status-${s.status}`}>{STAGE_WORDS[s.status]}</span>
            {s.reason && <span className="muted small">{s.reason}</span>}
          </li>
        ))}
      </ol>
      <ol className="log" aria-label="Live log">
        {job.events.map((e, i) => (
          <li key={i} className={`log-${e.kind}`}>
            <span className="t">{`${Math.round(e.t)} s`}</span> {e.message}
          </li>
        ))}
      </ol>
    </section>
  )
}

function Profile({ creator }) {
  const p = creator.profile
  const facts = [
    ['Followers', p.followers != null ? short(p.followers) : null],
    ['Posts', p.posts != null ? short(p.posts) : null],
    [`Reels in the last ${p.window_days} days`, p.reels_in_window],
    ['Median views', p.median_views != null ? short(p.median_views) : null],
    ['Posts per week', p.posts_per_week],
    ['Median engagement', p.median_engagement != null ? `${(p.median_engagement * 100).toFixed(1)}%` : null],
  ]
  const limits = Object.values(creator.null_reasons ?? {})
  return (
    <section className="panel" aria-label="Creator profile">
      <h2>
        <a href={p.profile_url} target="_blank" rel="noopener noreferrer">{`@${p.handle}`}</a>
        {p.access_status !== 'accessible' && (
          <span className={`status status-${p.access_status}`}>{STATUS_WORDS[p.access_status]}</span>
        )}
      </h2>
      {p.status_reason && <p className="muted">{p.status_reason}</p>}
      <dl className="facts-grid">
        {facts.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value ?? <Missing />}</dd>
          </div>
        ))}
      </dl>
      {p.window_note && <p className="note">{p.window_note}</p>}
      {limits.length > 0 && (
        <p className="muted small">{`What public pages can't show: ${limits.join('; ')}.`}</p>
      )}
    </section>
  )
}

function Insights({ insights, source, stage }) {
  return (
    <section className="panel insights" aria-label="Insights">
      <h2>Insights</h2>
      {insights.length === 0 && (
        <p className="muted">
          {stage && stage.status !== 'done' ? stage.reason || 'Waiting for the numbers…' : SOURCE_WORDS[source]}
        </p>
      )}
      <div className="insight-groups">
        {KINDS.map(({ id, title }) => {
          const group = insights.filter((i) => i.kind === id)
          if (!group.length) return null
          return (
            <div key={id} className={`insight-group insight-${id}`}>
              <h3>{title}</h3>
              <ul>
                {group.map((i, n) => (
                  <li key={n}>
                    <p>{i.claim}</p>
                    <p className="small">
                      {'Reels: '}
                      {i.reel_ids.map((rid) => (
                        <a key={rid} className="chip" href={`#reel-${rid}`}>{rid}</a>
                      ))}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </div>
      {insights.length > 0 && <p className="muted small">{SOURCE_WORDS[source]}</p>}
    </section>
  )
}

function ReelRows({ reels, label, showCreator = false }) {
  return (
    <section className="panel wide" aria-label={label}>
      <h2>{label}</h2>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Reel</th>
              {showCreator && <th>Creator</th>}
              <th>Posted</th>
              <th>Hook</th>
              <th>Views</th>
              <th>vs median</th>
              <th>Audio</th>
              <th>Hashtags</th>
            </tr>
          </thead>
          <tbody>
            {reels.map((r) => (
              <tr key={r.id} id={`reel-${r.id}`} className={r.in_window ? 'in-window' : undefined}>
                <td>
                  <a href={r.source_url} target="_blank" rel="noopener noreferrer"
                     aria-label={`Open Reel ${r.id} on Instagram`}>{r.id}</a>
                  {r.access_status !== 'accessible' && (
                    <span className={`status status-${r.access_status}`}>{STATUS_WORDS[r.access_status]}</span>
                  )}
                </td>
                {showCreator && <td>{r.handle ? `@${r.handle}` : ''}{r.topic && <span className="muted small">{` #${r.topic}`}</span>}</td>}
                <td>
                  {r.posted_date ? dayMonth(r.posted_date) : <Missing why={r.null_reasons?.posted_date} />}
                  {r.in_window && <span className="tag">7 days</span>}
                </td>
                <td className="hook">
                  {r.hook_line ?? <Missing why={r.null_reasons?.hook_line} />}
                  {r.hook_type && <span className="muted small">{` · ${HOOKS[r.hook_type] ?? r.hook_type}`}</span>}
                </td>
                <td>{r.views != null ? short(r.views) : <Missing why={r.null_reasons?.views} />}</td>
                <td><Ratio value={r.ratio_vs_median} /></td>
                <td className="small">{r.audio_label ?? <Missing why={r.null_reasons?.audio_label} />}</td>
                <td className="small">{r.hashtags?.join(' ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function CoverStrip({ reels }) {
  const covers = reels.filter((r) => r.cover_url || r.cover_notes)
  if (!covers.length) return null
  return (
    <section className="panel wide" aria-label="Cover visuals">
      <h2>Cover visuals <span className="muted small">Estimated from public cover images</span></h2>
      <ul className="cover-strip">
        {covers.map((r) => (
          <li key={r.id}>
            {r.cover_url ? (
              <a href={r.source_url} target="_blank" rel="noopener noreferrer" aria-label={`Open cover for ${r.id} on Instagram`}>
                <img src={r.cover_url} alt={`Cover image for ${r.id}`} loading="lazy" />
              </a>
            ) : <div className="cover-placeholder">Cover unavailable</div>}
            <strong>{r.id}</strong>
            {r.cover_notes ? (
              <p className="small">
                {r.cover_notes.text_on_cover && <span className="cover-quote">“{r.cover_notes.text_on_cover}”</span>}
                <span>{`${r.cover_notes.face === true ? 'Face visible' : r.cover_notes.face === false ? 'No face seen' : 'Face unclear'} · ${r.cover_notes.setting} · ${r.cover_notes.style}`}</span>
              </p>
            ) : (
              <p className="muted small">{r.null_reasons?.cover_notes || r.null_reasons?.cover_url || 'Visual notes unavailable'}</p>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

function Patterns({ patterns }) {
  if (!patterns?.length) return null
  const groups = Object.keys(DIMENSIONS)
    .map((d) => [d, patterns.filter((p) => p.dimension === d).slice(0, 6)])
    .filter(([, rows]) => rows.length)
  return (
    <section className="panel wide" aria-label="Patterns">
      <h2>Patterns</h2>
      <p className="muted small">
        Each row: the median views of the Reels that share it, divided by the usual (1x = typical), and how many sit in
        the top and bottom third.
      </p>
      <div className="pattern-grid">
        {groups.map(([d, rows]) => (
          <div key={d}>
            <h3>{DIMENSIONS[d]}</h3>
            <ul className="patterns">
              {rows.map((p) => (
                <li key={p.value}>
                  <span>{d === 'hook_type' ? HOOKS[p.value] ?? p.value : p.value}</span>
                  <Ratio value={p.median_ratio} />
                  <span className="muted small">{`${p.reel_ids.length} Reel${p.reel_ids.length === 1 ? '' : 's'} · ${p.in_top} top / ${p.in_bottom} bottom`}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  )
}

function ThisReel({ report }) {
  const r = report.reel
  const handle = report.creator.profile.handle
  return (
    <section className="panel" aria-label="This Reel">
      <h2>This Reel</h2>
      <p className="big" id="reel-r0">{r.hook_line ?? <Missing why={r.null_reasons?.hook_line} />}</p>
      <p className="muted">
        {`@${handle} · `}
        {r.posted_date ? dayMonth(r.posted_date) : 'date not shown'}
        {' · '}
        <a href={r.source_url} target="_blank" rel="noopener noreferrer">Open on Instagram</a>
      </p>
      <p>
        {r.views != null ? `${short(r.views)} views ` : <Missing why={r.null_reasons?.views} />}
        {r.ratio_vs_median != null && <Ratio value={r.ratio_vs_median} />}
      </p>
      <table aria-label={`Compared with @${handle}'s usual`}>
        <thead>
          <tr><th /><th>This Reel</th><th>{`@${handle}'s usual`}</th></tr>
        </thead>
        <tbody>
          {report.comparison.map((c) => (
            <tr key={c.label}>
              <th scope="row">{c.label}</th>
              <td>{c.this_reel ?? '–'}</td>
              <td>
                {c.creator_usual ?? '–'}
                {c.note && <span className="muted small">{` (${c.note})`}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

function PulseSummary({ pulse }) {
  return (
    <section className="panel" aria-label="Niche Pulse">
      <h2>{pulse.keywords.map((k) => `#${k}`).join('  ')}</h2>
      <p>{`${pulse.reels.length} Reels beat their own creator's usual views by 2x or more, from ${pulse.creators_read} creators (${dayMonth(pulse.run_date)}).`}</p>
      {pulse.null_reasons?.reels && <p className="muted">{pulse.null_reasons.reels}</p>}
      <h3>Since the last run</h3>
      {pulse.previous_run_date ? (
        pulse.since_last_run.length ? (
          <ul>{pulse.since_last_run.map((s) => <li key={s}>{s}</li>)}</ul>
        ) : (
          <p className="muted">{`No changes since ${dayMonth(pulse.previous_run_date)}.`}</p>
        )
      ) : (
        <p className="muted">First run for these keywords: run it again tomorrow to see what changed.</p>
      )}
    </section>
  )
}

function Web({ signals }) {
  if (!signals?.length) return null
  return (
    <section className="panel" aria-label="On the web">
      <h2>On the web</h2>
      <ul className="web">
        {signals.map((w) => (
          <li key={w.url}>
            <a href={w.url} target="_blank" rel="noopener noreferrer">{w.title}</a>
            {w.snippet && <p className="muted small">{w.snippet}</p>}
            <p className="muted small">{`retrieved ${clockTime(w.retrieved_at)}`}</p>
          </li>
        ))}
      </ul>
    </section>
  )
}

export default function ReportView({ job }) {
  const r = job.result
  return (
    <>
      {job.replay && <ReplayBanner recordedAt={job.replay_recorded_at} />}
      <main className="report">
        <div className="report-side">
          <Progress job={job} />
          {r?.kind === 'creator' && <Profile creator={r} />}
          {r?.kind === 'reel' && <ThisReel report={r} />}
          {r?.kind === 'niche' && <PulseSummary pulse={r} />}
        </div>
        <div className="report-main">
          {r && <Insights insights={r.insights} source={r.insights_source} stage={job.stages.insights} />}
          {r?.kind === 'creator' && (
            <>
              <ReelRows reels={r.reels} label="Recent Reels" />
              <CoverStrip reels={r.reels} />
              <Patterns patterns={r.patterns} />
            </>
          )}
          {r?.kind === 'reel' && (
            <>
              <Profile creator={r.creator} />
              <ReelRows reels={r.creator.reels} label={`@${r.creator.profile.handle}'s recent Reels`} />
              <CoverStrip reels={[r.reel, ...r.creator.reels]} />
              <Patterns patterns={r.creator.patterns} />
            </>
          )}
          {r?.kind === 'niche' && (
            <>
              <ReelRows reels={r.reels} label="Outliers today" showCreator />
              <Patterns patterns={r.patterns} />
              <Web signals={r.web} />
            </>
          )}
        </div>
      </main>
    </>
  )
}
