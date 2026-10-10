import { useEffect, useRef, useState } from 'react'

// Full-screen warning shown when the bank's rules start a safety pause.
// The guidance text comes from the backend's fixed warning message (policy
// POL-5.4), already in the customer's language.
export default function SafetyPause({ t, lang, warningText, heldUntil, onCancel, children }) {
  const { intro, points, outro } = splitWarning(warningText)
  const remaining = useCountdown(heldUntil)
  const heading = useRef(null)

  // Move keyboard and screen-reader focus to the warning when it appears.
  useEffect(() => {
    heading.current?.focus()
  }, [])

  return (
    <div lang={lang} className="flex-1 overflow-y-auto bg-red-50 px-5 py-6">
      <div role="alert">
        <div aria-hidden="true" className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-red-600 text-3xl text-white">!</div>
        <h2 ref={heading} tabIndex={-1} className="mt-4 text-center text-xl font-bold text-red-900 outline-none">
          {t.pauseTitle}
        </h2>
        <p className="mt-1 text-center font-medium text-red-900">{t.moneySafe}</p>
        {intro && <p className="mt-4 text-slate-900">{intro}</p>}
      </div>

      {points.length > 0 && (
        <ul className="mt-4 space-y-2">
          {points.map((point) => (
            <li key={point} className="flex gap-3 rounded-xl bg-white p-3 text-slate-900 shadow-sm">
              <span aria-hidden="true" className="mt-0.5 font-bold text-red-700">✓</span>
              <span>{point}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4 rounded-xl bg-white p-3 text-center shadow-sm">
        {remaining > 0 ? (
          <>
            <p className="text-sm text-slate-600">{t.coolingOff}</p>
            {/* Not a live region: a ticking clock would be read out every second. */}
            <p className="text-2xl font-semibold tabular-nums text-slate-900">{formatClock(remaining)}</p>
          </>
        ) : (
          <p className="text-sm text-slate-800">{t.coolingEnded}</p>
        )}
      </div>

      {outro && <p className="mt-4 text-sm text-slate-800">{outro}</p>}

      <div className="mt-5 space-y-2">
        <a
          href="tel:1930"
          className="flex min-h-12 w-full items-center justify-center rounded-xl bg-red-700 px-4 text-center font-semibold text-white hover:bg-red-800"
        >
          {t.call1930}
        </a>
        <a
          href="https://cybercrime.gov.in"
          target="_blank"
          rel="noopener noreferrer"
          className="flex min-h-12 w-full items-center justify-center rounded-xl border border-red-300 bg-white px-4 text-center font-semibold text-red-800 hover:bg-red-100"
        >
          {t.reportOnline}
        </a>
        <button
          type="button"
          onClick={onCancel}
          className="min-h-12 w-full rounded-xl border border-slate-300 bg-white px-4 font-semibold text-slate-900 hover:bg-slate-50"
        >
          {t.cancelPayment}
        </button>
      </div>

      <details className="mt-5 rounded-xl bg-white p-3 shadow-sm">
        <summary className="min-h-6 cursor-pointer font-medium text-slate-800">{t.showConversation}</summary>
        <div className="mt-3">{children}</div>
      </details>
    </div>
  )
}

// The warning is one paragraph, then "•" bullet lines, then a closing line.
function splitWarning(text) {
  const lines = (text || '').split('\n').map((line) => line.trim()).filter(Boolean)
  const isPoint = (line) => line.startsWith('•')
  return {
    intro: (lines.find((line) => !isPoint(line)) || '').replace(/^⚠\s*/, ''),
    points: lines.filter(isPoint).map((line) => line.replace(/^•\s*/, '')),
    outro: lines.slice(1).filter((line) => !isPoint(line)).join(' '),
  }
}

// Seconds left until an ISO time, updated once a second.
function useCountdown(untilIso) {
  const secondsLeft = () => (untilIso ? Math.max(0, Math.ceil((new Date(untilIso) - Date.now()) / 1000)) : 0)
  const [remaining, setRemaining] = useState(secondsLeft)
  useEffect(() => {
    setRemaining(secondsLeft())
    const timer = setInterval(() => setRemaining(secondsLeft()), 1000)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [untilIso])
  return remaining
}

const formatClock = (seconds) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
