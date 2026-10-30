const TOOLS = [
  { id: 'draft', title: 'Analyse a draft', description: 'Measure your opening, then compare it with public Reels in your niche.', action: 'Analyse a draft' },
  { id: 'creator', title: 'Creator report', description: 'See patterns across recent posts and compare them with the creator’s own baseline.', action: 'View a creator' },
  { id: 'reel', title: 'Reel comparison', description: 'Put one public Reel beside its creator’s recent results and examples.', action: 'Compare a Reel' },
  { id: 'niche', title: 'Niche Pulse', description: 'Explore today’s outliers, shared patterns and changes since the last run.', action: 'Explore a niche' },
]

function SignalIllustration() {
  return (
    <div className="home-visual" aria-hidden="true">
      <div className="signal-board">
        <div className="signal-sheet back">
          <div className="signal-sheet-label"><span>CREATOR BASELINE</span><span>RECENT</span></div>
          <div className="signal-lines"><i /><i /><i /></div>
          <div className="signal-strip"><i /><i /><i /><i /><i /><i /><i /></div>
        </div>
        <div className="signal-sheet main">
          <div className="signal-sheet-label"><span>VISIBLE EVIDENCE</span><span>↗</span></div>
          <div className="signal-lines"><i /><i /><i /></div>
          <div className="signal-strip"><i /><i /><i /><i /><i /><i /><i /></div>
        </div>
        <div className="signal-sheet front">
          <div className="signal-sheet-label"><span>YOUR NEXT TEST</span><span>↗</span></div>
          <div className="signal-lines"><i /><i /><i /></div>
        </div>
        <div className="signal-tag">A clear reason to test</div>
      </div>
    </div>
  )
}

export default function HomePage({ signedIn, onNavigate }) {
  return (
    <main className="home-page">
      <section className="home-hero" aria-labelledby="home-heading">
        <div className="home-copy">
          <p className="home-kicker">A clearer way to plan your next Reel</p>
          <h1 id="home-heading">Make your next Reel decision with evidence.</h1>
          <p className="home-intro">
            Understand what is working across your own posts and public niche examples. Every report keeps its claims tied to visible numbers and source Reels.
          </p>
          <div className="home-actions">
            <button type="button" className="home-primary" onClick={() => onNavigate('draft')}>
              Analyse a draft <span aria-hidden="true">↗</span>
            </button>
            <button type="button" className="home-secondary" onClick={() => onNavigate('niche')}>
              Explore a niche
            </button>
          </div>
          <div className="home-proof"><span>Public sources only</span><span>Every claim has receipts</span></div>
        </div>
        <SignalIllustration />
      </section>

      <section className="home-tools" aria-labelledby="tools-heading">
        <div className="home-section-heading">
          <div><h2 id="tools-heading">Start with a question</h2><p>Choose the kind of evidence you need.</p></div>
          <span className="muted small">Four ways into the same workspace</span>
        </div>
        <div className="tool-cards">
          {TOOLS.map((tool, index) => (
            <article className="tool-card" key={tool.id}>
              <p className="tool-number">0{index + 1}</p>
              <h3>{tool.title}</h3>
              <p>{tool.description}</p>
              <button type="button" className="text-action" onClick={() => onNavigate(tool.id)}>
                {tool.action}<span aria-hidden="true"> →</span>
              </button>
            </article>
          ))}
        </div>
      </section>

      {!signedIn && (
        <section className="home-account" aria-label="Create an account">
          <div>
            <h2>Keep your creator report in one place.</h2>
            <p>Create an account to save your report, refresh it, and ask questions about its evidence.</p>
          </div>
          <button type="button" onClick={() => onNavigate('login')}>Sign up</button>
        </section>
      )}
    </main>
  )
}
