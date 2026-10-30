// The app: four tools as tabs on one page (no router, no new packages: decision D5).
//   Analyse a draft  v1 draft analysis (DraftTab, unchanged)
//   Creator / Reel / Niche Pulse  v2 reports (ReportTab -> POST /reports/{kind} -> useReport -> ReportView)
// The tab and any running job or report live in the address bar (?tab=creator&report=<id>),
// so a refresh or a shared link opens the same thing.
import { useEffect, useState } from 'react'
import DraftTab from './DraftTab'
import ReportTab from './ReportTab'
import AuthPage from './AuthPage'
import StudioPage from './StudioPage'
import HomePage from './HomePage'
import { clearSession, getMe, hasSession, signOut } from './api'
import './App.css'

const TABS = [
  { id: 'draft', label: 'Analyse a draft' },
  { id: 'creator', label: 'Creator' },
  { id: 'reel', label: 'Reel' },
  { id: 'niche', label: 'Niche Pulse' },
]

function tabFromUrl() {
  const params = new URLSearchParams(window.location.search)
  if (params.get('job') || params.has('mock')) return 'draft' // v1 and mock links keep working
  const tab = params.get('tab')
  if (tab === 'login' || tab === 'studio') return tab
  return TABS.some((t) => t.id === tab) ? tab : (tab ? 'draft' : 'home')
}

export default function App() {
  const [tab, setTab] = useState(tabFromUrl)
  const [user, setUser] = useState(null)
  const [authLoading, setAuthLoading] = useState(hasSession)
  const [authError, setAuthError] = useState(null)
  const selectedTool = TABS.some((item) => item.id === tab) ? tab : (tab === 'home' ? null : 'draft')

  useEffect(() => {
    if (!hasSession()) return undefined
    let active = true
    getMe().then((current) => {
      if (active) setUser(current)
    }).catch((err) => {
      if (!active) return
      if (err?.status === 401) clearSession()
      else setAuthError(err.message)
    }).finally(() => {
      if (active) setAuthLoading(false)
    })
    return () => { active = false }
  }, [])

  function navigate(id) {
    const url = new URL(window.location.href)
    url.search = id === 'home' || id === 'draft' ? '' : `?tab=${id}`
    window.history.replaceState({}, '', url)
    setTab(id)
  }

  function choose(id) {
    if (id === tab) return
    if (id === 'studio' && !user) return navigate('login')
    navigate(id)
  }

  async function logout() {
    await signOut().catch((err) => setAuthError(err.message))
    setUser(null)
    navigate('draft')
  }

  // Keyboard: only the selected tab is a Tab stop; arrow keys move between tabs (WAI-ARIA tabs pattern).
  function onKeyDown(event) {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key]
    if (!step) return
    const i = (TABS.findIndex((t) => t.id === selectedTool) + step + TABS.length) % TABS.length
    choose(TABS[i].id)
    document.getElementById(`tab-${TABS[i].id}`)?.focus()
  }

  return (
    <>
      <nav className={tab === 'home' ? 'tabs home-nav' : 'tabs'} role={tab === 'home' ? undefined : 'tablist'} aria-label={tab === 'home' ? undefined : 'ReelMind tools'}>
        <button type="button" className="tabs-brand" aria-label="ReelMind AI home" onClick={() => navigate('home')}>
          ReelMind <span className="accent">AI</span>
        </button>
        {tab !== 'home' && TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={selectedTool === t.id}
            aria-controls="tool"
            tabIndex={selectedTool === t.id ? 0 : -1}
            className={selectedTool === t.id ? 'tab active' : 'tab'}
            onClick={() => choose(t.id)}
            onKeyDown={onKeyDown}
          >
            {t.label}
          </button>
        ))}
        <div className="account-actions">
          {user ? (
            <>
              <button type="button" onClick={() => choose('studio')}>My Studio</button>
              <button type="button" onClick={logout}>Log out</button>
            </>
          ) : authLoading ? (
            <span className="muted small" role="status">Checking account…</span>
          ) : (
            <button type="button" onClick={() => choose('login')}>Sign up / Log in</button>
          )}
        </div>
      </nav>
      {tab === 'login' ? (
        <AuthPage initialError={authError} onAuthenticated={(sessionUser) => {
          setUser(sessionUser)
          setAuthError(null)
          navigate('studio')
        }} />
      ) : tab === 'studio' ? (
        user ? (
          <StudioPage key={user.id} user={user} onUnauthorized={() => { clearSession(); setUser(null); navigate('login') }}
            onReportStarted={(id) => setUser((current) => current ? { ...current, latest_report_id: id } : current)} />
        ) : authLoading ? (
          <main className="page"><p role="status">Checking your account…</p></main>
        ) : (
          <AuthPage initialError={authError} onAuthenticated={(sessionUser) => { setUser(sessionUser); navigate('studio') }} />
        )
      ) : (
        <div id="tool" role={tab === 'home' ? undefined : 'tabpanel'} aria-labelledby={tab === 'home' ? undefined : `tab-${tab}`}>
          {tab === 'home' ? <HomePage signedIn={Boolean(user)} onNavigate={choose} /> : tab === 'draft' ? <DraftTab /> : <ReportTab key={tab} kind={tab} />}
        </div>
      )}
    </>
  )
}
