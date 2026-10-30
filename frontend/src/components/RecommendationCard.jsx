import ExampleCard from './ExampleCard'

const SOURCE = {
  llm: 'Written by Gemini and checked against the measurements and examples.',
  llm_retry: 'Written by Gemini on its second try, then checked against the measurements and examples.',
  template: "Gemini's answers didn't pass the checks, so this is a rule-based suggestion from your measurements.",
}

// The experiment card. Rendered only when at least one suggestion passed the grounding checks.
export default function RecommendationCard({ recommendation, examples }) {
  const byId = Object.fromEntries(examples.map((e) => [e.id, e]))
  return (
    <section className="panel recommendation" aria-label="Recommendation">
      <h2>Recommendation</h2>
      <p className="muted small">{SOURCE[recommendation.source]}</p>
      {recommendation.suggestions.map((s, i) => (
        <article key={i} className="suggestion">
          <h3>Observed</h3>
          <p>{s.observation}</p>
          <h3>Evidence</h3>
          <p>{s.evidence_summary}</p>
          {s.evidence_ids.map((id) => byId[id] && <ExampleCard key={id} example={byId[id]} />)}
          <h3>Hypothesis</h3>
          <p>{s.hypothesis}</p>
          <h3>Experiment</h3>
          <dl className="experiment">
            <div>
              <dt>Cut A</dt>
              <dd>{s.experiment.cut_a}</dd>
            </div>
            <div>
              <dt>Cut B</dt>
              <dd>{s.experiment.cut_b}</dd>
            </div>
            <div>
              <dt>Compare</dt>
              <dd>{s.experiment.measure}</dd>
            </div>
          </dl>
        </article>
      ))}
    </section>
  )
}
