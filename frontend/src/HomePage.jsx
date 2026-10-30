const TOOLS = [
  {
    id: 'draft',
    title: 'Analyse a draft',
    description: 'Measure the opening of your unposted video, then compare it with public Reels in your niche.',
    action: 'Analyse a draft',
  },
  {
    id: 'creator',
    title: 'Creator report',
    description: 'See how recent posts perform against your own baseline, with patterns and cover notes.',
    action: 'View a creator',
  },
  {
    id: 'reel',
    title: 'Reel comparison',
    description: 'Compare one public Reel with its creator’s recent results and inspect the supporting examples.',
    action: 'Compare a Reel',
  },
  {
    id: 'niche',
    title: 'Niche Pulse',
    description: 'Explore today’s outliers across up to three topics, then see patterns and what changed since the last run.',
    action: 'Explore a niche',
  },
]

export default function HomePage({ signedIn, onNavigate }) {
  return (
    <main className="home-page">
      <section className="home-hero" aria-labelledby="home-heading">
        <p className="eyebrow">REELMIND AI</p>
        <h1 id="home-heading">Make your next Reel decision with evidence.</h1>
        <p className="home-intro">
          Understand what is working across your own posts and public niche examples. Every report keeps its claims tied to visible numbers and source Reels.
        </p>
        <button type="button" className="home-primary" onClick={() => onNavigate('draft')}>
          Analyse a draft
        </button>
      </section>

      <section className="home-tools" aria-labelledby="tools-heading">
        <div className="home-section-heading">
          <h2 id="tools-heading">Choose a tool</h2>
          <p>Start with the question you want to answer.</p>
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
