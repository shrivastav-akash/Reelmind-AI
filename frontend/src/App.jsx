// Placeholder page so the data layer (api.js + useJob.js) can be checked before
// the real UI exists. Sujita replaces this on Friday with the layout in
// docs/ui-ux-brief.md (task S1 in docs/implementation-plan.md).
import { USE_MOCK } from './api'
import { useJob } from './useJob'

function App() {
  // In mock mode, start polling a pretend job straight away.
  const { job, error } = useJob(USE_MOCK ? 'mock' : null)

  const summary = job && {
    status: job.status,
    events: job.events.length,
    creators: job.creators.length,
    examples: job.examples.length,
    suggestions: job.recommendation?.suggestions.length ?? 0,
  }

  return (
    <main style={{ padding: 24, fontFamily: 'system-ui', textAlign: 'left' }}>
      <h1>ReelMind AI</h1>
      <p>The UI is built on Friday (task S1).</p>
      {!USE_MOCK && <p>Set VITE_USE_MOCK=1 in frontend/.env to see a mock job here.</p>}
      {error && <p role="alert">{error}</p>}
      {summary && <pre data-testid="job-summary">{JSON.stringify(summary, null, 2)}</pre>}
    </main>
  )
}

export default App
