import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BellRing, CheckCircle, Loader2, XCircle } from 'lucide-react'
import Dialog from '../users/Dialog'
import Segmented from './Segmented'
import { useChannelTypes } from '../../hooks/useAlertChannels'
import {
  useChannelsAt, useCreateChannel, useDeleteChannel, useMoveChannel, useTestChannel,
} from '../../hooks/useAlerting'
import type { Place, Scope, ScopedChannel, ScopedRule, ServerGroup } from '../../services/alertingApi'
import type { ChannelType, DeliveryResult } from '../../services/api'
import { CHANNEL_ICON, CONFIG_FIELD, channelTarget } from '../../utils/channels'
import {
  GLOBAL, alertingError, buttonDanger, buttonGhost, buttonPrimary, fieldClass, hintClass, labelClass, placeKey, placeLabel,
  placesReaching, ruleName, scopePill, sectionCard, smallButton, tableCell, tableHead,
} from './ui'

function ChannelDialog({ place, groupOfServer, rules, groups, onClose }: {
  place: Place
  groupOfServer: number | null
  rules: ScopedRule[]
  groups: ServerGroup[]
  onClose: () => void
}) {
  const { t } = useTranslation()
  const { data: typesData } = useChannelTypes()
  const types = typesData?.types ?? []
  const create = useCreateChannel()
  const [scope, setScope] = useState<Scope>(place.scope)
  const [channelType, setChannelType] = useState<ChannelType | null>(null)
  const [value, setValue] = useState('')
  const [ruleId, setRuleId] = useState('')
  const type = channelType ?? types[0]
  const field = type ? CONFIG_FIELD[type] : null

  const ownGroup = place.scope === 'group' ? place.group_id : groupOfServer
  const groupName = groups.find((g) => g.group_id === ownGroup)?.name ?? '—'
  const options = [
    { value: 'global' as const, label: t('alerts.screen.place.global') },
    ...(place.scope === 'group' || (place.scope === 'server' && groupOfServer !== null)
      ? [{ value: 'group' as const, label: t('alerts.screen.place.group', { name: groupName }) }] : []),
    ...(place.scope === 'server' ? [{ value: 'server' as const, label: t('alerts.screen.place.thisServer') }] : []),
  ]

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    if (!type || !field) return
    const target: Place = scope === 'global' ? GLOBAL
      : scope === 'group' ? { scope, group_id: place.scope === 'group' ? place.group_id : groupOfServer }
        : place
    create.mutate({
      ...target, channel_type: type, config: value.trim() ? { [field.key]: value.trim() } : {}, rule_id: ruleId || null,
    }, { onSuccess: onClose })
  }

  return (
    <Dialog
      title={t('alerts.screen.channels.newTitle')}
      onClose={onClose}
      dismissible={!create.isPending}
      footer={(
        <>
          <button type="button" className={buttonGhost} onClick={onClose} disabled={create.isPending}>{t('common.cancel')}</button>
          <button type="submit" form="channel-form" className={buttonPrimary} disabled={create.isPending || !type}>
            {create.isPending && <Loader2 className="w-4 h-4 animate-spin" aria-hidden />}{t('alerts.channels.add')}
          </button>
        </>
      )}
    >
      <form id="channel-form" onSubmit={submit}>
        {options.length > 1 && (
          <>
            <span className={labelClass}>{t('alerts.screen.channels.appliesTo')}</span>
            <Segmented label={t('alerts.screen.channels.appliesTo')} options={options} value={scope} onChange={setScope} />
          </>
        )}
        <div className="grid gap-3 sm:grid-cols-2 mt-4">
          <div>
            <label className={labelClass} htmlFor="channel-type">{t('alerts.channels.field.type')}</label>
            <select id="channel-type" className={fieldClass} value={type ?? ''}
              onChange={(e) => { setChannelType(e.target.value as ChannelType); setValue('') }}>
              {types.map((ty) => <option key={ty} value={ty}>{t(`alerts.channels.type.${ty}`)}</option>)}
            </select>
          </div>
          <div>
            <label className={labelClass} htmlFor="channel-rule">{t('alerts.channels.scopeLabel')}</label>
            <select id="channel-rule" className={fieldClass} value={ruleId} onChange={(e) => setRuleId(e.target.value)}>
              <option value="">{t('alerts.channels.scopeAll')}</option>
              {rules.map((rule) => <option key={rule.rule_id} value={rule.rule_id}>{ruleName(rule, t)}</option>)}
            </select>
          </div>
        </div>
        {field && (
          <div className="mt-3">
            <label className={labelClass} htmlFor="channel-value">{t(field.label)}</label>
            <input id="channel-value" type={field.input} required={!field.optional} className={`${fieldClass} font-mono`}
              value={value} onChange={(e) => setValue(e.target.value)} />
            {type === 'telegram' && <p className={hintClass}>{t('alerts.channels.field.chatIdHint')}</p>}
          </div>
        )}
        <p className={hintClass}>{t('alerts.screen.channels.addUp')}</p>
        {create.isError && <p role="alert" className="mt-2 text-xs text-red-300">{alertingError(create.error, t)}</p>}
      </form>
    </Dialog>
  )
}

function ChannelRow({ channel, rules, groups, here, canManage }: {
  channel: ScopedChannel
  rules: ScopedRule[]
  groups: ServerGroup[]
  here?: string
  canManage: boolean
}) {
  const { t } = useTranslation()
  const test = useTestChannel()
  const move = useMoveChannel()
  const remove = useDeleteChannel()
  const [result, setResult] = useState<DeliveryResult | null>(null)
  const Icon = CHANNEL_ICON[channel.channel_type] ?? BellRing
  const rule = rules.find((r) => r.rule_id === channel.rule_id)
  const error = test.error ?? move.error ?? remove.error

  return (
    <tr>
      <td className={tableCell}>
        <span className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-violet-300 shrink-0" aria-hidden />
          <span>
            {t(`alerts.channels.type.${channel.channel_type}`)}
            <span className="block text-[11px] text-slate-400 font-mono truncate max-w-[16rem]">{channelTarget(channel, t)}</span>
          </span>
        </span>
      </td>
      <td className={tableCell}><span className={scopePill(channel.scope)}>{placeLabel(channel, t, groups, undefined, here)}</span></td>
      <td className={tableCell}>{channel.rule_id ? (rule ? ruleName(rule, t) : '—') : t('alerts.screen.channels.allRules')}</td>
      <td className={`${tableCell} text-right`}>
        <span className="inline-flex flex-wrap justify-end items-center gap-2">
          {result && (
            <span role="status" className={`inline-flex items-center gap-1 text-[11px] ${result.ok ? 'text-emerald-300' : 'text-red-300'}`}>
              {result.ok ? <CheckCircle className="w-3.5 h-3.5" aria-hidden /> : <XCircle className="w-3.5 h-3.5" aria-hidden />}
              {result.ok ? t('alerts.channels.testOk') : t('alerts.channels.testFailed', { error: result.error })}
            </span>
          )}
          {canManage && (
            <>
              <button type="button" className={`${buttonGhost} ${smallButton}`} disabled={test.isPending}
                onClick={() => { setResult(null); test.mutate(channel.channel_id, { onSuccess: (r) => setResult(r as DeliveryResult) }) }}>
                {test.isPending && <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden />}{t('alerts.channels.test')}
              </button>
              {channel.scope !== 'global' && (
                <button type="button" className={`${buttonGhost} ${smallButton}`} disabled={move.isPending}
                  onClick={() => { if (window.confirm(t('alerts.screen.channels.confirmMove'))) move.mutate({ channelId: channel.channel_id, place: GLOBAL }) }}>
                  {t('alerts.screen.channels.moveToAll')}
                </button>
              )}
              <button type="button" className={`${buttonDanger} ${smallButton}`} disabled={remove.isPending}
                onClick={() => { if (window.confirm(t('alerts.channels.confirmRemove'))) remove.mutate(channel.channel_id) }}>
                {t('alerts.channels.remove')}
              </button>
            </>
          )}
        </span>
        {error && <p role="alert" className="mt-1 text-xs text-red-300">{alertingError(error, t)}</p>}
      </td>
    </tr>
  )
}

/** Where the alerts of a place go. On a server, the channels of every place that reaches it. */
export default function ChannelsCard({ place, groupOfServer, rules, groups, canManage }: {
  place: Place
  groupOfServer: number | null
  rules: ScopedRule[]
  groups: ServerGroup[]
  canManage: boolean
}) {
  const { t } = useTranslation()
  const [adding, setAdding] = useState(false)
  const results = useChannelsAt(placesReaching(place, groupOfServer))
  const loading = results.some((r) => r.isLoading)
  const channels = results.flatMap((r) => r.data ?? [])
  const here = place.scope === 'server' ? place.server_id ?? undefined : undefined
  const onlyLocal = channels.length > 0 && channels.every((c) => c.scope !== 'global')

  return (
    <section className={sectionCard} aria-labelledby={`channels-${placeKey(place)}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 id={`channels-${placeKey(place)}`} className="font-bold text-slate-100">
            {place.scope === 'server' ? t('alerts.screen.channels.titleServer') : t('alerts.screen.channels.titlePlace')}
          </h3>
          <p className="mt-0.5 text-xs text-slate-400">{t('alerts.screen.channels.addUp')}</p>
        </div>
        {canManage && (
          <button type="button" className={buttonGhost} onClick={() => setAdding(true)}>+ {t('alerts.screen.channels.add')}</button>
        )}
      </div>
      {loading ? (
        <p className="mt-3 flex items-center gap-2 text-sm text-slate-400"><Loader2 className="w-4 h-4 animate-spin" aria-hidden />{t('common.loading')}</p>
      ) : channels.length === 0 ? (
        <p className="mt-3 text-sm text-amber-200">{t('alerts.screen.channels.none')}</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th className={tableHead}>{t('alerts.screen.col.channel')}</th>
                <th className={tableHead}>{t('alerts.screen.col.appliesTo')}</th>
                <th className={tableHead}>{t('alerts.screen.col.rules')}</th>
                <th className={tableHead}><span className="sr-only">{t('alerts.screen.col.actions')}</span></th>
              </tr>
            </thead>
            <tbody>
              {channels.map((channel) => (
                <ChannelRow key={channel.channel_id} channel={channel} rules={rules} groups={groups} here={here} canManage={canManage} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {place.scope === 'server' && onlyLocal && <p className={hintClass}>{t('alerts.screen.channels.suggestAll')}</p>}
      {adding && (
        <ChannelDialog place={place} groupOfServer={groupOfServer} rules={rules} groups={groups} onClose={() => setAdding(false)} />
      )}
    </section>
  )
}
