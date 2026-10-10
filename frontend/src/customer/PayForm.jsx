import { useState } from 'react'
import { apiPost } from '../api.js'
import { money } from '../lib/format.js'

const NEW_PAYEE = '__new__'

// Send money: pick a saved payee or enter a new account, then an amount.
// The bank scores the payment and either sends it or holds it for a check.
export default function PayForm({ customer, onBack, onDone, onOpenCase }) {
  const [payeeChoice, setPayeeChoice] = useState(customer.usual_payees[0]?.payee_id || NEW_PAYEE)
  const [newPayeeId, setNewPayeeId] = useState('')
  const [amount, setAmount] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null) // the saved transaction

  const savedPayee = customer.usual_payees.find((p) => p.payee_id === payeeChoice)

  const submit = (event) => {
    event.preventDefault()
    setSending(true)
    setError(null)
    apiPost('/transactions', {
      type: savedPayee ? savedPayee.type : 'TRANSFER',
      amount: Number(amount),
      sender_id: customer.customer_id,
      sender_balance_before: customer.balance,
      payee_id: savedPayee ? savedPayee.payee_id : newPayeeId.trim(),
      description: savedPayee ? savedPayee.name : `Account ${newPayeeId.trim()}`,
    })
      .then((response) => {
        setResult(response.transaction)
        onDone()
      })
      .catch(() => setError('We could not send this payment. Please try again.'))
      .finally(() => setSending(false))
  }

  if (result) return <Outcome transaction={result} onBack={onBack} onOpenCase={onOpenCase} />

  return (
    <main className="flex flex-1 flex-col">
      <ScreenHeader title="Send money" onBack={onBack} />
      <form onSubmit={submit} className="flex flex-1 flex-col gap-5 px-5 py-5">
        <div>
          <label htmlFor="payee" className="block text-sm font-medium text-slate-800">Pay to</label>
          <select
            id="payee"
            value={payeeChoice}
            onChange={(event) => setPayeeChoice(event.target.value)}
            className="mt-1 min-h-11 w-full rounded-xl border border-slate-300 bg-white px-3"
          >
            {customer.usual_payees.map((payee) => (
              <option key={payee.payee_id} value={payee.payee_id}>{payee.name}</option>
            ))}
            <option value={NEW_PAYEE}>Someone new…</option>
          </select>
        </div>

        {!savedPayee && (
          <div>
            <label htmlFor="new-payee" className="block text-sm font-medium text-slate-800">Their account number</label>
            <input
              id="new-payee"
              required
              value={newPayeeId}
              onChange={(event) => setNewPayeeId(event.target.value)}
              autoComplete="off"
              className="mt-1 min-h-11 w-full rounded-xl border border-slate-300 px-3"
            />
          </div>
        )}

        <div>
          <label htmlFor="amount" className="block text-sm font-medium text-slate-800">Amount (₹)</label>
          <input
            id="amount"
            required
            type="number"
            inputMode="decimal"
            min="1"
            step="any"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            aria-describedby="amount-hint"
            className="mt-1 min-h-11 w-full rounded-xl border border-slate-300 px-3 text-lg tabular-nums"
          />
          <p id="amount-hint" className="mt-1 text-xs text-slate-500">Available: {money(customer.balance)}</p>
        </div>

        {error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p>}

        <button
          type="submit"
          disabled={sending}
          className="mt-auto min-h-12 w-full rounded-xl bg-teal-700 px-4 font-semibold text-white hover:bg-teal-800 disabled:opacity-60"
        >
          {sending ? 'Sending…' : 'Send payment'}
        </button>
      </form>
    </main>
  )
}

// What happened to the payment, in plain words.
function Outcome({ transaction, onBack, onOpenCase }) {
  const summary = `${money(transaction.amount)} to ${transaction.description}`
  const status = transaction.payment_status

  return (
    <main className="flex flex-1 flex-col px-5 py-8 text-center" role="status">
      {status === 'allowed' ? (
        <>
          <div aria-hidden="true" className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-emerald-100 text-3xl text-emerald-700">✓</div>
          <h1 className="mt-4 text-xl font-semibold text-slate-900">Payment sent</h1>
          <p className="mt-1 text-slate-600">{summary}</p>
        </>
      ) : status === 'held' ? (
        <>
          <div aria-hidden="true" className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-amber-100 text-3xl text-amber-700">⏸</div>
          <h1 className="mt-4 text-xl font-semibold text-slate-900">We paused this payment for a quick safety check</h1>
          <p className="mt-1 text-slate-600">{summary}</p>
          <p className="mt-3 text-slate-700">Your money is safe and has not left your account. Please answer a few questions so we can check it.</p>
          <button
            type="button"
            onClick={() => onOpenCase(transaction.case_id)}
            className="mt-6 min-h-12 w-full rounded-xl bg-amber-600 px-4 font-semibold text-white hover:bg-amber-700"
          >
            Continue
          </button>
        </>
      ) : (
        <>
          <div aria-hidden="true" className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-amber-100 text-3xl text-amber-700">?</div>
          <h1 className="mt-4 text-xl font-semibold text-slate-900">Please confirm this payment</h1>
          <p className="mt-1 text-slate-600">{summary}</p>
          <p className="mt-3 text-slate-700">Go back to the home screen to confirm it was you.</p>
        </>
      )}
      <button
        type="button"
        onClick={onBack}
        className="mt-3 min-h-12 w-full rounded-xl border border-slate-300 px-4 font-semibold text-slate-800 hover:bg-slate-50"
      >
        Back to home
      </button>
    </main>
  )
}

export function ScreenHeader({ title, onBack, lang }) {
  return (
    <header className="flex items-center gap-2 border-b border-slate-200 px-2 py-2">
      <button
        type="button"
        onClick={onBack}
        aria-label="Back to home"
        className="flex h-11 w-11 items-center justify-center rounded-full text-2xl text-slate-700 hover:bg-slate-100"
      >
        <span aria-hidden="true">‹</span>
      </button>
      <h1 lang={lang} className="text-lg font-semibold text-slate-900">{title}</h1>
    </header>
  )
}
