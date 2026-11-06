import { useDeferredValue, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { KeyRound, Pencil, Plus, Power } from 'lucide-react'
import type { AccountUser } from '../../services/api'
import { useReactivateAccount } from '../../hooks/useUsers'
import { relativeTime } from '../../utils/format'
import RoleBadge from './RoleBadge'
import {
  DeactivateDialog, EditAccountDialog, NewAccountDialog, PasswordShownDialog, TemporaryPasswordDialog,
} from './AccountDialogs'
import { apiErrorMessage, buttonGhost, buttonPrimary, fieldClass, iconButton } from './ui'

type StatusFilter = 'all' | 'active' | 'inactive'

type OpenDialog =
  | { kind: 'new' }
  | { kind: 'edit' | 'deactivate' | 'temporary'; user: AccountUser }
  | { kind: 'password'; title: string; password: string }

interface AccountsPanelProps {
  users: AccountUser[]
  selfId: number | null
  onOpenProfile: () => void
}

const formatDate = (iso: string, language: string) =>
  new Date(iso).toLocaleDateString(language, { day: '2-digit', month: '2-digit', year: 'numeric' })

const matches = (user: AccountUser, search: string) =>
  [user.full_name ?? '', user.username, user.email].some((value) => value.toLowerCase().includes(search))

export default function AccountsPanel({ users, selfId, onOpenProfile }: AccountsPanelProps) {
  const { t, i18n } = useTranslation()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<StatusFilter>('all')
  const [dialog, setDialog] = useState<OpenDialog | null>(null)
  const reactivate = useReactivateAccount()
  const deferredSearch = useDeferredValue(search.trim().toLowerCase())

  const shown = users
    .filter((user) => status === 'all' || (status === 'active') === user.active)
    .filter((user) => deferredSearch === '' || matches(user, deferredSearch))
    // Active first, then by name.
    .sort((a, b) => Number(b.active) - Number(a.active) || (a.full_name || a.username).localeCompare(b.full_name || b.username))

  const close = () => setDialog(null)

  return (
    <section id="panel-users" role="tabpanel" aria-labelledby="tab-users" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="search"
          className={`${fieldClass} max-w-xs`}
          placeholder={t('users.list.search')}
          aria-label={t('users.list.search')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          className={`${fieldClass} max-w-[180px]`}
          aria-label={t('users.list.statusFilter')}
          value={status}
          onChange={(e) => setStatus(e.target.value as StatusFilter)}
        >
          <option value="active">{t('users.list.onlyActive')}</option>
          <option value="all">{t('users.list.all')}</option>
          <option value="inactive">{t('users.list.onlyInactive')}</option>
        </select>
        <div className="flex-1" />
        <button type="button" className={buttonPrimary} onClick={() => setDialog({ kind: 'new' })}>
          <Plus size={14} aria-hidden="true" />
          {t('users.list.new')}
        </button>
      </div>

      {reactivate.error && <p role="alert" className="text-xs text-red-300">{apiErrorMessage(reactivate.error, t)}</p>}

      <div className="glass-card overflow-x-auto hover:!shadow-none">
        <table className="w-full text-left">
          <thead className="text-[10px] text-slate-400 uppercase tracking-widest bg-brand-dark/40">
            <tr>
              <th className="px-4 py-2.5 font-bold">{t('users.list.person')}</th>
              <th className="px-4 py-2.5 font-bold">{t('users.fields.role')}</th>
              <th className="px-4 py-2.5 font-bold">{t('users.list.status')}</th>
              <th className="px-4 py-2.5 font-bold hidden md:table-cell">{t('users.list.lastAccess')}</th>
              <th className="px-4 py-2.5 font-bold hidden md:table-cell">{t('users.list.createdAt')}</th>
              <th className="px-4 py-2.5 font-bold text-right">{t('users.list.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-sm text-slate-400 border-t border-white/5">{t('users.list.empty')}</td></tr>
            )}
            {shown.map((user) => {
              const isSelf = user.id === selfId
              const name = user.full_name || user.username
              return (
                <tr key={user.id} className={`border-t border-white/5 hover:bg-white/[0.02] ${user.active ? '' : 'text-slate-500'}`}>
                  <td className="px-4 py-3 text-[13px]">
                    <div className="font-semibold flex flex-wrap items-center gap-1.5">
                      {name}
                      {isSelf && <span className="px-2 py-0.5 rounded-md text-[11px] font-normal bg-white/5 text-slate-300">{t('users.list.you')}</span>}
                      {user.active && user.must_change_password && (
                        <span className="px-2 py-0.5 rounded-md text-[11px] font-normal bg-white/5 text-amber-200">{t('users.list.mustChange')}</span>
                      )}
                    </div>
                    <div className={`font-mono text-xs ${user.active ? 'text-slate-400' : ''}`}>{user.username} · {user.email}</div>
                  </td>
                  <td className="px-4 py-3"><RoleBadge role={user.role} muted={!user.active} /></td>
                  <td className="px-4 py-3 text-xs">
                    <span className="inline-flex items-center gap-1.5">
                      <span className={`w-2 h-2 rounded-full ${user.active ? 'bg-green-400' : 'bg-slate-500'}`} aria-hidden="true" />
                      {user.active
                        ? t('users.list.active')
                        : user.deactivated_at
                          ? t('users.list.deactivatedOn', { date: formatDate(user.deactivated_at, i18n.language) })
                          : t('users.list.inactive')}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-[13px] hidden md:table-cell">
                    {user.last_seen_at
                      ? <span title={new Date(user.last_seen_at).toLocaleString(i18n.language)}>{relativeTime(user.last_seen_at, t)}</span>
                      : <span className="text-slate-400">{t('users.list.neverLoggedIn')}</span>}
                  </td>
                  <td className="px-4 py-3 text-[13px] font-mono text-slate-400 hidden md:table-cell">{formatDate(user.created_at, i18n.language)}</td>
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    {isSelf ? (
                      <button type="button" onClick={onOpenProfile} className="text-xs text-slate-400 hover:text-violet-300 underline-offset-2 hover:underline">
                        {t('users.list.editInProfile')}
                      </button>
                    ) : user.active ? (
                      <>
                        <button type="button" className={iconButton} title={t('users.list.edit')}
                          aria-label={t('users.list.editNamed', { name })} onClick={() => setDialog({ kind: 'edit', user })}>
                          <Pencil size={15} aria-hidden="true" />
                        </button>
                        <button type="button" className={iconButton} title={t('users.list.temporary')}
                          aria-label={t('users.list.temporaryNamed', { name })} onClick={() => setDialog({ kind: 'temporary', user })}>
                          <KeyRound size={15} aria-hidden="true" />
                        </button>
                        <button type="button" className={`${iconButton} hover:!text-red-300`} title={t('users.list.deactivate')}
                          aria-label={t('users.list.deactivateNamed', { name })} onClick={() => setDialog({ kind: 'deactivate', user })}>
                          <Power size={15} aria-hidden="true" />
                        </button>
                      </>
                    ) : (
                      <button type="button" className={`${buttonGhost} min-h-8 py-1.5`}
                        disabled={reactivate.isPending && reactivate.variables === user.id}
                        aria-label={t('users.list.reactivateNamed', { name })}
                        onClick={() => reactivate.mutate(user.id)}>
                        {t('users.list.reactivate')}
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-slate-400 leading-relaxed">{t('users.list.footnote')}</p>

      {dialog?.kind === 'new' && (
        <NewAccountDialog
          onClose={close}
          onCreated={(user, password) => setDialog({
            kind: 'password', title: t('users.password.titleNew', { name: user.full_name || user.username }), password,
          })}
        />
      )}
      {dialog?.kind === 'edit' && <EditAccountDialog user={dialog.user} onClose={close} />}
      {dialog?.kind === 'deactivate' && <DeactivateDialog user={dialog.user} onClose={close} />}
      {dialog?.kind === 'temporary' && (
        <TemporaryPasswordDialog
          user={dialog.user}
          onClose={close}
          onGenerated={(password) => setDialog({ kind: 'password', title: t('users.password.title'), password })}
        />
      )}
      {dialog?.kind === 'password' && <PasswordShownDialog title={dialog.title} password={dialog.password} onClose={close} />}
    </section>
  )
}
