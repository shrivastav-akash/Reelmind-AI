import { useEffect, useState } from 'react'
import DraftTab from './DraftTab'
import ReportTab from './ReportTab'
import AuthPage from './AuthPage'
import StudioPage from './StudioPage'
import HomePage from './HomePage'
import { clearSession, getMe, hasSession, signOut } from './api'
import './App.css'

const TABS = [
  { id: 'draft', label: 'Analyse a draft', symbol: '✳', detail: 'Your next Reel' },
  { id: 'creator', label: 'Creator', symbol: '◉', detail: 'A profile over time' },
  { id: 'reel', label: 'Reel', symbol: '▷', detail: 'One post, in context' },
  { id: 'niche', label: 'Niche Pulse', symbol: '⌁', detail: 'What is moving now' },
]

const PAGE_NAMES = {
  home: 'Overview', draft: 'Draft lab', creator: 'Creator report', reel: 'Reel comparison',
  niche: 'Niche Pulse', login: 'Account', studio: 'My Studio',
}

function tabFromUrl() {
  const params = new URLSearchParams(window.location.search)
  if (params.get('job') || params.has('mock')) return 'draft'
  const tab = params.get('tab')
  if (tab === 'login' || tab === 'studio') return tab
  return TABS.some((item) => item.id === tab) ? tab : (tab ? 'draft' : 'home')
}

function Brand({ onClick }) {
  return (
    <button type="button" className="brand-lockup" aria-label="ReelMind AI home" onClick={onClick}>
      <span className="brand-symbol" aria-hidden="true"><i /><i /><i /></span>
      <span className="brand-word">reelmind<span>.ai</span></span>
    </button>
  )
}

export default function App() {
  const [tab, setTab] = useState(tabFromUrl)
  const [user, setUser] = useState(null)
  const [authLoading, setAuthLoading] = useState(hasSession)
  const [authError, setAuthError] = useState(null)
  const selectedTool = TABS.some((item) => item.id === tab) ? tab : null

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

  function onKeyDown(event) {
    const step = { ArrowDown: 1, ArrowUp: -1, ArrowRight: 1, ArrowLeft: -1 }[event.key]
    if (!step) return
    event.preventDefault()
    const index = TABS.findIndex((item) => item.id === selectedTool)
    const next = (index + step + TABS.length) % TABS.length
    choose(TABS[next].id)
    document.getElementById(`tab-${TABS[next].id}`)?.focus()
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Brand onClick={() => navigate('home')} />
        <p className="sidebar-label">Your workspace</p>
        <nav className="tool-nav" role="tablist" aria-label="ReelMind tools" aria-orientation="vertical">
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              id={`tab-${item.id}`}
              aria-selected={selectedTool === item.id}
              aria-controls="tool"
              aria-label={item.label}
              tabIndex={selectedTool === item.id || (!selectedTool && item.id === 'draft') ? 0 : -1}
              className={selectedTool === item.id ? 'tool-link active' : 'tool-link'}
              onClick={() => choose(item.id)}
              onKeyDown={onKeyDown}
            >
              <span className={`tool-symbol tool-${item.id}`} aria-hidden="true">{item.symbol}</span>
              <span className="tool-copy"><strong>{item.label}</strong><small>{item.detail}</small></span>
              {selectedTool === item.id && <span className="tool-current" aria-hidden="true" />}
            </button>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className="evidence-note">
            <span className="evidence-icon" aria-hidden="true">✳</span>
            <div><strong>Evidence, first.</strong><p>Every insight points to a source.</p></div>
          </div>
          <div className="account-actions">
            {user ? (
              <>
                <button type="button" aria-label="My Studio" className={tab === 'studio' ? 'account-link active' : 'account-link'} onClick={() => choose('studio')}>
                  <span className="account-avatar" aria-hidden="true">{user.ig_handle?.slice(0, 1)?.toUpperCase() || 'M'}</span>
                  <span className="account-copy"><strong>My Studio</strong><small>{`@${user.ig_handle}`}</small></span>
                </button>
                <button type="button" className="logout-link" onClick={logout}>Log out</button>
              </>
            ) : authLoading ? (
              <span className="muted small" role="status">Checking account…</span>
            ) : (
              <button type="button" aria-label="Sign up / Log in" className="account-link" onClick={() => choose('login')}>
                <span className="account-avatar guest" aria-hidden="true">↗</span>
                <span className="account-copy"><strong>Sign up / Log in</strong><small>Save your report</small></span>
              </button>
            )}
          </div>
        </div>
      </aside>

      <div className="workspace">
        <header className="workspace-bar">
          <div className="workspace-crumb"><span>Workspace</span><span aria-hidden="true">/</span><strong>{PAGE_NAMES[tab]}</strong></div>
          <div className="source-promise"><span className="source-dot" />Public pages only</div>
        </header>
        <div className="workspace-content">
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
            <div id="tool" role="tabpanel" aria-labelledby={tab === 'home' ? undefined : `tab-${tab}`}>
              {tab === 'home' ? <HomePage signedIn={Boolean(user)} onNavigate={choose} /> : tab === 'draft' ? <DraftTab /> : <ReportTab key={tab} kind={tab} />}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
