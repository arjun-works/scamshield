// Small building blocks shared across the analyst console.

// Status colours for risk tiers. The colour is always paired with the tier
// name, so it never carries the meaning alone.
export const TIER_COLOR = {
  Low: '#0ca30c',
  Medium: '#fab219',
  High: '#ec835a',
  Critical: '#d03b3b',
}

export function TierBadge({ tier }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2 py-0.5 text-xs font-semibold text-slate-800">
      <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full" style={{ background: TIER_COLOR[tier] || '#898781' }} />
      {tier}
    </span>
  )
}

const PAYMENT_LABEL = {
  allowed: 'Sent',
  released: 'Sent (released)',
  pending_verification: 'Awaiting customer',
  held: 'Held',
  safety_paused: 'Safety pause',
  cancelled: 'Cancelled by customer',
  blocked: 'Blocked by customer',
  rejected: 'Stopped',
}

export function PaymentChip({ status }) {
  const waiting = status === 'held' || status === 'safety_paused' || status === 'pending_verification'
  return (
    <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${waiting ? 'bg-slate-800 text-white' : 'bg-slate-100 text-slate-700'}`}>
      {PAYMENT_LABEL[status] || status}
    </span>
  )
}

export function Card({ title, aside, children }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
        {aside && <span className="text-xs text-slate-500">{aside}</span>}
      </div>
      {children}
    </section>
  )
}

// English names for the scam signal types reported by the protection agent.
export const SIGNAL_LABEL = {
  third_party_on_call: 'Someone on a call is guiding the payment',
  threat_of_arrest_or_freeze: 'Threat of arrest, legal action or account freeze',
  fake_official: 'Caller claims to be police, an official or bank staff',
  urgency_pressure: 'Pressure to pay immediately',
  secrecy_demand: 'Told to keep the payment secret',
  remote_access_app: 'Asked to install a remote-access app',
  promised_returns: 'Promised or guaranteed returns',
  fee_to_release: 'Fee demanded to release a prize, parcel, refund, loan or job',
  otp_or_credential_request: 'Asked for an OTP, PIN, password or card details',
  suspicious_link: 'Suspicious link or phone number',
  safe_account_transfer: 'Told to move money to a "safe account"',
  embedded_instructions: 'Message contains instructions aimed at the bank\'s AI',
}

// Seconds from now until an ISO time (0 if it has passed).
export const secondsUntil = (iso) => (iso ? Math.max(0, Math.ceil((new Date(iso) - Date.now()) / 1000)) : 0)
export const clock = (seconds) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
