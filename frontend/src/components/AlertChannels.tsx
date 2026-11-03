import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BellRing, CheckCircle, Loader2, Plus, Send, Trash2, XCircle } from 'lucide-react'
import {
  useAddChannel, useAlertChannels, useChannelTypes, useDeleteChannel, useTestChannel,
} from '../hooks/useAlertChannels'
import type { AlertChannel, AlertRule, ChannelType, DeliveryResult } from '../services/api'
import { CHANNEL_ICON, channelTarget, ruleLabel } from '../utils/channels'

const INPUT_CLS = 'bg-brand-slate border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-brand-purple/50 transition-all'

/** The config field each type asks for, and whether it may stay empty. */
const CONFIG_FIELD: Record<ChannelType, { key: string; label: string; input: 'text' | 'url' | 'email'; optional: boolean }> = {
  telegram: { key: 'chat_id', label: 'alerts.channels.field.chatId', input: 'text', optional: true },
  webhook: { key: 'url', label: 'alerts.channels.field.url', input: 'url', optional: false },
  slack: { key: 'webhook_url', label: 'alerts.channels.field.slackUrl', input: 'url', optional: false },
  email: { key: 'to', label: 'alerts.channels.field.email', input: 'email', optional: false },
}

// ── New channel form ──────────────────────────────────────────────────────────

function ChannelForm({
  serverId, rules, types, onClose,
}: {
  serverId: string
  rules: AlertRule[]
  types: ChannelType[]
  onClose: () => void
}) {
  const { t } = useTranslation()
  const add = useAddChannel(serverId)
  const [channelType, setChannelType] = useState<ChannelType>(types[0])
  const [value, setValue] = useState('')
  const [ruleId, setRuleId] = useState<string>('')
  const field = CONFIG_FIELD[channelType]

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const config = value.trim() ? { [field.key]: value.trim() } : {}
    add.mutate({ channel_type: channelType, config, rule_id: ruleId || null }, { onSuccess: onClose })
  }

  const label = (text: string, node: React.ReactNode, hint?: string) => (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] text-slate-400 uppercase tracking-widest font-bold">{text}</span>
      {node}
      {hint && <span className="text-[11px] text-slate-500">{hint}</span>}
    </label>
  )

  return (
    <form onSubmit={handleSubmit} className="glass-card p-5 space-y-4">
      <h3 className="text-sm font-bold text-slate-200">{t('alerts.channels.adding')}</h3>
      <div className="grid gap-4 sm:grid-cols-2">
        {label(t('alerts.channels.field.type'),
          <select
            value={channelType}
            onChange={(e) => { setChannelType(e.target.value as ChannelType); setValue('') }}
            className={INPUT_CLS}
          >
            {types.map((type) => <option key={type} value={type}>{t(`alerts.channels.type.${type}`)}</option>)}
          </select>,
        )}
        {label(t('alerts.channels.scopeLabel'),
          <select value={ruleId} onChange={(e) => setRuleId(e.target.value)} className={INPUT_CLS}>
            <option value="">{t('alerts.channels.scopeAll')}</option>
            {rules.map((rule) => (
              <option key={rule.rule_id} value={rule.rule_id}>
                {t('alerts.channels.scopeRule', { rule: ruleLabel(rule, t) })}
              </option>
            ))}
          </select>,
        )}
      </div>
      {label(t(field.label),
        <input
          type={field.input}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          required={!field.optional}
          className={`${INPUT_CLS} font-mono`}
        />,
        channelType === 'telegram' ? t('alerts.channels.field.chatIdHint') : undefined,
      )}
      {add.isError && <p className="text-xs text-red-400">{t('alerts.channels.errorAdd')}</p>}
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onClose} className="px-3 py-2 text-xs font-bold text-slate-400 hover:text-white">
          {t('alerts.channels.cancel')}
        </button>
        <button
          type="submit"
          disabled={add.isPending}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-purple hover:bg-brand-purple/80 text-white text-sm font-bold transition-all disabled:opacity-50"
        >
          {add.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
          {t('alerts.channels.add')}
        </button>
      </div>
    </form>
  )
}

// ── One channel ───────────────────────────────────────────────────────────────

function ChannelRow({ serverId, channel, rules }: { serverId: string; channel: AlertChannel; rules: AlertRule[] }) {
  const { t } = useTranslation()
  const test = useTestChannel(serverId)
  const remove = useDeleteChannel(serverId)
  const [result, setResult] = useState<DeliveryResult | null>(null)
  const Icon = CHANNEL_ICON[channel.channel_type] ?? BellRing
  const rule = channel.rule_id ? rules.find((r) => r.rule_id === channel.rule_id) : undefined
  const scope = channel.rule_id
    ? t('alerts.channels.scopeRule', { rule: rule ? ruleLabel(rule, t) : '—' })
    : t('alerts.channels.scopeAll')

  const handleTest = () => {
    setResult(null)
    test.mutate(channel.channel_id, { onSuccess: setResult })
  }

  const handleRemove = () => {
    if (window.confirm(t('alerts.channels.confirmRemove'))) remove.mutate(channel.channel_id)
  }

  return (
    <li className="px-4 py-3 flex flex-wrap items-center gap-x-4 gap-y-2">
      <Icon className="w-4 h-4 text-brand-purple shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-bold text-slate-200">{t(`alerts.channels.type.${channel.channel_type}`)}</p>
        <p className="text-[11px] text-slate-500 font-mono truncate">{channelTarget(channel, t)}</p>
        <p className="text-[11px] text-slate-400">{scope}</p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {result && (
          <span className={`flex items-center gap-1 text-[11px] ${result.ok ? 'text-brand-neon' : 'text-red-400'}`} role="status">
            {result.ok ? <CheckCircle className="w-3.5 h-3.5" /> : <XCircle className="w-3.5 h-3.5" />}
            {result.ok ? t('alerts.channels.testOk') : t('alerts.channels.testFailed', { error: result.error })}
          </span>
        )}
        <button
          onClick={handleTest}
          disabled={test.isPending}
          className="flex items-center gap-1.5 text-xs font-bold text-slate-200 bg-white/5 border border-white/10 px-3 py-1.5 rounded-lg hover:bg-white/10 transition-all disabled:opacity-50"
        >
          {test.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
          {t('alerts.channels.test')}
        </button>
        <button
          onClick={handleRemove}
          disabled={remove.isPending}
          className="p-1.5 text-slate-500 hover:text-red-400 transition-colors"
          title={t('alerts.channels.remove')}
          aria-label={t('alerts.channels.remove')}
        >
          {remove.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
        </button>
      </div>
    </li>
  )
}

// ── Section ───────────────────────────────────────────────────────────────────

export default function AlertChannels({ serverId, rules }: { serverId: string; rules: AlertRule[] }) {
  const { t } = useTranslation()
  const { data: channels, isLoading } = useAlertChannels(serverId)
  const { data: typesData } = useChannelTypes()
  const [adding, setAdding] = useState(false)
  const types = typesData?.types ?? []

  return (
    <section>
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm font-bold text-slate-400 uppercase tracking-widest flex items-center gap-2">
          <BellRing className="w-4 h-4 text-brand-purple" />
          {t('alerts.channels.title')}
        </h2>
        {!adding && types.length > 0 && (
          <button
            onClick={() => setAdding(true)}
            className="flex items-center gap-2 text-xs font-bold text-brand-purple bg-brand-purple/10 border border-brand-purple/20 px-3 py-1.5 rounded-lg hover:bg-brand-purple/20 transition-all"
          >
            <Plus className="w-3.5 h-3.5" />
            {t('alerts.channels.add')}
          </button>
        )}
      </div>
      <p className="text-xs text-slate-400 mb-4">{t('alerts.channels.desc')}</p>

      <div className="space-y-3">
        {adding && (
          <ChannelForm serverId={serverId} rules={rules} types={types} onClose={() => setAdding(false)} />
        )}

        {isLoading ? (
          <div className="flex items-center gap-2 text-slate-500 text-sm">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span>{t('common.loading')}</span>
          </div>
        ) : !channels?.length ? (
          <div className="glass-card p-5 flex items-center gap-3 border-l-2 border-l-amber-500">
            <BellRing className="w-4 h-4 text-amber-400 shrink-0" />
            <p className="text-sm text-slate-300">{t('alerts.channels.empty')}</p>
          </div>
        ) : (
          <ul className="glass-card divide-y divide-white/5">
            {channels.map((channel) => (
              <ChannelRow key={channel.channel_id} serverId={serverId} channel={channel} rules={rules} />
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}
