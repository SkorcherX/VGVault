import type { ReactNode } from 'react'

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  )
}

export function Modal({
  title,
  onClose,
  children,
  wide,
}: {
  title: string
  onClose: () => void
  children: ReactNode
  wide?: boolean
}) {
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? 'wide' : ''}`} role="dialog" aria-label={title}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="ghost" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null
  return <p className="error">{error instanceof Error ? error.message : String(error)}</p>
}

/** Multi-select rendered as a compact checkbox list. */
export function CheckList<T extends string | number>({
  label,
  options,
  value,
  onChange,
}: {
  label: string
  options: { value: T; label: string }[]
  value: T[]
  onChange: (v: T[]) => void
}) {
  if (options.length === 0) return null
  return (
    <fieldset className="checklist">
      <legend>
        {label}
        {value.length > 0 && (
          <button className="link" onClick={() => onChange([])}>
            clear
          </button>
        )}
      </legend>
      {options.map((o) => (
        <label key={String(o.value)}>
          <input
            type="checkbox"
            checked={value.includes(o.value)}
            onChange={(e) =>
              onChange(e.target.checked ? [...value, o.value] : value.filter((v) => v !== o.value))
            }
          />
          {o.label}
        </label>
      ))}
    </fieldset>
  )
}

export const money = (v: string | number | null | undefined) =>
  v === null || v === undefined || v === ''
    ? '—'
    : Number(v).toLocaleString(undefined, { style: 'currency', currency: 'USD' })
