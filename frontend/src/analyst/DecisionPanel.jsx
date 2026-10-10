import { useEffect, useState } from 'react'
import { apiPost } from '../api.js'
import { when } from '../lib/format.js'
import { Card, clock, secondsUntil } from './parts.jsx'

// The three analyst decisions (policy POL-7.3). Each writes a feedback record.
const DECISIONS = [
  {
    id: 'approve',
    label: 'Approve: confirm fraud',
    help: 'Stops the payment. The money stays with the customer.',
    className: 'bg-red-700 text-white hover:bg-red-800',
    sendsPayment: false,
  },
  {
    id: 'release',
    label: 'Release payment',
    help: 'Reviewed and genuine. The payment is sent.',
    className: 'bg-teal-700 text-white hover:bg-teal-800',
    sendsPayment: true,
  },
  {
    id: 'reject',
    label: 'Reject alert: false alarm',
    help: 'The alert was wrong. The payment is sent and the case is closed as a false positive.',
    className: 'border border-slate-300 bg-white text-slate-900 hover:bg-slate-50',
    sendsPayment: true,
  },
]

export default function DecisionPanel({ caseData, onDecided }) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const pauseLeft = useSecondsUntil(caseData.payment_status === 'safety_paused' ? caseData.held_until : null)

  const decided = caseData.analyst_decision
  if (decided) {
    const info = DECISIONS.find((d) => d.id === decided.decision)
    return (
      <Card title="Decision" aside={when(decided.at)}>
        <p className="font-medium text-slate-900">{info.label}</p>
        <p className="mt-1 text-sm text-slate-700">Reason: {decided.reason}</p>
        <p className="mt-2 text-xs text-slate-500">By {decided.analyst}. Stored as feedback for retraining.</p>
      </Card>
    )
  }
  if (caseData.payment_status !== 'held' && caseData.payment_status !== 'safety_paused') {
    return (
      <Card title="Decision">
        <p className="text-sm text-slate-700">No decision needed: the customer cancelled this payment.</p>
      </Card>
    )
  }

  const submit = (decision) => {
    setBusy(true)
    setError(null)
    apiPost(`/cases/${caseData.case_id}/decision`, { decision, reason })
      .then(() => {
        setReason('')
        onDecided()
      })
      .catch((err) => setError(err.message))
      .finally(() => setBusy(false))
  }
  const reasonMissing = reason.trim().length < 3

  return (
    <Card title="Decision">
      {pauseLeft > 0 && (
        <p className="mb-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
          Safety pause: {clock(pauseLeft)} of cooling-off left. The payment can be stopped now, but cannot be sent until the pause ends.
        </p>
      )}
      <label htmlFor="decision-reason" className="block text-sm font-medium text-slate-800">Reason (required)</label>
      <textarea
        id="decision-reason"
        rows={2}
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        maxLength={1000}
        className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
      />
      <div className="mt-3 grid gap-2 lg:grid-cols-3">
        {DECISIONS.map((decision) => (
          <div key={decision.id}>
            <button
              type="button"
              disabled={busy || reasonMissing || (decision.sendsPayment && pauseLeft > 0)}
              onClick={() => submit(decision.id)}
              aria-describedby={`help-${decision.id}`}
              className={`min-h-11 w-full rounded-lg px-3 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50 ${decision.className}`}
            >
              {decision.label}
            </button>
            <p id={`help-${decision.id}`} className="mt-1 text-xs text-slate-600">{decision.help}</p>
          </div>
        ))}
      </div>
      {error && <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
    </Card>
  )
}

function useSecondsUntil(iso) {
  const [left, setLeft] = useState(() => secondsUntil(iso))
  useEffect(() => {
    setLeft(secondsUntil(iso))
    const timer = setInterval(() => setLeft(secondsUntil(iso)), 1000)
    return () => clearInterval(timer)
  }, [iso])
  return left
}
