import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { VolumeX } from 'lucide-react'
import Layout from './Layout'
import type { ViewType } from '../App'
import { useServers } from '../hooks/useServers'
import { usePermissions } from '../hooks/usePermissions'
import { useAllRules, useGroups, useMaintenance, useSilences } from '../hooks/useAlerting'
import { useServerName } from '../hooks/useServerName'
import QuietTab from './alerts/QuietTab'
import RulesTab from './alerts/RulesTab'
import ServersTab from './alerts/ServersTab'
import { buttonGhost, clockTime, ruleName, smallButton } from './alerts/ui'
import type { MaintenanceWindow, ScopedRule, ServerGroup, Silence } from '../services/alertingApi'

interface AlertsProps {
  setView: (view: ViewType) => void
}

type Tab = 'rules' | 'quiet' | 'servers'
const TABS: Tab[] = ['rules', 'quiet', 'servers']

/** One line per active silence or maintenance, so nobody wonders why the chat is quiet. */
function QuietBanner({ silences, windows, groups, rules, onShow }: {
  silences: Silence[]
  windows: MaintenanceWindow[]
  groups: ServerGroup[]
  rules: ScopedRule[]
  onShow: () => void
}) {
  const { t } = useTranslation()
  const nameOf = useServerName()
  const activeWindows = windows.filter((w) => w.active)
  const activeSilences = silences.filter((s) => s.active)
  if (!activeWindows.length && !activeSilences.length) return null

  const place = (s: Silence) => {
    if (s.scope === 'global') return t('alerts.screen.place.global')
    if (s.scope === 'group') return t('alerts.screen.place.group', { name: groups.find((g) => g.group_id === s.group_id)?.name ?? '—' })
    return nameOf(s.server_id ?? '').display
  }
  const parts = [
    ...activeWindows.map((w) => t('alerts.screen.banner.maintenance', {
      server: nameOf(w.server_id).display, time: w.next_ends_at ? clockTime(w.next_ends_at) : '—',
    })),
    ...activeSilences.map((s) => {
      const rule = rules.find((r) => r.rule_id === s.rule_id)
      return t('alerts.screen.banner.silence', {
        what: rule ? ruleName(rule, t) : t('alerts.screen.quiet.allRules'), where: place(s),
        time: clockTime(s.ends_at), who: s.created_by, reason: s.reason,
      })
    }),
  ]
  return (
    <div role="status" className="flex flex-wrap items-center gap-3 rounded-[10px] border border-orange-400/30 bg-orange-400/[0.08] px-3.5 py-2.5 text-[13px] text-orange-100">
      <VolumeX className="w-[18px] h-[18px] shrink-0" aria-hidden />
      <span className="flex-1 min-w-0">{parts.join(' · ')}</span>
      <button type="button" className={`${buttonGhost} ${smallButton}`} onClick={onShow}>{t('alerts.screen.banner.show')}</button>
    </div>
  )
}

export default function Alerts({ setView }: AlertsProps) {
  const { t } = useTranslation()
  const { data: servers = [] } = useServers()
  const { data: groups = [] } = useGroups()
  const { data: silences = [] } = useSilences()
  const { data: windows = [] } = useMaintenance()
  const { data: rules = [] } = useAllRules()
  const { can } = usePermissions()
  const [tab, setTab] = useState<Tab>('rules')
  const tabRefs = useRef<Record<Tab, HTMLButtonElement | null>>({ rules: null, quiet: null, servers: null })
  const activeQuiet = silences.filter((s) => s.active).length + windows.filter((w) => w.active).length

  const select = (next: Tab) => {
    setTab(next)
    tabRefs.current[next]?.focus()
  }

  // Arrow keys move between tabs (WAI-ARIA tabs pattern); only the selected tab is in the tab order.
  const handleKeyDown = (event: React.KeyboardEvent) => {
    const index = TABS.indexOf(tab)
    if (event.key === 'ArrowRight') select(TABS[(index + 1) % TABS.length])
    else if (event.key === 'ArrowLeft') select(TABS[(index - 1 + TABS.length) % TABS.length])
    else if (event.key === 'Home') select(TABS[0])
    else if (event.key === 'End') select(TABS[TABS.length - 1])
    else return
    event.preventDefault()
  }

  return (
    <Layout currentView="alerts" setView={setView} title={t('alerts.title')}>
      <div className="flex flex-col gap-5 max-w-[1240px]">
        <QuietBanner silences={silences} windows={windows} groups={groups} rules={rules} onShow={() => select('quiet')} />

        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-[22px] font-bold text-slate-100 mb-1">{t('alerts.title')}</h1>
            <p className="text-[13px] text-slate-400">{t('alerts.screen.subtitle')}</p>
          </div>
          <div role="tablist" aria-label={t('alerts.screen.sections')} className="flex flex-wrap gap-2" onKeyDown={handleKeyDown}>
            {TABS.map((id) => (
              <button
                key={id}
                ref={(el) => { tabRefs.current[id] = el }}
                type="button"
                role="tab"
                id={`alerts-tab-${id}`}
                aria-selected={tab === id}
                aria-controls={`alerts-panel-${id}`}
                tabIndex={tab === id ? 0 : -1}
                onClick={() => setTab(id)}
                className={`min-h-9 px-4 py-2 rounded-full text-[13px] font-semibold border transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-400 ${
                  tab === id ? 'bg-violet-500/15 text-violet-200 border-violet-500/40' : 'text-slate-400 border-white/10 hover:text-slate-200'
                }`}
              >
                {t(`alerts.screen.tabs.${id}`)}
                {id === 'quiet' && activeQuiet > 0 && <span className="ml-1.5 font-mono opacity-70">{activeQuiet}</span>}
              </button>
            ))}
          </div>
        </div>

        <section id={`alerts-panel-${tab}`} role="tabpanel" aria-labelledby={`alerts-tab-${tab}`}>
          {tab === 'rules' && <RulesTab servers={servers} groups={groups} silences={silences} canManage={can('alerts.manage')} />}
          {tab === 'quiet' && (
            <QuietTab servers={servers} groups={groups} silences={silences} windows={windows} canManage={can('alerts.manage')} />
          )}
          {tab === 'servers' && <ServersTab servers={servers} groups={groups} canManageServers={can('servers.manage')} />}
        </section>
      </div>
    </Layout>
  )
}
