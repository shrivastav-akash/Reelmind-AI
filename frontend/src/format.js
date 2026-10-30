// Small display helpers shared by the components. Numbers and times only; no copy here.

// Status words come first, colour second: the UI never says a status by colour alone.
export const STATUS_WORDS = {
  accessible: 'Accessible',
  login_wall: 'Login wall',
  blocked: 'Blocked',
  not_found: 'Not found',
  timeout: 'Timed out',
}

const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })
// The venue's clock: the browser's own timezone (tests pin Asia/Kolkata).
const clock = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit' })
const day = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short' })

// 412000 -> "412K". Callers show "not shown publicly" for null, never 0.
export const short = (n) => compact.format(n)
export const clockTime = (iso) => clock.format(new Date(iso))
export const dayMonth = (isoDate) => day.format(new Date(isoDate))
export const seconds = (s) => `${Number(s.toFixed(1))} s`
