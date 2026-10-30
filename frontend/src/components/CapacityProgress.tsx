import { useTranslation } from 'react-i18next'
import type { CollectionProgress } from '../services/api'

const STATES = ['learning', 'preliminary', 'evolving', 'complete'] as const

export default function CapacityProgress({ collection }: { collection: CollectionProgress }) {
  const { t } = useTranslation()
  const { days_collected, min_days, weekly_pattern_days, window_days, state, complete_on } = collection
  const percent = Math.min(100, (days_collected / window_days) * 100)

  const ranges: Record<typeof STATES[number], string> = {
    learning:    t('capacity.progress.rangeUnder', { max: min_days }),
    preliminary: t('capacity.progress.range', { min: min_days, max: weekly_pattern_days - 1 }),
    evolving:    t('capacity.progress.range', { min: weekly_pattern_days, max: window_days - 1 }),
    complete:    t('capacity.progress.rangeOver', { min: window_days }),
  }

  return (
    <div className="rounded-2xl border border-white/10 bg-brand-slate p-6">
      <div className="flex items-baseline justify-between gap-4 flex-wrap mb-3">
        <h2 className="text-sm font-bold text-slate-200">{t('capacity.progress.title')}</h2>
        <p className="text-xs text-slate-400">
          <span className="font-mono font-bold text-slate-200">
            {t('capacity.progress.days', { days: days_collected, window: window_days })}
          </span>
          {' · '}
          {complete_on
            ? t('capacity.progress.completeOn', { date: new Date(`${complete_on}T12:00:00`).toLocaleDateString() })
            : t('capacity.progress.complete')}
        </p>
      </div>

      <div className="h-2 rounded-full bg-white/5 overflow-hidden mb-5">
        <div className="h-full rounded-full bg-brand-purple" style={{ width: `${percent}%` }} />
      </div>

      <table className="w-full text-left text-xs">
        <thead className="text-[10px] text-slate-500 uppercase tracking-widest">
          <tr>
            <th className="py-1.5 pr-4 font-medium">{t('capacity.progress.stateColumn')}</th>
            <th className="py-1.5 pr-4 font-medium">{t('capacity.progress.daysColumn')}</th>
            <th className="py-1.5 font-medium">{t('capacity.progress.meaningColumn')}</th>
          </tr>
        </thead>
        <tbody>
          {STATES.map((rowState) => {
            const current = rowState === state
            return (
              <tr
                key={rowState}
                className={`border-t border-white/5 ${current ? 'bg-brand-purple/10' : ''}`}
                aria-current={current ? 'true' : undefined}
              >
                <td className={`py-2 px-2 whitespace-nowrap ${current ? 'font-bold text-brand-purple' : 'text-slate-300'}`}>
                  {t(`capacity.progress.state.${rowState}`)}
                  {current && (
                    <span className="ml-2 text-[9px] uppercase tracking-widest">{t('capacity.progress.current')}</span>
                  )}
                </td>
                <td className="py-2 pr-4 font-mono whitespace-nowrap text-slate-400">{ranges[rowState]}</td>
                <td className={`py-2 ${current ? 'text-slate-200' : 'text-slate-500'}`}>
                  {t(`capacity.progress.meaning.${rowState}`, { window: window_days })}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
