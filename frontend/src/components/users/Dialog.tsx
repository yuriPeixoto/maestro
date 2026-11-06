import { useEffect, useId, useRef, type ReactNode } from 'react'

const FOCUSABLE = 'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea, [href], [tabindex]:not([tabindex="-1"])'

interface DialogProps {
  title: string
  subtitle?: ReactNode
  onClose: () => void
  children: ReactNode
  footer: ReactNode
  /** False while a request runs, so Escape or a click outside cannot drop its answer. */
  dismissible?: boolean
}

/** Modal with focus kept inside, Escape to close and focus returned to whatever opened it. */
export default function Dialog({ title, subtitle, onClose, children, footer, dismissible = true }: DialogProps) {
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    panel.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus()
    return () => opener?.focus()
  }, [])

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape' && dismissible) {
      event.stopPropagation()
      onClose()
      return
    }
    if (event.key !== 'Tab' || !panel.current) return
    const focusable = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)]
    if (focusable.length === 0) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/70 backdrop-blur-sm"
      onMouseDown={(event) => { if (event.target === event.currentTarget && dismissible) onClose() }}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={handleKeyDown}
        className="w-full max-w-md bg-brand-slate border border-white/10 rounded-2xl p-6 shadow-2xl"
      >
        <h2 id={titleId} className="text-[17px] font-bold text-slate-100">{title}</h2>
        {subtitle && <div className="mt-1 text-xs text-slate-400 font-mono">{subtitle}</div>}
        <div className="mt-4">{children}</div>
        <div className="mt-5 flex justify-end gap-2">{footer}</div>
      </div>
    </div>
  )
}
