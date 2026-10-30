// The app: four tools as tabs on one page (no router, no new packages: decision D5).
//   Analyse a draft  v1 draft analysis (DraftTab, unchanged)
//   Creator / Reel / Niche Pulse  v2 reports (ReportTab -> POST /reports/{kind} -> useReport -> ReportView)
// The tab and any running job or report live in the address bar (?tab=creator&report=<id>),
// so a refresh or a shared link opens the same thing.
import { useState } from 'react'
import DraftTab from './DraftTab'
import ReportTab from './ReportTab'
import './App.css'

const TABS = [
  { id: 'draft', label: 'Analyse a draft' },
  { id: 'creator', label: 'Creator' },
  { id: 'reel', label: 'Reel' },
  { id: 'niche', label: 'Niche Pulse' },
]

function tabFromUrl() {
  const params = new URLSearchParams(window.location.search)
  if (params.get('job')) return 'draft' // v1 links (?job=<id>) keep working
  const tab = params.get('tab')
  return TABS.some((t) => t.id === tab) ? tab : 'draft'
}

export default function App() {
  const [tab, setTab] = useState(tabFromUrl)

  function choose(id) {
    if (id === tab) return
    // A new tab starts empty: drop the other tab's job or report from the address bar.
    const url = new URL(window.location.href)
    url.search = id === 'draft' ? '' : `?tab=${id}`
    window.history.replaceState({}, '', url)
    setTab(id)
  }

  // Keyboard: only the selected tab is a Tab stop; arrow keys move between tabs (WAI-ARIA tabs pattern).
  function onKeyDown(event) {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key]
    if (!step) return
    const i = (TABS.findIndex((t) => t.id === tab) + step + TABS.length) % TABS.length
    choose(TABS[i].id)
    document.getElementById(`tab-${TABS[i].id}`)?.focus()
  }

  return (
    <>
      <nav className="tabs" role="tablist" aria-label="ReelMind tools">
        <span className="tabs-brand">
          ReelMind <span className="accent">AI</span>
        </span>
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls="tool"
            tabIndex={tab === t.id ? 0 : -1}
            className={tab === t.id ? 'tab active' : 'tab'}
            onClick={() => choose(t.id)}
            onKeyDown={onKeyDown}
          >
            {t.label}
          </button>
        ))}
      </nav>
      <div id="tool" role="tabpanel" aria-labelledby={`tab-${tab}`}>
        {tab === 'draft' ? <DraftTab /> : <ReportTab key={tab} kind={tab} />}
      </div>
    </>
  )
}
