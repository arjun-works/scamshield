import { useState } from 'react'
import { apiGet, apiPost } from '../api.js'
import { LANG_CODE, money, when } from '../lib/format.js'
import { usePolling } from '../lib/usePolling.js'
import DecisionPanel from './DecisionPanel.jsx'
import ShapChart from './ShapChart.jsx'
import { Card, PaymentChip, SIGNAL_LABEL, TierBadge } from './parts.jsx'

// Everything an analyst needs to decide one case (policy POL-7.2).
export default function CaseDetail({ caseId, onChanged }) {
  const [caseData, setCaseData] = useState(null)
  const [chat, setChat] = useState(null)

  const refresh = () => {
    apiGet(`/cases/${caseId}`).then(setCaseData).catch(() => {})
    // 404 simply means the customer has not opened the chat yet.
    apiGet(`/cases/${caseId}/chat`).then(setChat).catch(() => setChat(null))
  }
  usePolling(refresh, 4000, [caseId])

  if (!caseData || caseData.case_id !== caseId) return <p className="p-6 text-slate-600">Loading case…</p>

  const context = caseData.customer_context || {}
  const afterDecision = () => {
    refresh()
    onChanged()
  }

  return (
    <div className="space-y-4 p-4">
      <header className="rounded-xl border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold text-slate-900">{caseData.case_id}</h2>
          <TierBadge tier={caseData.tier} />
          <PaymentChip status={caseData.payment_status} />
          <span className="text-xs text-slate-500">Case {caseData.status} · opened {when(caseData.created_at)}</span>
        </div>
        <p className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">{money(caseData.amount)}</p>
        <p className="text-sm text-slate-700">
          {caseData.type} from <strong>{context.customer_name || caseData.sender_id}</strong> to{' '}
          <strong>{context.payee_name || caseData.payee_id}</strong>
        </p>
        <p className="mt-2 text-sm text-slate-700">{caseData.reason}</p>
        {caseData.customer_denied_payment && (
          <p className="mt-2 rounded-lg bg-red-50 p-2 text-sm font-medium text-red-800">The customer says they did not make this payment.</p>
        )}
      </header>

      <DecisionPanel caseData={caseData} onDecided={afterDecision} />
      <Investigation caseData={caseData} onStarted={refresh} />

      <div className="grid gap-4 2xl:grid-cols-2">
        <Card title="Model risk factors" aside={`Risk score ${caseData.probability.toFixed(3)} · tier from ${caseData.tier_source === 'model' ? 'model' : 'behaviour rule'}`}>
          <ShapChart factors={caseData.risk_factors} />
        </Card>

        <div className="space-y-4">
          <Card title="Customer" aside={context.known_customer ? 'Synthetic profile' : undefined}>
            {context.known_customer ? (
              <>
                <p className="text-sm text-slate-800">
                  {context.customer_name} · {context.segment.replace('_', ' ')} · prefers {context.preferred_language}
                </p>
                <p className="mt-1 text-sm text-slate-600">
                  Typical payments {money(context.typical_amount_min)} to {money(context.typical_amount_max)}
                </p>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-800">
                  {context.notes.map((note) => <li key={note}>{note}</li>)}
                </ul>
              </>
            ) : (
              <p className="text-sm text-slate-600">No profile is held for sender {caseData.sender_id}.</p>
            )}
          </Card>

          <Card title="Payee (mule indicators)">
            <dl className="grid grid-cols-3 gap-3 text-sm">
              <Stat label="Different senders before" value={caseData.payee_stats.payee_distinct_senders_before} />
              <Stat label="Payments in last 24h" value={caseData.payee_stats.payee_inflow_count_24h} />
              <Stat label="Received in last 24h" value={money(caseData.payee_stats.payee_inflow_amount_24h)} />
            </dl>
          </Card>
        </div>
      </div>

      <ScamSignals signals={caseData.scam_signals} />
      <Transcript chat={chat} required={caseData.chat_required} />
      <AuditLog entries={caseData.audit_log} />
    </div>
  )
}

const Stat = ({ label, value }) => (
  <div>
    <dt className="text-xs text-slate-500">{label}</dt>
    <dd className="text-base font-semibold tabular-nums text-slate-900">{value}</dd>
  </div>
)

// The Gemini investigation: evidence and advice, never a money decision.
function Investigation({ caseData, onStarted }) {
  const [starting, setStarting] = useState(false)
  const status = caseData.investigation_status
  const result = caseData.investigation
  const start = () => {
    setStarting(true)
    apiPost(`/cases/${caseData.case_id}/investigate`).then(onStarted).finally(() => setStarting(false))
  }

  return (
    <Card title="Gemini investigation" aside={result ? `${result.model} · ${when(result.generated_at)}` : undefined}>
      {result ? (
        <div className="space-y-3 text-sm">
          <p className="text-slate-900">{result.investigation_summary}</p>
          <div className="grid gap-3 lg:grid-cols-3">
            <EvidenceList title="Top risk factors" items={result.top_risk_factors} />
            <EvidenceList title="Customer history" items={result.historical_evidence} />
            <EvidenceList title="Payee and mule evidence" items={result.payee_mule_evidence} />
          </div>
          <div className="rounded-lg bg-slate-50 p-3">
            <p className="text-xs font-semibold text-slate-600">Recommended next step (advice only)</p>
            <p className="mt-1 text-slate-900">{result.recommended_next_step}</p>
          </div>
          <p className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
            Policy:
            {result.policy_references.map((ref) => (
              <span key={ref.section} className="rounded border border-slate-200 px-1.5 py-0.5 text-slate-800">
                {ref.section} {ref.title}
              </span>
            ))}
          </p>
        </div>
      ) : status === 'queued' || status === 'running' ? (
        <p role="status" className="text-sm text-slate-700">Gemini is gathering evidence… this usually takes one to two minutes.</p>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-slate-700">
            {status === 'failed' ? 'The investigation failed (see the audit log). You can try again.' : 'Not investigated yet.'}
          </p>
          <button
            type="button"
            disabled={starting}
            onClick={start}
            className="min-h-10 rounded-lg bg-slate-900 px-3 text-sm font-semibold text-white hover:bg-slate-700 disabled:opacity-50"
          >
            Run investigation
          </button>
        </div>
      )}
    </Card>
  )
}

const EvidenceList = ({ title, items }) => (
  <div>
    <p className="text-xs font-semibold text-slate-600">{title}</p>
    {items.length ? (
      <ul className="mt-1 list-disc space-y-1 pl-5 text-slate-800">
        {items.map((item) => <li key={item}>{item}</li>)}
      </ul>
    ) : (
      <p className="mt-1 text-slate-500">None recorded.</p>
    )}
  </div>
)

function ScamSignals({ signals }) {
  return (
    <Card title="Scam signals from the customer conversation" aside={signals.length ? `${signals.length} found` : undefined}>
      {signals.length === 0 ? (
        <p className="text-sm text-slate-600">None so far.</p>
      ) : (
        <ul className="space-y-3">
          {signals.map((signal) => (
            <li key={signal.type}>
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className="font-medium text-slate-900">{SIGNAL_LABEL[signal.type] || signal.type}</span>
                <span className="shrink-0 tabular-nums text-slate-600">confidence {signal.confidence.toFixed(2)}</span>
              </div>
              {/* Confidence meter: one hue, length carries the value. */}
              <div className="mt-1 h-2 rounded bg-slate-100">
                <div className="h-2 rounded" style={{ width: `${signal.confidence * 100}%`, background: '#2a78d6' }} />
              </div>
              <p className="mt-1 text-sm text-slate-700">
                “{signal.evidence}” <span className="text-xs text-slate-500">· {signal.source === 'pattern_check' ? 'found by pattern check' : 'reported by Gemini'}</span>
              </p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function Transcript({ chat, required }) {
  const lang = chat ? LANG_CODE[chat.language] : undefined
  return (
    <Card title="Customer chat" aside={chat ? `${chat.language} · ${chat.status.replace('_', ' ')}` : undefined}>
      {!chat ? (
        <p className="text-sm text-slate-600">{required ? 'The customer has not opened the safety check yet.' : 'No chat for this case.'}</p>
      ) : (
        <ol className="space-y-2">
          {chat.messages.map((message, index) => (
            <li key={index} className="text-sm">
              <span className="text-xs font-semibold text-slate-500">
                {message.role === 'customer' ? 'Customer' : 'Assistant'} · {when(message.at)}
                {message.kind === 'safety_warning' && ' · safety warning'}
              </span>
              {message.text && <p lang={lang} className="whitespace-pre-line text-slate-900">{message.text}</p>}
              {message.has_image && (
                <blockquote className="mt-1 border-l-2 border-slate-300 pl-3 text-slate-700">
                  <span className="text-xs font-semibold text-slate-500">Text read from the customer's screenshot</span>
                  <p className="whitespace-pre-line">{message.evidence_transcript || '(not read)'}</p>
                </blockquote>
              )}
            </li>
          ))}
        </ol>
      )}
    </Card>
  )
}

function AuditLog({ entries }) {
  return (
    <Card title="Audit log" aside={`${entries.length} entries`}>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs text-slate-500">
            <tr>
              <th scope="col" className="py-1 pr-3 font-medium">Time</th>
              <th scope="col" className="py-1 pr-3 font-medium">Actor</th>
              <th scope="col" className="py-1 pr-3 font-medium">Event</th>
              <th scope="col" className="py-1 font-medium">Detail</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {entries.map((entry, index) => (
              <tr key={index} className="align-top">
                <td className="whitespace-nowrap py-1.5 pr-3 tabular-nums text-slate-600">{when(entry.at)}</td>
                <td className="whitespace-nowrap py-1.5 pr-3 text-slate-800">{entry.actor}</td>
                <td className="whitespace-nowrap py-1.5 pr-3 text-slate-800">{entry.event}</td>
                <td className="py-1.5 text-slate-700">{entry.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
