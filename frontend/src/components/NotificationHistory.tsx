import { useTranslation } from 'react-i18next'
import { BellRing, CheckCircle, Clock, Loader2, XCircle } from 'lucide-react'
import { useAlertChannels, useNotificationHistory } from '../hooks/useAlertChannels'
import { CHANNEL_ICON, channelTarget } from '../utils/channels'

export default function NotificationHistory({ serverId }: { serverId: string }) {
  const { t } = useTranslation()
  const { data: records, isLoading } = useNotificationHistory(serverId)
  const { data: channels } = useAlertChannels(serverId)
  const channelById = Object.fromEntries((channels ?? []).map((ch) => [ch.channel_id, ch]))

  const fmtTs = (iso: string) =>
    new Date(iso).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })

  return (
    <section>
      <h2 className="text-sm font-bold text-slate-400 uppercase tracking-widest mb-4">
        {t('alerts.history.title')}
      </h2>

      {isLoading ? (
        <div className="flex items-center gap-2 text-slate-500 text-sm">
          <Loader2 className="w-4 h-4 animate-spin" />
          <span>{t('common.loading')}</span>
        </div>
      ) : !records?.length ? (
        <div className="glass-card p-6 text-center">
          <p className="text-slate-500 text-sm">{t('alerts.history.empty')}</p>
        </div>
      ) : (
        <div className="glass-card overflow-x-auto">
          <table className="w-full text-left">
            <thead className="text-[10px] text-slate-500 uppercase tracking-widest bg-brand-dark/20">
              <tr>
                <th className="px-4 py-2 font-medium">{t('alerts.history.time')}</th>
                <th className="px-4 py-2 font-medium">{t('alerts.history.channel')}</th>
                <th className="px-4 py-2 font-medium">{t('alerts.history.kind')}</th>
                <th className="px-4 py-2 font-medium">{t('alerts.history.result')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {records.map((record) => {
                const channel = channelById[record.channel_id]
                const Icon = CHANNEL_ICON[record.channel_type] ?? BellRing
                return (
                  <tr key={`${record.channel_id}-${record.sent_at}-${record.kind}`} className="hover:bg-white/5 transition-colors">
                    <td className="px-4 py-3 font-mono text-[11px] text-slate-500 whitespace-nowrap">
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {fmtTs(record.sent_at)}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-300">
                      <span className="flex items-center gap-1.5">
                        <Icon className="w-3.5 h-3.5 text-brand-purple shrink-0" aria-hidden />
                        {t(`alerts.channels.type.${record.channel_type}`)}
                        <span className="text-slate-500 font-mono truncate max-w-[16rem]">
                          {channel ? channelTarget(channel, t) : t('alerts.history.removedChannel')}
                        </span>
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-300">{t(`alerts.history.kindLabel.${record.kind}`)}</td>
                    <td className="px-4 py-3 text-xs">
                      {record.ok ? (
                        <span className="flex items-center gap-1 text-brand-neon">
                          <CheckCircle className="w-3.5 h-3.5" />
                          {t('alerts.history.sent')}
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-red-400">
                          <XCircle className="w-3.5 h-3.5 shrink-0" />
                          {t('alerts.history.failed', { error: record.error })}
                        </span>
                      )}
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
