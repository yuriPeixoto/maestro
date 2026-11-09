import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAllRules, useResolvedRules, useRulesAt } from '../../hooks/useAlerting'
import { serverName, useServerName } from '../../hooks/useServerName'
import { useUIStore } from '../../store/uiStore'
import type { Scope, ScopedRule, ServerGroup, Silence } from '../../services/alertingApi'
import type { ServerStatus } from '../../types/server'
import ChannelsCard from './ChannelsCard'
import { DeliveryHistory, EventsHistory } from './Histories'
import OpenAlertsCard from './OpenAlertsCard'
import { OverrideDialog, RuleDialog } from './RuleDialogs'
import { PlaceRules, ServerRules, type RuleActions } from './RulesTable'
import Segmented from './Segmented'
import ServerPicker from './ServerPicker'
import { GLOBAL, buttonPrimary, fieldClass, pill } from './ui'

type Editing = { kind: 'new' } | { kind: 'edit'; rule: ScopedRule } | { kind: 'override'; rule: ScopedRule } | null

function ServerHead({ server }: { server: ServerStatus }) {
  const { t } = useTranslation()
  const name = serverName(server)
  const details = [
    server.server_id,
    server.label && server.label !== name.display ? t('alerts.screen.head.label', { label: server.label }) : null,
    server.group_name ? t('alerts.screen.head.group', { name: server.group_name }) : null,
  ].filter(Boolean).join(' · ')
  const online = server.status === 'online'
  return (
    <div className="glass-card px-5 py-4 flex flex-wrap items-center gap-4">
      <div>
        <div className="text-[17px] font-bold text-slate-100">{name.display}</div>
        <div className="text-xs text-slate-400 font-mono">{details}</div>
      </div>
      <span className={`ml-auto ${online ? pill.server : pill.off}`}>{t(`alerts.screen.head.${server.status}`)}</span>
    </div>
  )
}

export default function RulesTab({ servers, groups, silences, canManage }: {
  servers: ServerStatus[]
  groups: ServerGroup[]
  silences: Silence[]
  canManage: boolean
}) {
  const { t } = useTranslation()
  const nameOf = useServerName()
  const selected = useUIStore((s) => s.selectedAgentId)
  const setSelected = useUIStore((s) => s.setSelectedAgentId)
  const fallback = servers.find((s) => s.status === 'online')?.server_id ?? servers[0]?.server_id ?? ''
  const serverId = servers.some((s) => s.server_id === selected) ? (selected as string) : fallback
  const server = servers.find((s) => s.server_id === serverId)
  const [view, setView] = useState<Scope>('server')
  const [groupId, setGroupId] = useState<number | null>(null)
  const group = groups.find((g) => g.group_id === groupId) ?? groups[0]
  const [editing, setEditing] = useState<Editing>(null)

  const { data: resolved } = useResolvedRules(view === 'server' ? serverId : '')
  const { data: all = [] } = useAllRules()
  const { data: globalRules } = useRulesAt(GLOBAL, view !== 'server')
  const { data: groupRules } = useRulesAt({ scope: 'group', group_id: group?.group_id }, view === 'group' && !!group)

  const actions: RuleActions = {
    canManage,
    onEdit: (rule) => setEditing({ kind: 'edit', rule }),
    onOverride: (rule) => setEditing({ kind: 'override', rule }),
  }
  const serverRules = (resolved ?? []).map((r) => r.rule)
  const placeRules = view === 'server' ? serverRules : view === 'group' ? (groupRules ?? []) : (globalRules ?? [])
  // The rules a channel or a silence may name: what is judged there, and what the place sets.
  const rulesForChannels = view === 'group' ? [...(groupRules ?? []), ...(globalRules ?? [])] : placeRules

  const viewOptions = [
    { value: 'global' as const, label: t('alerts.screen.place.global') },
    ...(groups.length ? [{ value: 'group' as const, label: t('alerts.screen.place.groupTab') }] : []),
    { value: 'server' as const, label: t('alerts.screen.place.serverTab') },
  ]

  return (
    <div className="flex flex-col gap-4">
      <OpenAlertsCard />

      <div className="flex flex-wrap items-center gap-3">
        <Segmented label={t('alerts.screen.rules.whereLabel')} options={viewOptions} value={view} onChange={setView} />
        {view === 'server' && servers.length > 0 && (
          <>
            <ServerPicker servers={servers} value={serverId} onChange={setSelected} />
            <span className="text-xs text-slate-400">{t('alerts.screen.picker.hint')}</span>
          </>
        )}
        {view === 'group' && group && (
          <select aria-label={t('alerts.screen.servers.group')} className={`${fieldClass} w-auto`} value={group.group_id}
            onChange={(e) => setGroupId(Number(e.target.value))}>
            {groups.map((g) => <option key={g.group_id} value={g.group_id}>{g.name}</option>)}
          </select>
        )}
        {canManage && (
          <button type="button" className={`${buttonPrimary} ml-auto`} onClick={() => setEditing({ kind: 'new' })}>
            + {t('alerts.screen.rules.new')}
          </button>
        )}
      </div>

      {view === 'server' && server && (
        <>
          <ServerHead server={server} />
          <ServerRules resolved={resolved} server={server} name={nameOf(serverId)} groups={groups} silences={silences} actions={actions} />
          <ChannelsCard place={{ scope: 'server', server_id: serverId }} groupOfServer={server.group_id} rules={serverRules} groups={groups} canManage={canManage} />
          <EventsHistory serverId={serverId} />
          <DeliveryHistory serverId={serverId} groupOfServer={server.group_id} rules={serverRules} />
        </>
      )}
      {view === 'server' && !server && <p className="text-sm text-slate-400">{t('alerts.screen.noServers')}</p>}

      {view === 'global' && (
        <>
          <PlaceRules rules={globalRules} all={all} broader={[]} groups={groups} nameOf={nameOf} actions={actions}
            caption={t('alerts.screen.rules.captionGlobal')} />
          <ChannelsCard place={GLOBAL} groupOfServer={null} rules={rulesForChannels} groups={groups} canManage={canManage} />
        </>
      )}

      {view === 'group' && group && (
        <>
          <PlaceRules rules={groupRules} all={all} broader={globalRules ?? []} groups={groups} nameOf={nameOf} actions={actions}
            caption={t('alerts.screen.rules.captionGroup', { name: group.name })} />
          <ChannelsCard place={{ scope: 'group', group_id: group.group_id }} groupOfServer={null} rules={rulesForChannels} groups={groups} canManage={canManage} />
        </>
      )}

      {editing?.kind === 'new' && (
        <RuleDialog initialScope={view} initialServer={serverId} initialGroup={group?.group_id ?? null}
          servers={servers} groups={groups} onClose={() => setEditing(null)} />
      )}
      {editing?.kind === 'edit' && (
        <RuleDialog rule={editing.rule} initialScope={editing.rule.scope} servers={servers} groups={groups} onClose={() => setEditing(null)} />
      )}
      {editing?.kind === 'override' && server && (
        <OverrideDialog inherited={editing.rule} serverId={serverId} serverLabel={nameOf(serverId).display}
          groups={groups} onClose={() => setEditing(null)} />
      )}
    </div>
  )
}
