import { useEffect, useState } from 'react'
import { apiGet } from '../api.js'
import { usePolling } from '../lib/usePolling.js'
import Home from '../customer/Home.jsx'
import PayForm from '../customer/PayForm.jsx'
import Chat from '../customer/Chat.jsx'

const SAVED_CUSTOMER = 'scamshield.customer'

// The customer's banking app, shown in a phone-sized frame.
// Three screens: home, send money, and the safety check for a held payment.
export default function Customer() {
  const [customers, setCustomers] = useState([])
  const [customerId, setCustomerId] = useState(() => localStorage.getItem(SAVED_CUSTOMER) || 'CUST-001')
  const [account, setAccount] = useState(null) // { customer, transactions }
  const [screen, setScreen] = useState({ name: 'home' })
  const [error, setError] = useState(null)

  useEffect(() => {
    apiGet('/customers').then(setCustomers).catch(() => {})
  }, [])

  // Keep the account fresh: an analyst may release or stop a payment at any time.
  const refresh = () =>
    apiGet(`/customers/${customerId}`)
      .then((data) => {
        setAccount(data)
        setError(null)
      })
      .catch((err) => setError(err.status === 404 ? 'no-customer' : 'offline'))
  usePolling(refresh, 4000, [customerId])

  const switchCustomer = (id) => {
    localStorage.setItem(SAVED_CUSTOMER, id)
    setAccount(null)
    setScreen({ name: 'home' })
    setCustomerId(id)
  }

  return (
    <div className="flex justify-center px-0 py-0 sm:py-6">
      <div className="flex min-h-[calc(100dvh-3.5rem)] w-full max-w-md flex-col bg-white shadow-xl sm:min-h-[46rem] sm:rounded-3xl sm:border sm:border-slate-200">
        {/* Demo control: there is no login, so pick which customer you are. */}
        <div className="flex items-center gap-2 border-b border-slate-100 bg-slate-50 px-4 py-2 text-xs text-slate-600 sm:rounded-t-3xl">
          <label htmlFor="demo-customer" className="shrink-0">Demo customer</label>
          <select
            id="demo-customer"
            value={customerId}
            onChange={(event) => switchCustomer(event.target.value)}
            className="min-h-8 w-full rounded-md border border-slate-300 bg-white px-2 py-1 text-xs"
          >
            {customers.length === 0 && <option value={customerId}>{customerId}</option>}
            {customers.map((c) => (
              <option key={c.customer_id} value={c.customer_id}>
                {c.name} · {c.preferred_language}
              </option>
            ))}
          </select>
        </div>

        {error && !account ? (
          <Problem kind={error} />
        ) : !account ? (
          <p className="p-6 text-slate-600">Loading your account…</p>
        ) : screen.name === 'pay' ? (
          <PayForm
            customer={account.customer}
            onBack={() => setScreen({ name: 'home' })}
            onDone={refresh}
            onOpenCase={(caseId) => setScreen({ name: 'chat', caseId })}
          />
        ) : screen.name === 'chat' ? (
          <Chat
            caseId={screen.caseId}
            customer={account.customer}
            onBack={() => {
              refresh()
              setScreen({ name: 'home' })
            }}
          />
        ) : (
          <Home
            account={account}
            onPay={() => setScreen({ name: 'pay' })}
            onOpenCase={(caseId) => setScreen({ name: 'chat', caseId })}
            onChanged={refresh}
          />
        )}
      </div>
    </div>
  )
}

function Problem({ kind }) {
  return (
    <div role="alert" className="m-6 rounded-xl bg-amber-50 p-4 text-sm text-amber-900">
      {kind === 'no-customer' ? (
        <>
          <p className="font-semibold">No demo customers found.</p>
          <p className="mt-1">Seed them with <code>scripts/seed_demo.py</code> and restart the backend.</p>
        </>
      ) : (
        <>
          <p className="font-semibold">Cannot reach the bank right now.</p>
          <p className="mt-1">Check that the backend is running on port 8080. Retrying…</p>
        </>
      )}
    </div>
  )
}
