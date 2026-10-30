import { useState } from 'react'
import { signIn, signUp } from './api'

export default function AuthPage({ onAuthenticated, initialError = null }) {
  const [mode, setMode] = useState('signup')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [instagramUrl, setInstagramUrl] = useState('')
  const [error, setError] = useState(initialError)
  const [busy, setBusy] = useState(false)

  async function submit(event) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      const session = mode === 'signup'
        ? await signUp({ email: email.trim(), password, instagram_url: instagramUrl.trim() })
        : await signIn({ email: email.trim(), password })
      onAuthenticated(session.user)
    } catch (err) {
      setError(err.message || 'We could not sign you in. Try again.')
    } finally {
      setBusy(false)
    }
  }

  function changeMode(next) {
    setMode(next)
    setError(null)
  }

  return (
    <main className="auth-page">
      <section className="auth-copy">
        <p className="auth-mark">ReelMind AI</p>
        <h1>Your Reels, understood.</h1>
        <p>Save your creator report and return to it whenever you need a new idea to test.</p>
      </section>
      <section className="auth-panel" aria-label="Account access">
        <div className="auth-switch" role="group" aria-label="Account action">
          <button type="button" aria-pressed={mode === 'signup'} onClick={() => changeMode('signup')}>Sign up</button>
          <button type="button" aria-pressed={mode === 'login'} onClick={() => changeMode('login')}>Log in</button>
        </div>
        <h2>{mode === 'signup' ? 'Create your account' : 'Welcome back'}</h2>
        <form onSubmit={submit}>
          <label htmlFor="account-email">Email</label>
          <input id="account-email" type="email" autoComplete="email" required value={email}
                 onChange={(event) => setEmail(event.target.value)} disabled={busy} />
          <label htmlFor="account-password">Password</label>
          <input id="account-password" type="password" autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
                 minLength={mode === 'signup' ? 8 : undefined} required value={password}
                 onChange={(event) => setPassword(event.target.value)} disabled={busy} />
          {mode === 'signup' && (
            <>
              <label htmlFor="account-instagram">Instagram profile link or handle</label>
              <input id="account-instagram" type="text" autoComplete="url" required value={instagramUrl}
                     placeholder="instagram.com/yourname" onChange={(event) => setInstagramUrl(event.target.value)} disabled={busy} />
              <p className="muted small">Your first public profile report starts after you sign up.</p>
            </>
          )}
          {error && <p className="alert" role="alert">{error}</p>}
          <button className="primary auth-submit" type="submit" disabled={busy}>
            {busy ? 'Please wait…' : mode === 'signup' ? 'Create account' : 'Log in'}
          </button>
        </form>
      </section>
    </main>
  )
}
