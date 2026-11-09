import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, X } from 'lucide-react'
import Dialog from '../users/Dialog'
import {
  useAllRules, useClearNickname, useCreateGroup, useDeleteGroup, useSetNickname, useUpdateServer,
} from '../../hooks/useAlerting'
import { serverName } from '../../hooks/useServerName'
import type { ServerGroup } from '../../services/alertingApi'
import type { ServerStatus } from '../../types/server'
import { ServerName } from '../primitives'
import {
  alertingError, buttonDanger, buttonGhost, buttonPrimary, fieldClass, hintClass, labelClass, pill, sectionCard, smallButton,
  tableCell, tableHead,
} from './ui'

const NAME_MAX = 60

function NameDialog({ title, desc, label, hint, initial, removable, onSave, onRemove, onClose, saving, error }: {
  title: string
  desc: string
  label: string
  hint: string
  initial: string
  removable: boolean
  onSave: (value: string) => void
  onRemove?: () => void
  onClose: () => void
  saving: boolean
  error: unknown
}) {
  const { t } = useTranslation()
  const [value, setValue] = useState(initial)
  return (
    <Dialog
      title={title}
      onClose={onClose}
      dismissible={!saving}
      footer={(
        <>
          {removable && onRemove && (
            <button type="button" className={`${buttonDanger} mr-auto`} disabled={saving} onClick={onRemove}>
              {t('alerts.screen.servers.removeNickname')}
            </button>
          )}
          <button type="button" className={buttonGhost} onClick={onClose} disabled={saving}>{t('common.cancel')}</button>
          <button type="submit" form="name-form" className={buttonPrimary} disabled={saving}>
            {saving && <Loader2 className="w-4 h-4 animate-spin" aria-hidden />}{t('common.save')}
          </button>
        </>
      )}
    >
      <form id="name-form" onSubmit={(e) => { e.preventDefault(); onSave(value.trim()) }}>
        <p className="text-xs text-slate-400 leading-relaxed mb-3">{desc}</p>
        <label className={labelClass} htmlFor="name-value">{label}</label>
        <input id="name-value" className={fieldClass} maxLength={NAME_MAX} value={value} onChange={(e) => setValue(e.target.value)}
          aria-describedby="name-hint" />
        <p id="name-hint" className={hintClass}>{hint}</p>
        {!!error && <p role="alert" className="mt-2 text-xs text-red-300">{alertingError(error, t)}</p>}
      </form>
    </Dialog>
  )
}

function GroupDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const create = useCreateGroup()
  const [name, setName] = useState('')
  return (
    <Dialog
      title={t('alerts.screen.servers.newGroup')}
      onClose={onClose}
      dismissible={!create.isPending}
      footer={(
        <>
          <button type="button" className={buttonGhost} onClick={onClose} disabled={create.isPending}>{t('common.cancel')}</button>
          <button type="submit" form="group-form" className={buttonPrimary} disabled={create.isPending || !name.trim()}>
            {create.isPending && <Loader2 className="w-4 h-4 animate-spin" aria-hidden />}{t('common.save')}
          </button>
        </>
      )}
    >
      <form id="group-form" onSubmit={(e) => { e.preventDefault(); create.mutate(name.trim(), { onSuccess: onClose }) }}>
        <label className={labelClass} htmlFor="group-name">{t('alerts.screen.servers.groupName')}</label>
        <input id="group-name" className={fieldClass} maxLength={NAME_MAX} required value={name} onChange={(e) => setName(e.target.value)} />
        <p className={hintClass}>{t('alerts.screen.servers.groupHint')}</p>
        {create.isError && <p role="alert" className="mt-2 text-xs text-red-300">{alertingError(create.error, t)}</p>}
      </form>
    </Dialog>
  )
}

type Editing = { kind: 'nickname' | 'label'; server: ServerStatus } | { kind: 'group' } | null

export default function ServersTab({ servers, groups, canManageServers }: {
  servers: ServerStatus[]
  groups: ServerGroup[]
  canManageServers: boolean
}) {
  const { t } = useTranslation()
  const { data: rules = [] } = useAllRules()
  const updateServer = useUpdateServer()
  const setNickname = useSetNickname()
  const clearNickname = useClearNickname()
  const deleteGroup = useDeleteGroup()
  const [editing, setEditing] = useState<Editing>(null)
  const close = () => { setEditing(null); setNickname.reset(); clearNickname.reset(); updateServer.reset() }
  const example = servers.find((s) => s.label) ?? servers[0]

  return (
    <div className="flex flex-col gap-4">
      <section className={sectionCard} aria-labelledby="names-title">
        <h3 id="names-title" className="font-bold text-slate-100">{t('alerts.screen.servers.howTitle')}</h3>
        <ol className="mt-2 pl-5 list-decimal text-xs text-slate-400 leading-relaxed space-y-0.5">
          <li><b className="text-slate-200">{t('alerts.screen.servers.nickname')}</b>: {t('alerts.screen.servers.howNickname')}</li>
          <li><b className="text-slate-200">{t('alerts.screen.servers.label')}</b>: {t('alerts.screen.servers.howLabel')}</li>
          <li><b className="text-slate-200">{t('alerts.screen.servers.hostname')}</b>: {t('alerts.screen.servers.howHostname')}</li>
        </ol>
        {example && (
          <div className="mt-3 rounded-[10px] border border-white/10 bg-slate-800/40 px-3.5 py-2.5 text-[13px]">
            <span className="block mb-1.5 text-[10px] text-slate-400 uppercase tracking-widest font-bold">{t('alerts.screen.servers.telegramExample')}</span>
            {t('alerts.screen.servers.telegramLine', {
              server: example.label ? `${example.label} (${example.server_id})` : example.server_id,
            })}
          </div>
        )}
      </section>

      <div className="glass-card overflow-x-auto">
        <table className="w-full">
          <caption className="sr-only">{t('alerts.screen.servers.caption')}</caption>
          <thead>
            <tr>
              <th className={tableHead}>{t('alerts.screen.col.server')}</th>
              <th className={tableHead}>{t('alerts.screen.servers.label')} <span className="normal-case tracking-normal">({t('alerts.screen.servers.admin')})</span></th>
              <th className={tableHead}>{t('alerts.screen.servers.group')} <span className="normal-case tracking-normal">({t('alerts.screen.servers.admin')})</span></th>
              <th className={tableHead}>{t('alerts.screen.servers.yourNickname')}</th>
            </tr>
          </thead>
          <tbody>
            {servers.map((server) => (
              <tr key={server.server_id}>
                <td className={tableCell}><ServerName name={serverName(server)} /></td>
                <td className={tableCell}>
                  {canManageServers ? (
                    <button type="button" className={`${buttonGhost} ${smallButton}`} onClick={() => setEditing({ kind: 'label', server })}>
                      {server.label ?? t('alerts.screen.servers.giveLabel')} <span aria-hidden>✎</span>
                    </button>
                  ) : (server.label ?? '—')}
                </td>
                <td className={tableCell}>
                  {canManageServers ? (
                    <select
                      className={`${fieldClass} w-auto py-1.5`}
                      aria-label={t('alerts.screen.servers.groupOf', { server: server.server_id })}
                      value={server.group_id ?? ''}
                      disabled={updateServer.isPending}
                      onChange={(e) => updateServer.mutate({
                        serverId: server.server_id, changes: { group_id: e.target.value ? Number(e.target.value) : null },
                      })}
                    >
                      {groups.map((g) => <option key={g.group_id} value={g.group_id}>{g.name}</option>)}
                      <option value="">{t('alerts.screen.servers.noGroup')}</option>
                    </select>
                  ) : (server.group_name ?? '—')}
                </td>
                <td className={tableCell}>
                  <button type="button" className={`${buttonGhost} ${smallButton}`} onClick={() => setEditing({ kind: 'nickname', server })}>
                    {server.nickname ?? `+ ${t('alerts.screen.servers.giveNickname')}`} {server.nickname && <span aria-hidden>✎</span>}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {updateServer.isError && !editing && <p role="alert" className="px-4 py-2 text-xs text-red-300">{alertingError(updateServer.error, t)}</p>}
      </div>

      <section className={sectionCard} aria-labelledby="groups-title">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 id="groups-title" className="font-bold text-slate-100">{t('alerts.screen.servers.groups')}</h3>
            <p className="mt-0.5 text-xs text-slate-400">{t('alerts.screen.servers.groupsDesc')}</p>
          </div>
          {canManageServers && <button type="button" className={buttonGhost} onClick={() => setEditing({ kind: 'group' })}>+ {t('alerts.screen.servers.group')}</button>}
        </div>
        {groups.length === 0 ? (
          <p className="mt-3 text-sm text-slate-400">{t('alerts.screen.servers.noGroups')}</p>
        ) : (
          <ul className="mt-3 flex flex-wrap gap-1.5">
            {groups.map((g) => {
              const members = servers.filter((s) => s.group_id === g.group_id).length
              const groupRules = rules.filter((r) => r.scope === 'group' && r.group_id === g.group_id).length
              const parts = [
                g.name,
                members ? t('alerts.screen.servers.members', { count: members }) : t('alerts.screen.servers.empty'),
                ...(groupRules ? [t('alerts.screen.servers.rulesCount', { count: groupRules })] : []),
              ]
              return (
                <li key={g.group_id} className={pill.group}>
                  {parts.join(' · ')}
                  {canManageServers && (
                    <button type="button" className="ml-0.5 rounded hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet-400"
                      aria-label={t('alerts.screen.servers.deleteGroup', { name: g.name })} disabled={deleteGroup.isPending}
                      onClick={() => { if (window.confirm(t('alerts.screen.servers.confirmDeleteGroup', { name: g.name }))) deleteGroup.mutate(g.group_id) }}>
                      <X className="w-3 h-3" aria-hidden />
                    </button>
                  )}
                </li>
              )
            })}
          </ul>
        )}
        {deleteGroup.isError && <p role="alert" className="mt-2 text-xs text-red-300">{alertingError(deleteGroup.error, t)}</p>}
      </section>

      {editing?.kind === 'nickname' && (
        <NameDialog
          title={t('alerts.screen.servers.nicknameTitle', { server: editing.server.server_id })}
          desc={t('alerts.screen.servers.nicknameDesc', { label: editing.server.label ?? editing.server.server_id })}
          label={t('alerts.screen.servers.nickname')}
          hint={t('alerts.screen.servers.nicknameHint')}
          initial={editing.server.nickname ?? ''}
          removable={!!editing.server.nickname}
          saving={setNickname.isPending || clearNickname.isPending}
          error={setNickname.error ?? clearNickname.error}
          onSave={(value) => (value
            ? setNickname.mutate({ serverId: editing.server.server_id, nickname: value }, { onSuccess: close })
            : clearNickname.mutate(editing.server.server_id, { onSuccess: close }))}
          onRemove={() => clearNickname.mutate(editing.server.server_id, { onSuccess: close })}
          onClose={close}
        />
      )}
      {editing?.kind === 'label' && (
        <NameDialog
          title={t('alerts.screen.servers.labelTitle', { server: editing.server.server_id })}
          desc={t('alerts.screen.servers.labelDesc')}
          label={t('alerts.screen.servers.label')}
          hint={t('alerts.screen.servers.labelHint')}
          initial={editing.server.label ?? ''}
          removable={false}
          saving={updateServer.isPending}
          error={updateServer.error}
          onSave={(value) => updateServer.mutate({ serverId: editing.server.server_id, changes: { label: value || null } }, { onSuccess: close })}
          onClose={close}
        />
      )}
      {editing?.kind === 'group' && <GroupDialog onClose={() => setEditing(null)} />}
    </div>
  )
}
