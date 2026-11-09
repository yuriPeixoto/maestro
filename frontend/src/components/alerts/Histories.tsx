import { useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'
import { useAlertEvents } from '../../hooks/useAlerts'
import { useNotificationHistory } from '../../hooks/useAlertChannels'
import { useChannelsAt, useRetries } from '../../hooks/useAlerting'
import type { ScopedRule } from '../../services/alertingApi'
import type { AlertEvent } from '../../services/api'
import { CHANNEL_ICON, channelTarget } from '../../utils/channels'
import { formatRuleValue, metricLabel } from '../../utils/format'
import { clockTime, dateTime, pill, placesReaching, sectionCard, tableCell, tableHead } from './ui'

const STATE_PILL: Record<AlertEvent['state'], string> = { FIRING: pill.critical, RESOLVED: pill.server, NO_DATA: pill.noData }

const Loading = ({ text }: { text: string }) => (
  <p className="mt-3 flex items-center gap-2 text-sm text-slate-400"><Loader2 className="w-4 h-4 animate-spin" aria-hidden />{text}</p>
)

/** Changes of state on one server, including those a silence kept from the channels. */
export function EventsHistory({ serverId }: { serverId: string }) {
  const { t } = useTranslation()
  const { data, isLoading } = useAlertEvents(serverId)
  const events = data?.events ?? []

  return (
    <section className={sectionCard} aria-labelledby="events-title">
      <h3 id="events-title" className="font-bold text-slate-100">{t('alerts.screen.events.title')}</h3>
      <p className="mt-0.5 text-xs text-slate-400">{t('alerts.screen.events.desc')}</p>
      {isLoading ? <Loading text={t('common.loading')} /> : events.length === 0 ? (
        <p className="mt-3 text-sm text-slate-400">{t('alerts.noEvents')}</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th className={tableHead}>{t('alerts.events.state')}</th>
                <th className={tableHead}>{t('alerts.events.metric')}</th>
                <th className={tableHead}>{t('alerts.events.value')}</th>
                <th className={tableHead}>{t('alerts.events.threshold')}</th>
                <th className={tableHead}>{t('alerts.events.time')}</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.event_id}>
                  <td className={tableCell}><span className={STATE_PILL[event.state]}>{t(`alerts.events.stateLabel.${event.state}`)}</span></td>
                  <td className={tableCell}>{metricLabel(event.metric_name, t)}</td>
                  <td className={`${tableCell} font-mono`}>{event.state === 'NO_DATA' ? '—' : formatRuleValue(event.metric_name, event.value)}</td>
                  <td className={`${tableCell} font-mono`}>{formatRuleValue(event.metric_name, event.threshold)}</td>
                  <td className={`${tableCell} font-mono text-slate-400`}>{dateTime(event.triggered_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

/** Deliveries to the channels of one server, and those waiting for another attempt. */
export function DeliveryHistory({ serverId, groupOfServer, rules }: {
  serverId: string
  groupOfServer: number | null
  rules: ScopedRule[]
}) {
  const { t } = useTranslation()
  const { data: records, isLoading } = useNotificationHistory(serverId)
  const { data: retries } = useRetries(serverId)
  const channels = useChannelsAt(placesReaching({ scope: 'server', server_id: serverId }, groupOfServer))
    .flatMap((r) => r.data ?? [])
  const channelById = new Map(channels.map((c) => [c.channel_id, c]))
  const ruleById = new Map(rules.map((r) => [r.rule_id, r]))

  return (
    <section className={sectionCard} aria-labelledby="deliveries-title">
      <h3 id="deliveries-title" className="font-bold text-slate-100">{t('alerts.screen.deliveries.title')}</h3>
      <p className="mt-0.5 text-xs text-slate-400">{t('alerts.screen.deliveries.desc')}</p>
      {retries?.map((retry) => {
        const channel = channelById.get(retry.channel_id)
        return (
          <div key={retry.retry_id} role="status" className="mt-3 rounded-[10px] border border-yellow-400/30 bg-yellow-400/5 px-3.5 py-2.5 text-[13px] text-yellow-100">
            <b>{t('alerts.screen.deliveries.waiting')}</b>
            {' · '}{channel ? t(`alerts.channels.type.${channel.channel_type}`) : t('alerts.history.removedChannel')}
            {' · '}{t('alerts.screen.deliveries.attempt', { next: retry.attempts + 1, max: retry.max_attempts, time: clockTime(retry.next_attempt_at) })}
            {' · '}{t('alerts.screen.deliveries.lastError')} <span className="font-mono">{retry.last_error}</span>
          </div>
        )
      })}
      {isLoading ? <Loading text={t('common.loading')} /> : !records?.length ? (
        <p className="mt-3 text-sm text-slate-400">{t('alerts.history.empty')}</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th className={tableHead}>{t('alerts.history.time')}</th>
                <th className={tableHead}>{t('alerts.history.channel')}</th>
                <th className={tableHead}>{t('alerts.screen.col.what')}</th>
                <th className={tableHead}>{t('alerts.history.result')}</th>
              </tr>
            </thead>
            <tbody>
              {records.map((record, index) => {
                const channel = channelById.get(record.channel_id)
                const rule = record.rule_id ? ruleById.get(record.rule_id) : undefined
                const Icon = CHANNEL_ICON[record.channel_type]
                return (
                  <tr key={`${record.channel_id}-${record.sent_at}-${record.kind}-${index}`}>
                    <td className={`${tableCell} font-mono text-slate-400 whitespace-nowrap`}>{dateTime(record.sent_at)}</td>
                    <td className={tableCell}>
                      <span className="flex items-center gap-1.5">
                        {Icon && <Icon className="w-3.5 h-3.5 text-violet-300 shrink-0" aria-hidden />}
                        {t(`alerts.channels.type.${record.channel_type}`)}
                        <span className="text-slate-400 font-mono truncate max-w-[14rem]">
                          {channel ? channelTarget(channel, t) : t('alerts.history.removedChannel')}
                        </span>
                      </span>
                    </td>
                    <td className={tableCell}>
                      {t(`alerts.history.kindLabel.${record.kind}`)}
                      {rule && <span className="text-slate-400"> · {metricLabel(rule.metric_name, t)}</span>}
                    </td>
                    <td className={tableCell}>
                      {record.ok
                        ? <span className={pill.server}>{t('alerts.history.sent')}</span>
                        : <span className={pill.critical}>{t('alerts.history.failed', { error: record.error })}</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
