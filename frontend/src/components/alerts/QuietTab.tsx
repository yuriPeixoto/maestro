import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAllRules, useCancelMaintenance, useEndSilence } from '../../hooks/useAlerting'
import { useServerName } from '../../hooks/useServerName'
import type { MaintenanceWindow, ScopedRule, ServerGroup, Silence } from '../../services/alertingApi'
import type { ServerStatus } from '../../types/server'
import { MaintenanceDialog, SilenceDialog } from './QuietDialogs'
import { ServerName } from '../primitives'
import {
  alertingError, buttonDanger, buttonPrimary, clockTime, dateTime, minutesUntil, pill, ruleName, sectionCard, smallButton,
  tableCell, tableHead,
} from './ui'

const MINUTES_PER_HOUR = 60

function SilenceWhere({ silence, groups }: { silence: Silence; groups: ServerGroup[] }) {
  const { t } = useTranslation()
  const nameOf = useServerName()
  if (silence.scope === 'global') return <>{t('alerts.screen.place.global')}</>
  if (silence.scope === 'group') {
    return <>{t('alerts.screen.place.group', { name: groups.find((g) => g.group_id === silence.group_id)?.name ?? '—' })}</>
  }
  return <ServerName name={nameOf(silence.server_id ?? '')} />
}

function Remaining({ until }: { until: string }) {
  const { t } = useTranslation()
  const minutes = minutesUntil(until)
  return minutes < MINUTES_PER_HOUR
    ? <>{t('alerts.screen.quiet.minutesLeft', { count: minutes })}</>
    : <>{t('alerts.screen.quiet.hoursLeft', { count: Math.round(minutes / MINUTES_PER_HOUR) })}</>
}

function When({ window: w }: { window: MaintenanceWindow }) {
  const { t } = useTranslation()
  if (!w.weekly) return <>{t('alerts.screen.quiet.once')}</>
  const days = w.weekly.weekdays.map((d) => t(`alerts.screen.quiet.weekday.${d}`)).join(', ')
  const [hours, minutes] = w.weekly.local_start.split(':').map(Number)
  const end = new Date(2000, 0, 1, hours, minutes + w.weekly.duration_minutes)
  const endText = `${String(end.getHours()).padStart(2, '0')}:${String(end.getMinutes()).padStart(2, '0')}`
  return (
    <>
      {t('alerts.screen.quiet.everyWeek', { days, from: w.weekly.local_start.slice(0, 5), to: endText })}
      <span className="block text-[11px] text-slate-400 font-mono">{w.weekly.time_zone}</span>
    </>
  )
}

function Next({ window: w }: { window: MaintenanceWindow }) {
  const { t } = useTranslation()
  if (w.active && w.next_ends_at) return <span className={pill.quiet}>{t('alerts.screen.quiet.nowUntil', { time: clockTime(w.next_ends_at) })}</span>
  if (!w.next_starts_at) return <>—</>
  return <span className="font-mono">{dateTime(w.next_starts_at)}{w.next_ends_at ? `–${clockTime(w.next_ends_at)}` : ''}</span>
}

export default function QuietTab({ servers, groups, silences, windows, canManage }: {
  servers: ServerStatus[]
  groups: ServerGroup[]
  silences: Silence[]
  windows: MaintenanceWindow[]
  canManage: boolean
}) {
  const { t } = useTranslation()
  const nameOf = useServerName()
  const { data: rules = [] } = useAllRules()
  const ruleById = new Map<string, ScopedRule>(rules.map((r) => [r.rule_id, r]))
  const end = useEndSilence()
  const cancel = useCancelMaintenance()
  const [dialog, setDialog] = useState<'silence' | 'maintenance' | null>(null)

  return (
    <div className="flex flex-col gap-4">
      <p className="text-xs text-slate-400">{t('alerts.screen.quiet.intro')}</p>

      <section className={sectionCard} aria-labelledby="silences-title">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 id="silences-title" className="font-bold text-slate-100">{t('alerts.screen.quiet.silences')}</h3>
          {canManage && <button type="button" className={buttonPrimary} onClick={() => setDialog('silence')}>+ {t('alerts.screen.quiet.silence')}</button>}
        </div>
        {silences.length === 0 ? (
          <p className="mt-3 text-sm text-slate-400">{t('alerts.screen.quiet.noSilences')}</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className={tableHead}>{t('alerts.screen.col.what')}</th>
                  <th className={tableHead}>{t('alerts.screen.quiet.where')}</th>
                  <th className={tableHead}>{t('alerts.screen.quiet.until')}</th>
                  <th className={tableHead}>{t('alerts.screen.quiet.reason')}</th>
                  <th className={`${tableHead} hidden md:table-cell`}>{t('alerts.screen.quiet.who')}</th>
                  <th className={tableHead}><span className="sr-only">{t('alerts.screen.col.actions')}</span></th>
                </tr>
              </thead>
              <tbody>
                {silences.map((s) => {
                  const rule = s.rule_id ? ruleById.get(s.rule_id) : undefined
                  return (
                    <tr key={s.silence_id}>
                      <td className={tableCell}>{s.rule_id ? (rule ? ruleName(rule, t) : '—') : t('alerts.screen.quiet.allRules')}</td>
                      <td className={tableCell}><SilenceWhere silence={s} groups={groups} /></td>
                      <td className={tableCell}>
                        <span className={s.active ? pill.quiet : pill.off}>
                          {s.active
                            ? t('alerts.screen.quiet.untilTime', { time: clockTime(s.ends_at) })
                            : t('alerts.screen.quiet.startsOn', { when: dateTime(s.starts_at) })}
                        </span>
                        {s.active && <div className="mt-1 text-xs text-slate-400"><Remaining until={s.ends_at} /></div>}
                      </td>
                      <td className={tableCell}>{s.reason}</td>
                      <td className={`${tableCell} font-mono hidden md:table-cell`}>{s.created_by}</td>
                      <td className={`${tableCell} text-right`}>
                        {canManage && (
                          <button type="button" className={`${buttonDanger} ${smallButton}`} disabled={end.isPending}
                            onClick={() => end.mutate(s.silence_id)}>
                            {t('alerts.screen.quiet.endNow')}
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {end.isError && <p role="alert" className="mt-2 text-xs text-red-300">{alertingError(end.error, t)}</p>}
      </section>

      <section className={sectionCard} aria-labelledby="maintenance-title">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 id="maintenance-title" className="font-bold text-slate-100">{t('alerts.screen.quiet.maintenance')}</h3>
          {canManage && <button type="button" className={buttonPrimary} onClick={() => setDialog('maintenance')}>+ {t('alerts.screen.quiet.planMaintenance')}</button>}
        </div>
        {windows.length === 0 ? (
          <p className="mt-3 text-sm text-slate-400">{t('alerts.screen.quiet.noMaintenance')}</p>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className={tableHead}>{t('alerts.screen.col.server')}</th>
                  <th className={tableHead}>{t('alerts.screen.quiet.when')}</th>
                  <th className={tableHead}>{t('alerts.screen.quiet.next')}</th>
                  <th className={tableHead}>{t('alerts.screen.quiet.reason')}</th>
                  <th className={`${tableHead} hidden md:table-cell`}>{t('alerts.screen.quiet.who')}</th>
                  <th className={tableHead}><span className="sr-only">{t('alerts.screen.col.actions')}</span></th>
                </tr>
              </thead>
              <tbody>
                {windows.map((w) => (
                  <tr key={w.window_id}>
                    <td className={tableCell}><ServerName name={nameOf(w.server_id)} /></td>
                    <td className={tableCell}><When window={w} /></td>
                    <td className={tableCell}><Next window={w} /></td>
                    <td className={tableCell}>{w.reason}</td>
                    <td className={`${tableCell} font-mono hidden md:table-cell`}>{w.created_by}</td>
                    <td className={`${tableCell} text-right`}>
                      {canManage && (
                        <button type="button" className={`${buttonDanger} ${smallButton}`} disabled={cancel.isPending}
                          onClick={() => { if (window.confirm(t('alerts.screen.quiet.confirmCancel'))) cancel.mutate(w.window_id) }}>
                          {t('alerts.screen.quiet.cancel')}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {cancel.isError && <p role="alert" className="mt-2 text-xs text-red-300">{alertingError(cancel.error, t)}</p>}
        <p className="mt-2 text-xs text-slate-400">{t('alerts.screen.quiet.overlapHint')}</p>
      </section>

      {dialog === 'silence' && <SilenceDialog servers={servers} groups={groups} onClose={() => setDialog(null)} />}
      {dialog === 'maintenance' && <MaintenanceDialog servers={servers} onClose={() => setDialog(null)} />}
    </div>
  )
}
