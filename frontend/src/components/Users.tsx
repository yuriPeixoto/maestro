import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import Layout from './Layout'
import type { ViewType } from '../App'
import { useMe, usePermissions } from '../hooks/usePermissions'
import { useAccounts } from '../hooks/useUsers'
import AccountsPanel from './users/AccountsPanel'
import AuditPanel from './users/AuditPanel'
import RolesPanel from './users/RolesPanel'

interface UsersProps {
  setView: (view: ViewType) => void
}

type Tab = 'users' | 'audit' | 'roles'

const tabClass = (selected: boolean) =>
  `px-4 py-2 rounded-full text-[13px] font-semibold border transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-400 ${selected
    ? 'bg-brand-purple/15 text-violet-300 border-brand-purple/40'
    : 'text-slate-400 border-white/10 hover:text-slate-100'
  }`

/** Accounts, audit log and the roles matrix: each tab only for the permission it needs. */
export default function Users({ setView }: UsersProps) {
  const { t } = useTranslation()
  const { data: me } = useMe()
  const { can } = usePermissions()
  const manageUsers = can('users.manage')
  const viewAudit = can('audit.view')
  const accounts = useAccounts(manageUsers || viewAudit)

  const tabs: Tab[] = [
    ...(manageUsers ? ['users' as const] : []),
    ...(viewAudit ? ['audit' as const] : []),
    ...(manageUsers ? ['roles' as const] : []),
  ]
  const [chosen, setChosen] = useState<Tab | null>(null)
  const tab = chosen && tabs.includes(chosen) ? chosen : tabs[0]

  // Arrow keys move between tabs, as in any tablist.
  const handleTabKey = (event: React.KeyboardEvent) => {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    if (step === 0) return
    const next = tabs[(tabs.indexOf(tab) + step + tabs.length) % tabs.length]
    setChosen(next)
    document.getElementById(`tab-${next}`)?.focus()
  }

  return (
    <Layout currentView="users" setView={setView} title={t('nav.users')}>
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-[22px] font-bold mb-1">{t('users.title')}</h1>
            <p className="text-[13px] text-slate-400">{t('users.subtitle')}</p>
          </div>
          {tabs.length > 0 && (
            <div role="tablist" aria-label={t('users.sections')} className="flex gap-2" onKeyDown={handleTabKey}>
              {tabs.map((id) => (
                <button
                  key={id}
                  id={`tab-${id}`}
                  type="button"
                  role="tab"
                  aria-selected={tab === id}
                  aria-controls={`panel-${id}`}
                  tabIndex={tab === id ? 0 : -1}
                  className={tabClass(tab === id)}
                  onClick={() => setChosen(id)}
                >
                  {t(`users.tabs.${id}`)}
                  {id === 'users' && accounts.data && (
                    <span className="ml-1.5 font-mono opacity-70">{accounts.data.length}</span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>

        {tabs.length === 0 && (
          <p className="glass-card p-6 text-sm text-slate-400">{t('users.noAccess')}</p>
        )}
        {accounts.isError && <p role="alert" className="text-sm text-red-300">{t('users.loadError')}</p>}
        {tab === 'users' && accounts.data && (
          <AccountsPanel users={accounts.data} selfId={me?.id ?? null} onOpenProfile={() => setView('profile')} />
        )}
        {tab === 'audit' && <AuditPanel users={accounts.data ?? []} />}
        {tab === 'roles' && <RolesPanel />}
      </div>
    </Layout>
  )
}
