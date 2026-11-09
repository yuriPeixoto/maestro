import { useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'
import { useAcknowledge, useOpenAlerts } from '../../hooks/useAlerting'
import { usePermissions } from '../../hooks/usePermissions'
import { useServerName } from '../../hooks/useServerName'
import type { OpenAlert } from '../../services/alertingApi'
import { formatRuleValue, metricLabel, relativeTime } from '../../utils/format'
import { ServerName } from '../primitives'
import { alertingError, buttonGhost, limitText, pill, sectionCard, smallButton, tableCell, tableHead } from './ui'

function Situation({ alert }: { alert: OpenAlert }) {
  const { t } = useTranslation()
  if (alert.acknowledged_at) {
    return (
      <>
        <span className={pill.off}>{t('alerts.screen.open.acknowledgedBy', { name: alert.acknowledged_by ?? '—' })}</span>
        <div className="mt-1 text-xs text-slate-400">
          {t('alerts.screen.open.acknowledgedWhen', { when: relativeTime(alert.acknowledged_at, t) })}
        </div>
      </>
    )
  }
  if (alert.quiet) return <span className={pill.quiet}>{t(`alerts.screen.open.quiet.${alert.quiet}`)}</span>
  return <span className={pill.warning}>{t('alerts.screen.open.open')}</span>
}

function What({ alert }: { alert: OpenAlert }) {
  const { t } = useTranslation()
  const noData = alert.state === 'NO_DATA'
  return (
    <>
      <span className="flex flex-wrap items-center gap-2">
        {metricLabel(alert.metric_name, t)}
        {noData
          ? <span className={pill.noData}>{t('alerts.screen.noData')}</span>
          : <span className={pill[alert.severity]}>{t(`alerts.severity.${alert.severity}`)}</span>}
      </span>
      <div className="mt-1 text-xs text-slate-400 font-mono">
        {noData
          ? t('alerts.screen.open.noDataHint')
          : t('alerts.screen.open.valueAndLimit', { value: formatRuleValue(alert.metric_name, alert.value), limit: limitText(alert) })}
      </div>
    </>
  )
}

export default function OpenAlertsCard() {
  const { t } = useTranslation()
  const { data: alerts, isLoading } = useOpenAlerts()
  const acknowledge = useAcknowledge()
  const canAcknowledge = usePermissions().can('alerts.acknowledge')
  const nameOf = useServerName()

  return (
    <section className={sectionCard} aria-labelledby="open-alerts-title">
      <h2 id="open-alerts-title" className="font-bold text-slate-100">
        {t('alerts.screen.open.title')} <span className="font-mono text-slate-400">{alerts?.length ?? ''}</span>
      </h2>
      <p className="mt-0.5 text-xs text-slate-400 leading-relaxed">{t('alerts.screen.open.desc')}</p>

      {isLoading ? (
        <p className="mt-3 flex items-center gap-2 text-sm text-slate-400"><Loader2 className="w-4 h-4 animate-spin" aria-hidden />{t('common.loading')}</p>
      ) : !alerts?.length ? (
        <p className="mt-3 text-sm text-slate-400">{t('alerts.screen.open.none')}</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full">
            <caption className="sr-only">{t('alerts.screen.open.title')}</caption>
            <thead>
              <tr>
                <th className={tableHead}>{t('alerts.screen.col.server')}</th>
                <th className={tableHead}>{t('alerts.screen.col.what')}</th>
                <th className={tableHead}>{t('alerts.screen.col.since')}</th>
                <th className={tableHead}>{t('alerts.screen.col.situation')}</th>
                <th className={tableHead}><span className="sr-only">{t('alerts.screen.col.actions')}</span></th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((alert) => {
                const busy = acknowledge.isPending
                  && acknowledge.variables?.ruleId === alert.rule_id && acknowledge.variables?.serverId === alert.server_id
                return (
                  <tr key={`${alert.rule_id}:${alert.server_id}`}>
                    <td className={tableCell}><ServerName name={nameOf(alert.server_id)} /></td>
                    <td className={tableCell}><What alert={alert} /></td>
                    <td className={tableCell}>
                      {alert.since ? relativeTime(alert.since, t) : '—'}
                      {alert.state === 'FIRING' && !alert.acknowledged_at && alert.cooldown_minutes > 0 && (
                        <div className="mt-1 text-xs text-slate-400">{t('alerts.screen.open.repeats', { minutes: alert.cooldown_minutes })}</div>
                      )}
                    </td>
                    <td className={tableCell}><Situation alert={alert} /></td>
                    <td className={`${tableCell} text-right`}>
                      {canAcknowledge && !alert.acknowledged_at && (
                        <button
                          type="button"
                          className={`${buttonGhost} ${smallButton}`}
                          disabled={busy}
                          onClick={() => acknowledge.mutate({ serverId: alert.server_id, ruleId: alert.rule_id })}
                        >
                          {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden />}
                          {t('alerts.screen.open.acknowledge')}
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
      {acknowledge.isError && <p role="alert" className="mt-2 text-xs text-red-300">{alertingError(acknowledge.error, t)}</p>}
      <p className="mt-2 text-xs text-slate-400">{t('alerts.screen.open.footnote')}</p>
    </section>
  )
}
