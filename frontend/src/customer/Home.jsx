import { useState } from 'react'
import { apiPost } from '../api.js'
import { money, payeeName, statusInfo, TONE_CLASSES, when } from '../lib/format.js'

const NEEDS_ATTENTION = ['held', 'safety_paused', 'pending_verification']

// Home screen: balance, anything that needs the customer's attention, and
// recent payments.
export default function Home({ account, onPay, onOpenCase, onChanged }) {
  const { customer, transactions } = account
  const alerts = transactions.filter((t) => NEEDS_ATTENTION.includes(t.payment_status))

  return (
    <main className="flex flex-1 flex-col">
      <header className="bg-teal-700 px-5 pb-6 pt-5 text-white">
        <p className="text-sm text-teal-100">ScamShield Bank</p>
        <h1 className="mt-1 text-xl font-semibold">Hello, {customer.name.split(' ')[0]}</h1>
        <p className="mt-4 text-sm text-teal-100">Available balance</p>
        <p className="text-3xl font-semibold tracking-tight">{money(customer.balance)}</p>
        <button
          type="button"
          onClick={onPay}
          className="mt-5 min-h-11 w-full rounded-xl bg-white px-4 font-semibold text-teal-800 hover:bg-teal-50"
        >
          Send money
        </button>
      </header>

      {alerts.length > 0 && (
        <section aria-labelledby="alerts-heading" className="space-y-3 px-4 pt-4">
          <h2 id="alerts-heading" className="text-sm font-semibold text-slate-700">Needs your attention</h2>
          {alerts.map((transaction) => (
            <AlertCard key={transaction.transaction_id} transaction={transaction} onOpenCase={onOpenCase} onChanged={onChanged} />
          ))}
        </section>
      )}

      <section aria-labelledby="recent-heading" className="flex-1 px-4 pb-6 pt-5">
        <h2 id="recent-heading" className="text-sm font-semibold text-slate-700">Recent payments</h2>
        {transactions.length === 0 ? (
          <p className="mt-3 text-sm text-slate-600">No payments yet.</p>
        ) : (
          <ul className="mt-2 divide-y divide-slate-100">
            {transactions.map((transaction) => (
              <TransactionRow key={transaction.transaction_id} transaction={transaction} />
            ))}
          </ul>
        )}
      </section>
    </main>
  )
}

function TransactionRow({ transaction }) {
  const status = statusInfo(transaction.payment_status)
  return (
    <li className="flex items-center justify-between gap-3 py-3">
      <div className="min-w-0">
        <p className="truncate font-medium text-slate-900">{payeeName(transaction)}</p>
        <p className="text-xs text-slate-500">{when(transaction.created_at)}</p>
      </div>
      <div className="shrink-0 text-right">
        <p className="font-medium tabular-nums text-slate-900">{money(transaction.amount)}</p>
        {transaction.payment_status !== 'allowed' && (
          <span className={`mt-1 inline-block rounded-full px-2 py-0.5 text-xs font-medium ${TONE_CLASSES[status.tone]}`}>
            {status.label}
          </span>
        )}
      </div>
    </li>
  )
}

// One card per payment that is waiting for the customer.
function AlertCard({ transaction, onOpenCase, onChanged }) {
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  const summary = `${money(transaction.amount)} to ${payeeName(transaction)}`

  const verify = (confirmed) => {
    setBusy(true)
    setFailed(false)
    apiPost(`/transactions/${transaction.transaction_id}/verify`, { confirmed })
      .then(onChanged)
      .catch(() => setFailed(true))
      .finally(() => setBusy(false))
  }

  if (transaction.payment_status === 'safety_paused') {
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50 p-4">
        <p className="font-semibold text-red-900">Payment paused for your safety</p>
        <p className="mt-1 text-sm text-red-900">{summary}. Your money has not left your account.</p>
        <button
          type="button"
          onClick={() => onOpenCase(transaction.case_id)}
          className="mt-3 min-h-11 w-full rounded-xl bg-red-700 px-4 font-semibold text-white hover:bg-red-800"
        >
          See why and what to do
        </button>
      </div>
    )
  }

  if (transaction.payment_status === 'held') {
    return (
      <div className="rounded-2xl border border-amber-300 bg-amber-50 p-4">
        <p className="font-semibold text-amber-950">We paused a payment for a quick safety check</p>
        <p className="mt-1 text-sm text-amber-950">{summary}. Your money is safe.</p>
        <button
          type="button"
          onClick={() => onOpenCase(transaction.case_id)}
          className="mt-3 min-h-11 w-full rounded-xl bg-amber-600 px-4 font-semibold text-white hover:bg-amber-700"
        >
          Answer a few questions
        </button>
      </div>
    )
  }

  // pending_verification: a simple yes or no.
  return (
    <div className="rounded-2xl border border-amber-300 bg-amber-50 p-4">
      <p className="font-semibold text-amber-950">Did you make this payment?</p>
      <p className="mt-1 text-sm text-amber-950">{summary}</p>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => verify(true)}
          className="min-h-11 flex-1 rounded-xl bg-teal-700 px-4 font-semibold text-white hover:bg-teal-800 disabled:opacity-60"
        >
          Yes, it was me
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => verify(false)}
          className="min-h-11 flex-1 rounded-xl border border-slate-300 bg-white px-4 font-semibold text-slate-800 hover:bg-slate-50 disabled:opacity-60"
        >
          No, block it
        </button>
      </div>
      {failed && <p role="alert" className="mt-2 text-sm text-red-800">Could not save your answer. Please try again.</p>}
    </div>
  )
}
