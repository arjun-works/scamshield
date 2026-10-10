import { useEffect, useRef, useState } from 'react'
import { apiGet, apiPost } from '../api.js'
import { LANG_CODE, money } from '../lib/format.js'
import { usePolling } from '../lib/usePolling.js'
import { ScreenHeader } from './PayForm.jsx'
import SafetyPause from './SafetyPause.jsx'
import { stringsFor } from './strings.js'

const MAX_IMAGE_BYTES = 5 * 1024 * 1024

// The safety check for one held payment: a chat with the bank's assistant,
// which turns into the safety-pause warning if scam signs are found.
export default function Chat({ caseId, customer, onBack }) {
  const [chat, setChat] = useState(null)
  const [caseInfo, setCaseInfo] = useState(null)
  const [text, setText] = useState('')
  const [image, setImage] = useState(null) // { base64, mimeType, name }
  const [pending, setPending] = useState(null) // the message being sent
  const [error, setError] = useState(null)
  const cancelDialog = useRef(null)
  const bottom = useRef(null)

  const language = chat?.language || customer.preferred_language
  const t = stringsFor(language)
  const lang = LANG_CODE[language] || 'en'
  const sending = pending !== null

  // Opening the chat is free (a fixed greeting) and safe to repeat.
  useEffect(() => {
    apiPost(`/cases/${caseId}/chat/start`).then(setChat).catch(() => setError(t.sendFailed))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId])

  // Watch the case: the fraud team may release or stop the payment meanwhile.
  usePolling(() => apiGet(`/cases/${caseId}`).then(setCaseInfo).catch(() => {}), 4000, [caseId])

  // Keep the newest message in view.
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' })
  }, [chat?.messages.length, sending])

  const pickImage = (event) => {
    const file = event.target.files[0]
    event.target.value = '' // allow picking the same file again
    if (!file) return
    if (file.size > MAX_IMAGE_BYTES) {
      setError(t.imageTooBig)
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      setError(null)
      setImage({ base64: reader.result.split(',')[1], mimeType: file.type, name: file.name })
    }
    reader.readAsDataURL(file)
  }

  const send = (event) => {
    event.preventDefault()
    const body = { text: text.trim() }
    if (image) Object.assign(body, { image_base64: image.base64, image_mime_type: image.mimeType })
    if (!body.text && !image) return

    setPending({ text: body.text, has_image: Boolean(image) })
    setError(null)
    apiPost(`/cases/${caseId}/chat/messages`, body)
      .then((result) => {
        setChat(result.chat)
        setCaseInfo((current) => ({ ...current, payment_status: result.payment_status, held_until: result.held_until }))
        setText('')
        setImage(null)
      })
      .catch(() => setError(t.sendFailed))
      .finally(() => setPending(null))
  }

  const cancelPayment = () => {
    cancelDialog.current.close()
    apiPost(`/cases/${caseId}/cancel`)
      .then((updated) => {
        setCaseInfo(updated)
        setChat((current) => ({ ...current, status: 'closed' }))
      })
      .catch(() => setError(t.sendFailed))
  }

  const status = caseInfo?.payment_status
  const canCancel = status === 'held' || status === 'safety_paused'
  const messages = chat?.messages || []
  const transcript = (
    <ol className="space-y-3">
      {messages.map((message, index) => (
        <Message key={index} message={message} lang={lang} t={t} />
      ))}
      {pending && <Message message={{ role: 'customer', ...pending }} lang={lang} t={t} />}
    </ol>
  )

  return (
    <main className="flex min-h-0 flex-1 flex-col">
      <ScreenHeader title={t.chatTitle} onBack={onBack} lang={lang} />
      {caseInfo && (
        <p className="border-b border-slate-100 bg-slate-50 px-4 py-2 text-sm text-slate-700">
          {money(caseInfo.amount)} → {caseInfo.customer_context?.payee_name || caseInfo.payee_id}
        </p>
      )}

      {status === 'safety_paused' ? (
        <SafetyPause
          t={t}
          lang={lang}
          warningText={messages.find((m) => m.kind === 'safety_warning')?.text}
          heldUntil={caseInfo.held_until}
          onCancel={() => cancelDialog.current.showModal()}
        >
          {transcript}
        </SafetyPause>
      ) : (
        <>
          {/* role="log": new messages are announced politely, in order. */}
          <div role="log" aria-live="polite" aria-label={t.chatTitle} className="flex-1 overflow-y-auto px-4 py-4">
            {transcript}
            {sending && (
              <p lang={lang} className="mt-3 flex items-center gap-2 text-sm text-slate-600">
                <span aria-hidden="true" className="flex gap-1">
                  <Dot delay="0ms" /><Dot delay="150ms" /><Dot delay="300ms" />
                </span>
                {t.typing}
              </p>
            )}
            <div ref={bottom} />
          </div>

          {error && <p role="alert" lang={lang} className="mx-4 mb-2 rounded-xl bg-red-50 p-3 text-sm text-red-800">{error}</p>}

          {status === 'cancelled' ? (
            <p role="status" lang={lang} className="m-4 rounded-xl bg-slate-100 p-3 text-sm text-slate-800">{t.cancelled}</p>
          ) : chat && chat.status !== 'active' ? (
            <p role="status" lang={lang} className="m-4 rounded-xl bg-slate-100 p-3 text-sm text-slate-800">{t.chatClosed}</p>
          ) : (
            <form onSubmit={send} lang={lang} className="border-t border-slate-200 px-3 py-3">
              {image && (
                <p className="mb-2 flex items-center justify-between gap-2 rounded-lg bg-teal-50 px-3 py-2 text-sm text-teal-900">
                  <span className="truncate">{t.screenshotAttached}: {image.name}</span>
                  <button type="button" onClick={() => setImage(null)} className="min-h-8 shrink-0 font-semibold underline">
                    {t.remove}
                  </button>
                </p>
              )}
              <div className="flex items-end gap-2">
                <label
                  className={`flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-full border border-slate-300 text-xl text-slate-700 hover:bg-slate-100 focus-within:outline focus-within:outline-3 focus-within:outline-offset-2 focus-within:outline-teal-700 ${sending ? 'opacity-50' : ''}`}
                >
                  <span aria-hidden="true">📎</span>
                  <span className="sr-only">{t.attach}</span>
                  <input type="file" accept="image/png,image/jpeg,image/webp" onChange={pickImage} disabled={sending} className="sr-only" />
                </label>
                <label htmlFor="chat-text" className="sr-only">{t.placeholder}</label>
                <textarea
                  id="chat-text"
                  rows={1}
                  value={text}
                  onChange={(event) => setText(event.target.value)}
                  onKeyDown={(event) => {
                    // Enter sends; Shift+Enter makes a new line.
                    if (event.key === 'Enter' && !event.shiftKey) send(event)
                  }}
                  placeholder={t.placeholder}
                  disabled={sending || !chat}
                  maxLength={4000}
                  className="max-h-32 min-h-11 flex-1 resize-none rounded-2xl border border-slate-300 px-3 py-2.5 disabled:bg-slate-50"
                />
                <button
                  type="submit"
                  disabled={sending || !chat || (!text.trim() && !image)}
                  className="min-h-11 shrink-0 rounded-full bg-teal-700 px-4 font-semibold text-white hover:bg-teal-800 disabled:opacity-50"
                >
                  {t.send}
                </button>
              </div>
              {canCancel && (
                <button
                  type="button"
                  onClick={() => cancelDialog.current.showModal()}
                  className="mt-2 min-h-9 w-full text-sm font-medium text-slate-600 underline hover:text-slate-900"
                >
                  {t.cancelPayment}
                </button>
              )}
            </form>
          )}
        </>
      )}

      {/* Native modal dialog: the browser handles focus and Esc. */}
      <dialog ref={cancelDialog} lang={lang} aria-labelledby="cancel-title" className="m-auto w-80 max-w-[90vw] rounded-2xl p-5">
        <h2 id="cancel-title" className="text-lg font-semibold text-slate-900">{t.cancelConfirmTitle}</h2>
        <p className="mt-2 text-slate-700">{t.cancelConfirmBody}</p>
        <div className="mt-5 flex gap-2">
          <button
            type="button"
            onClick={() => cancelDialog.current.close()}
            className="min-h-11 flex-1 rounded-xl border border-slate-300 px-3 font-semibold text-slate-800 hover:bg-slate-50"
          >
            {t.keepPayment}
          </button>
          <button
            type="button"
            onClick={cancelPayment}
            className="min-h-11 flex-1 rounded-xl bg-red-700 px-3 font-semibold text-white hover:bg-red-800"
          >
            {t.confirmCancel}
          </button>
        </div>
      </dialog>
    </main>
  )
}

function Message({ message, lang, t }) {
  const fromCustomer = message.role === 'customer'
  return (
    <li className={`flex ${fromCustomer ? 'justify-end' : 'justify-start'}`}>
      <div
        lang={lang}
        className={`max-w-[85%] whitespace-pre-line rounded-2xl px-3.5 py-2.5 ${
          fromCustomer ? 'rounded-br-md bg-teal-700 text-white' : 'rounded-bl-md bg-slate-100 text-slate-900'
        }`}
      >
        {/* Says who is speaking for screen readers; colour alone is not enough. */}
        <span className="sr-only">{fromCustomer ? 'You: ' : 'ScamShield Bank: '}</span>
        {message.has_image && <span className="block text-sm italic opacity-90">📎 {t.screenshotSent}</span>}
        {message.text}
      </div>
    </li>
  )
}

const Dot = ({ delay }) => (
  <span className="h-2 w-2 rounded-full bg-slate-400 motion-safe:animate-bounce" style={{ animationDelay: delay }} />
)
