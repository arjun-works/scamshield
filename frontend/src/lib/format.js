// Formatting helpers shared by the customer app and the analyst console.

const rupees = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })
const dateTime = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })

export const money = (amount) => rupees.format(amount)
export const when = (iso) => dateTime.format(new Date(iso))

// Who the money went to, in the most readable form available.
export function payeeName(transaction) {
  return transaction.customer_context?.payee_name || transaction.description || transaction.payee_id
}

// How a payment status is shown to the customer. `tone` picks the colours.
const STATUS = {
  allowed: { label: 'Sent', tone: 'ok' },
  released: { label: 'Sent', tone: 'ok' },
  pending_verification: { label: 'Needs your confirmation', tone: 'warn' },
  held: { label: 'On hold for a safety check', tone: 'warn' },
  safety_paused: { label: 'Paused for your safety', tone: 'danger' },
  cancelled: { label: 'Cancelled by you', tone: 'muted' },
  blocked: { label: 'Blocked', tone: 'muted' },
  rejected: { label: 'Stopped by the bank', tone: 'muted' },
}

export const statusInfo = (status) => STATUS[status] || { label: status, tone: 'muted' }

export const TONE_CLASSES = {
  ok: 'bg-emerald-50 text-emerald-800',
  warn: 'bg-amber-100 text-amber-900',
  danger: 'bg-red-100 text-red-800',
  muted: 'bg-slate-100 text-slate-700',
}

// BCP 47 codes for the lang attribute, so screen readers pronounce text correctly.
export const LANG_CODE = { English: 'en', Tamil: 'ta', Hindi: 'hi' }
