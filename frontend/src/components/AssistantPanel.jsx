import { useRef, useState } from 'react'
import { askAssistant } from '../api'

const STARTERS = [
  "What's working for me?",
  'What should I post next?',
  'Which hooks should I drop?',
  'Give me 3 hooks to test this week.',
]

export default function AssistantPanel({ ready, onUnauthorized }) {
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const busyRef = useRef(false)

  async function send(raw) {
    const message = raw.trim()
    if (!ready || !message || busyRef.current) return
    busyRef.current = true
    setBusy(true)
    setDraft('')
    setError(null)
    const history = messages.slice(-6).map(({ role, text }) => ({ role, text }))
    setMessages((current) => [...current, { role: 'user', text: message }])
    try {
      const reply = await askAssistant(message, history)
      setMessages((current) => [...current, { role: 'assistant', ...reply, text: reply.answer }])
    } catch (err) {
      if (err?.status === 401) onUnauthorized?.()
      else setError(err.message || 'The assistant could not answer. Try again.')
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }

  return (
    <section className="panel assistant-panel" aria-label="Creator assistant">
      <header>
        <h2>Ask about your Reels</h2>
        <p className="muted">Answers use your report and link back to the Reels behind them.</p>
      </header>
      {!ready ? (
        <p className="note">Your creator report needs to finish before the assistant can use its evidence.</p>
      ) : messages.length === 0 ? (
        <div className="assistant-starters" aria-label="Starter questions">
          {STARTERS.map((text) => <button type="button" key={text} onClick={() => send(text)} disabled={busy}>{text}</button>)}
        </div>
      ) : (
        <ol className="assistant-messages" aria-label="Conversation" aria-live="polite">
          {messages.map((message, index) => (
            <li key={`${message.role}-${index}`} className={`assistant-message ${message.role}`}>
              <p>{message.text || message.answer}</p>
              {message.role === 'assistant' && (
                <>
                  {message.keys?.map((key) => <span className="chip citation-key" key={key}>{key}</span>)}
                  {message.reel_ids?.length > 0 && (
                    <p className="small citation-links">Evidence: {message.reel_ids.map((id) => (
                      <a className="chip" href={`#reel-${id}`} key={id}>{id}</a>
                    ))}</p>
                  )}
                </>
              )}
            </li>
          ))}
        </ol>
      )}
      {error && <p className="alert" role="alert">{error}</p>}
      {ready && (
        <>
          {messages.length > 0 && messages.at(-1)?.follow_ups?.length > 0 && !busy && (
            <div className="assistant-followups" aria-label="Follow-up questions">
              {messages.at(-1).follow_ups.map((text) => <button type="button" key={text} onClick={() => send(text)}>{text}</button>)}
            </div>
          )}
          <form className="assistant-form" onSubmit={(event) => { event.preventDefault(); send(draft) }}>
            <label htmlFor="assistant-question">Your question</label>
            <div>
              <input id="assistant-question" type="text" value={draft} maxLength={1200} disabled={busy}
                     placeholder="Ask what your report supports" onChange={(event) => setDraft(event.target.value)} />
              <button className="primary" type="submit" disabled={busy || !draft.trim()}>{busy ? 'Thinking…' : 'Ask'}</button>
            </div>
          </form>
        </>
      )}
    </section>
  )
}
