import { useTranslation } from 'react-i18next'
import type { CapacityStatus } from '../../services/api'

const STATUS_STYLES: Record<CapacityStatus, { pill: string; big: string }> = {
  safe:     { pill: 'bg-emerald-500/10 text-emerald-400', big: 'text-emerald-400' },
  watch:    { pill: 'bg-amber-500/10 text-amber-400',     big: 'text-amber-400' },
  critical: { pill: 'bg-red-500/10 text-red-400',         big: 'text-red-400' },
  no_data:  { pill: 'bg-white/5 text-slate-500',          big: 'text-slate-500' },
}

/** One metric's capacity at a glance: name and state, a headline, one line of detail. */
export default function CapacityCard({
  label, status, headline, detail,
}: { label: string; status: CapacityStatus; headline: string; detail: string }) {
  const { t } = useTranslation()
  const style = STATUS_STYLES[status]
  return (
    <div className="flex flex-col gap-1.5 p-4 rounded-xl border border-white/10 bg-white/[0.03]">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-mono text-slate-400 uppercase tracking-widest">{label}</span>
        <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full ${style.pill}`}>{t(`capacity.pill.${status}`)}</span>
      </div>
      <p className={`text-lg font-bold font-mono ${style.big}`}>{headline}</p>
      <p className="text-xs text-slate-400 leading-relaxed">{detail}</p>
    </div>
  )
}
