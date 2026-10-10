// Diverging bar chart of the model's SHAP risk factors.
// Bars to the right raise the risk score, bars to the left lower it. Direction
// is shown by side, by the +/- value and by colour, so colour is not needed to
// read it. Each row's label is the plain-English fact behind the factor.
const RAISES = '#d95926'
const LOWERS = '#2a78d6'

export default function ShapChart({ factors }) {
  if (!factors.length) return <p className="text-sm text-slate-600">No model factors: this payment type is outside the model's scope.</p>
  const largest = Math.max(...factors.map((f) => Math.abs(f.shap_value)))

  return (
    <figure>
      <div className="mb-2 flex items-center justify-end gap-4 text-xs text-slate-600">
        <span className="flex items-center gap-1.5"><Swatch color={LOWERS} /> lowers risk</span>
        <span className="flex items-center gap-1.5"><Swatch color={RAISES} /> raises risk</span>
      </div>
      <ul className="space-y-2.5">
        {factors.map((factor) => {
          const raises = factor.shap_value > 0
          const width = `${(Math.abs(factor.shap_value) / largest) * 50}%`
          const signed = `${raises ? '+' : '−'}${Math.abs(factor.shap_value).toFixed(2)}`
          return (
            <li key={factor.feature} title={`${factor.label}: SHAP ${signed} (${factor.direction})`}>
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className="text-slate-800">{factor.text}</span>
                <span className="shrink-0 tabular-nums text-slate-600">{signed}</span>
              </div>
              {/* Track with the zero line in the middle. */}
              <div className="relative mt-1 h-3 rounded bg-slate-100">
                <div className="absolute inset-y-0 left-1/2 w-px bg-slate-400" />
                <div
                  className="absolute inset-y-0"
                  style={{
                    width,
                    background: raises ? RAISES : LOWERS,
                    left: raises ? '50%' : undefined,
                    right: raises ? undefined : '50%',
                    borderRadius: raises ? '0 4px 4px 0' : '4px 0 0 4px',
                  }}
                />
              </div>
            </li>
          )
        })}
      </ul>
      <figcaption className="mt-3 text-xs text-slate-500">
        SHAP values in log-odds: how much each fact moved this payment's risk score. Top {factors.length} factors.
      </figcaption>
    </figure>
  )
}

const Swatch = ({ color }) => <span aria-hidden="true" className="h-2.5 w-2.5 rounded-sm" style={{ background: color }} />
