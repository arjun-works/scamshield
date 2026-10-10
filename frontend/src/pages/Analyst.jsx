import { useState } from 'react'
import { apiGet } from '../api.js'
import { money, payeeName, when } from '../lib/format.js'
import { usePolling } from '../lib/usePolling.js'
import CaseDetail from '../analyst/CaseDetail.jsx'
import { PaymentChip, TIER_COLOR, TierBadge } from '../analyst/parts.jsx'

const WAITING = ['held', 'safety_paused']

// The fraud analyst's console: live payment feed, case queue, case detail.
// Everything is refreshed by polling the backend every few seconds.
export default function Analyst() {
  const [cases, setCases] = useState([])
  const [transactions, setTransactions] = useState([])
  const [feedback, setFeedback] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [showAll, setShowAll] = useState(false)
  const [offline, setOffline] = useState(false)

  const refresh = () => {
    apiGet('/cases?limit=100')
      .then((data) => {
        setCases(data)
        setOffline(false)
      })
      .catch(() => setOffline(true))
    apiGet('/transactions?limit=30').then(setTransactions).catch(() => {})
    apiGet('/feedback').then(setFeedback).catch(() => {})
  }
  usePolling(refresh, 4000)

  const waiting = cases.filter((c) => WAITING.includes(c.payment_status))
  const listed = showAll ? cases : waiting
  // Show the first waiting case until the analyst picks one.
  const currentId = selectedId || listed[0]?.case_id || null

  return (
    <main className="grid md:h-[calc(100dvh-3.5rem)] md:grid-cols-[19rem_minmax(0,1fr)] md:grid-rows-[15rem_minmax(0,1fr)] xl:grid-cols-[17rem_20rem_minmax(0,1fr)] xl:grid-rows-1">
      <h1 className="sr-only">Analyst console</h1>

      {/* Live feed */}
      <section aria-labelledby="feed-heading" className="border-b border-slate-200 bg-white md:overflow-y-auto md:border-r">
        <h2 id="feed-heading" className="sticky top-0 border-b border-slate-100 bg-white px-4 py-3 text-sm font-semibold text-slate-900">
          Live payments <span className="ml-1 font-normal text-slate-500">updates every 4s</span>
        </h2>
        <ul className="max-h-64 divide-y divide-slate-100 overflow-y-auto md:max-h-none md:overflow-visible">
          {transactions.map((t) => (
            <li key={t.transaction_id} className="flex items-center gap-2 px-4 py-2 text-sm">
              <span aria-hidden="true" className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: TIER_COLOR[t.tier] }} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-slate-900">{payeeName(t)}</p>
                <p className="text-xs text-slate-500">{t.tier} · {when(t.created_at)}</p>
              </div>
              <div className="shrink-0 text-right">
                <p className="tabular-nums text-slate-900">{money(t.amount)}</p>
                {t.payment_status !== 'allowed' && <PaymentChip status={t.payment_status} />}
              </div>
            </li>
          ))}
          {transactions.length === 0 && <li className="px-4 py-3 text-sm text-slate-600">No payments yet.</li>}
        </ul>
      </section>

      {/* Case queue */}
      <section aria-labelledby="cases-heading" className="border-b border-slate-200 bg-slate-50 md:overflow-y-auto md:border-b-0 md:border-r xl:col-start-2 xl:row-start-1">
        <div className="sticky top-0 border-b border-slate-200 bg-slate-50 px-4 py-3">
          <h2 id="cases-heading" className="text-sm font-semibold text-slate-900">Cases</h2>
          <dl className="mt-2 grid grid-cols-3 gap-2 text-center">
            <Kpi label="Waiting" value={waiting.length} />
            <Kpi label="Held" value={money(waiting.reduce((sum, c) => sum + c.amount, 0))} />
            <Kpi label="Decisions" value={feedback.length} />
          </dl>
          <label className="mt-2 flex min-h-6 items-center gap-2 text-xs text-slate-700">
            <input type="checkbox" checked={showAll} onChange={(event) => setShowAll(event.target.checked)} />
            Show closed cases too
          </label>
        </div>
        {offline && <p role="alert" className="m-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Cannot reach the backend. Retrying…</p>}
        <ul className="space-y-2 p-3">
          {listed.map((c) => (
            <li key={c.case_id}>
              <button
                type="button"
                onClick={() => setSelectedId(c.case_id)}
                aria-current={c.case_id === currentId ? 'true' : undefined}
                className={`w-full rounded-lg border bg-white p-3 text-left hover:border-slate-400 ${
                  c.case_id === currentId ? 'border-slate-900 ring-1 ring-slate-900' : 'border-slate-200'
                }`}
                style={{ borderLeftWidth: 6, borderLeftColor: TIER_COLOR[c.tier] }}
              >
                <span className="flex items-center justify-between gap-2">
                  <TierBadge tier={c.tier} />
                  <span className="text-sm font-semibold tabular-nums text-slate-900">{money(c.amount)}</span>
                </span>
                <span className="mt-1.5 block truncate text-sm text-slate-800">
                  {c.customer_context?.customer_name || c.sender_id} → {c.customer_context?.payee_name || c.payee_id}
                </span>
                <span className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                  <PaymentChip status={c.payment_status} />
                  {c.scam_signals.length > 0 && <span className="rounded bg-red-100 px-1.5 py-0.5 font-medium text-red-800">{c.scam_signals.length} scam signals</span>}
                  {c.customer_denied_payment && <span className="rounded bg-red-100 px-1.5 py-0.5 font-medium text-red-800">customer denies</span>}
                  <span>{when(c.created_at)}</span>
                </span>
              </button>
            </li>
          ))}
          {listed.length === 0 && !offline && (
            <li className="p-3 text-sm text-slate-600">{showAll ? 'No cases yet.' : 'No cases are waiting for a decision.'}</li>
          )}
        </ul>
      </section>

      {/* Case detail */}
      <section aria-label="Case detail" className="md:col-start-2 md:row-span-2 md:row-start-1 md:overflow-y-auto xl:col-start-3 xl:row-span-1">
        {currentId ? (
          <CaseDetail key={currentId} caseId={currentId} onChanged={refresh} />
        ) : (
          <p className="p-6 text-slate-600">Select a case to see its evidence.</p>
        )}
      </section>
    </main>
  )
}

const Kpi = ({ label, value }) => (
  <div className="rounded-lg bg-white px-1 py-1.5">
    <dd className="truncate text-sm font-semibold tabular-nums text-slate-900">{value}</dd>
    <dt className="text-xs text-slate-500">{label}</dt>
  </div>
)
