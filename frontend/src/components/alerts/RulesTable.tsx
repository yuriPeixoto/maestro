import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { Loader2 } from 'lucide-react'
import { useDeleteRule, useUpdateRule } from '../../hooks/useAlerting'
import type { ServerName } from '../../hooks/useServerName'
import type { ResolvedRule, ScopedRule, ServerGroup, Silence } from '../../services/alertingApi'
import type { ServerStatus } from '../../types/server'
import { formatRuleValue, metricLabel } from '../../utils/format'
import {
  alertingError, buttonGhost, clockTime, limitText, pill, placeLabel, scopePill, silenceCovers, smallButton, tableCell, tableHead,
} from './ui'

// Rules read in this order: is the server there at all, then disk, memory, CPU, the rest.
const METRIC_ORDER = ['heartbeat_age_seconds', 'disk_usage_percent', 'memory_usage_percent', 'cpu_usage_percent']
const SEVERITY_ORDER = ['warning', 'critical']

const byMetric = (a: ScopedRule, b: ScopedRule) => {
  const rank = (m: string) => (METRIC_ORDER.indexOf(m) === -1 ? METRIC_ORDER.length : METRIC_ORDER.indexOf(m))
  return rank(a.metric_name) - rank(b.metric_name)
    || a.metric_name.localeCompare(b.metric_name)
    || SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity)
}

export interface RuleActions {
  canManage: boolean
  onEdit: (rule: ScopedRule) => void
  onOverride: (rule: ScopedRule) => void
}

function Head({ t }: { t: TFunction }) {
  return (
    <thead>
      <tr>
        <th className={tableHead}>{t('alerts.screen.col.metric')}</th>
        <th className={tableHead}>{t('alerts.screen.col.severity')}</th>
        <th className={tableHead}>{t('alerts.screen.col.limit')}</th>
        <th className={tableHead}>{t('alerts.screen.col.from')}</th>
        <th className={`${tableHead} hidden md:table-cell`}>{t('alerts.screen.col.repeat')}</th>
        <th className={tableHead}><span className="sr-only">{t('alerts.screen.col.actions')}</span></th>
      </tr>
    </thead>
  )
}

function Cells({ rule, t, quietUntil }: { rule: ScopedRule; t: TFunction; quietUntil?: string }) {
  return (
    <>
      <td className={tableCell}>
        <span className="flex flex-wrap items-center gap-2">
          {metricLabel(rule.metric_name, t)}
          {quietUntil && <span className={pill.quiet} title={t('alerts.screen.rules.silencedUntil', { time: clockTime(quietUntil) })}>{t('alerts.screen.rules.silenced')}</span>}
          {rule.alert_mode !== 'static' && <span className={pill.global}>{rule.alert_mode === 'ml' ? t('alerts.detection.badgeMl') : t('alerts.detection.badgeBoth')}</span>}
        </span>
      </td>
      <td className={tableCell}><span className={pill[rule.severity]}>{t(`alerts.severity.${rule.severity}`)}</span></td>
      <td className={`${tableCell} font-mono`}>{limitText(rule)}</td>
    </>
  )
}

const Repeat = ({ rule, t }: { rule: ScopedRule; t: TFunction }) => (
  <td className={`${tableCell} hidden md:table-cell`}>
    {rule.enabled ? t('alerts.screen.rules.minutes', { count: rule.cooldown_minutes }) : '—'}
  </td>
)

/** The rules judged on one server: where each comes from, and what can be changed only there. */
export function ServerRules({ resolved, server, name, groups, silences, actions }: {
  resolved: ResolvedRule[] | undefined
  server: ServerStatus
  name: ServerName
  groups: ServerGroup[]
  silences: Silence[]
  actions: RuleActions
}) {
  const { t } = useTranslation()
  const remove = useDeleteRule()
  const update = useUpdateRule()
  const busy = remove.isPending || update.isPending
  if (!resolved) return <Loading t={t} />
  const items = [...resolved].sort((a, b) => byMetric(a.rule, b.rule))

  const switchOn = (item: ResolvedRule) => {
    // Without the rule underneath, switching on is the rule's own flag; with it, removing this one.
    if (item.overrides.length) remove.mutate(item.rule.rule_id)
    else update.mutate({ ruleId: item.rule.rule_id, changes: { enabled: true } })
  }

  const confirmRemove = (rule: ScopedRule) => {
    if (window.confirm(t('alerts.screen.rules.confirmRemove'))) remove.mutate(rule.rule_id)
  }

  return (
    <div className="glass-card overflow-x-auto">
      <table className="w-full">
        <caption className="sr-only">{t('alerts.screen.rules.captionServer', { server: name.display })}</caption>
        <Head t={t} />
        <tbody>
          {items.length === 0 && (
            <tr><td colSpan={6} className={`${tableCell} text-slate-400`}>{t('alerts.screen.rules.none')}</td></tr>
          )}
          {items.map(({ rule, overrides }) => {
            const silence = silences.find((s) => silenceCovers(s, server, rule.rule_id))
            const replaced = overrides[0]
            const inherited = rule.scope !== 'server'
            return (
              <tr key={rule.rule_id} className={rule.enabled ? '' : 'text-slate-500'}>
                <Cells rule={rule} t={t} quietUntil={silence?.ends_at} />
                <td className={tableCell}>
                  {rule.enabled ? (
                    <span className={scopePill(rule.scope)}>{placeLabel(rule, t, groups, undefined, server.server_id)}</span>
                  ) : (
                    <span className={pill.off}>{t('alerts.screen.rules.offHere')}</span>
                  )}
                  {replaced && rule.enabled && (
                    <div className="mt-1 text-xs text-slate-400">
                      {t('alerts.screen.rules.replaces')}{' '}
                      <s className="text-slate-500">{limitText(replaced)} · {placeLabel(replaced, t, groups)}</s>
                    </div>
                  )}
                  {replaced && !rule.enabled && (
                    <div className="mt-1 text-xs text-slate-400">{t('alerts.screen.rules.appliesElsewhere', { place: placeLabel(replaced, t, groups) })}</div>
                  )}
                </td>
                <Repeat rule={rule} t={t} />
                <td className={`${tableCell} text-right whitespace-nowrap`}>
                  {actions.canManage && (
                    <span className="inline-flex gap-2">
                      {!rule.enabled && (
                        <button type="button" className={`${buttonGhost} ${smallButton}`} disabled={busy} onClick={() => switchOn({ rule, overrides })}>
                          {t('alerts.screen.rules.switchOn')}
                        </button>
                      )}
                      {rule.enabled && inherited && (
                        <button type="button" className={`${buttonGhost} ${smallButton}`} onClick={() => actions.onOverride(rule)}>
                          {t('alerts.screen.rules.changeHere')}
                        </button>
                      )}
                      {rule.enabled && !inherited && (
                        <>
                          <button type="button" className={`${buttonGhost} ${smallButton}`} onClick={() => actions.onEdit(rule)}>
                            {t('alerts.screen.rules.edit')}
                          </button>
                          <button type="button" className={`${buttonGhost} ${smallButton}`} disabled={busy}
                            onClick={() => (replaced ? remove.mutate(rule.rule_id) : confirmRemove(rule))}>
                            {replaced ? t('alerts.screen.rules.backToDefault') : t('alerts.screen.rules.remove')}
                          </button>
                        </>
                      )}
                    </span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <Failure t={t} error={remove.error ?? update.error} />
    </div>
  )
}

/** What groups and servers do with a broader rule: "group Robots changes it (95%)". */
function changesBelow(rule: ScopedRule, all: ScopedRule[], t: TFunction, groups: ServerGroup[], nameOf: (id: string) => ServerName): string[] {
  const below = all.filter((r) => r.rule_id !== rule.rule_id && r.metric_name === rule.metric_name
    && r.severity === rule.severity && (rule.scope === 'global' ? r.scope !== 'global' : r.scope === 'server'))
  const notes: string[] = []
  for (const r of below.filter((x) => x.scope === 'group' && x.enabled)) {
    const group = groups.find((g) => g.group_id === r.group_id)
    notes.push(t('alerts.screen.rules.groupChanges', { name: group?.name ?? '—', value: formatRuleValue(r.metric_name, r.threshold) }))
  }
  const servers = below.filter((x) => x.scope === 'server' && x.enabled)
  if (servers.length === 1) {
    notes.push(t('alerts.screen.rules.oneServerChanges', {
      name: nameOf(servers[0].server_id ?? '').display, value: formatRuleValue(servers[0].metric_name, servers[0].threshold),
    }))
  } else if (servers.length > 1) {
    notes.push(t('alerts.screen.rules.serversChange', { count: servers.length }))
  }
  const off = below.filter((x) => !x.enabled).length
  if (off) notes.push(t('alerts.screen.rules.offIn', { count: off }))
  return notes
}

/** The rules set for every server or for one group, with what is set more specifically below. */
export function PlaceRules({ rules, all, broader, groups, nameOf, actions, caption }: {
  rules: ScopedRule[] | undefined
  all: ScopedRule[]
  /** For a group: the global rules its rules replace. */
  broader: ScopedRule[]
  groups: ServerGroup[]
  nameOf: (id: string) => ServerName
  actions: RuleActions
  caption: string
}) {
  const { t } = useTranslation()
  const remove = useDeleteRule()
  if (!rules) return <Loading t={t} />
  const items = [...rules].sort(byMetric)

  return (
    <div className="glass-card overflow-x-auto">
      <table className="w-full">
        <caption className="sr-only">{caption}</caption>
        <Head t={t} />
        <tbody>
          {items.length === 0 && (
            <tr><td colSpan={6} className={`${tableCell} text-slate-400`}>{t('alerts.screen.rules.noneHere')}</td></tr>
          )}
          {items.map((rule) => {
            const replaced = broader.find((b) => b.metric_name === rule.metric_name && b.severity === rule.severity)
            const notes = changesBelow(rule, all, t, groups, nameOf)
            return (
              <tr key={rule.rule_id} className={rule.enabled ? '' : 'text-slate-500'}>
                <Cells rule={rule} t={t} />
                <td className={tableCell}>
                  <span className={rule.enabled ? scopePill(rule.scope) : pill.off}>
                    {rule.enabled ? placeLabel(rule, t, groups) : t('alerts.screen.rules.offInGroup')}
                  </span>
                  {replaced && (
                    <div className="mt-1 text-xs text-slate-400">
                      {t('alerts.screen.rules.replaces')} <s className="text-slate-500">{limitText(replaced)} · {placeLabel(replaced, t, groups)}</s>
                    </div>
                  )}
                  {notes.length > 0 && <div className="mt-1 text-xs text-slate-400">{notes.join(' · ')}</div>}
                </td>
                <Repeat rule={rule} t={t} />
                <td className={`${tableCell} text-right whitespace-nowrap`}>
                  {actions.canManage && (
                    <span className="inline-flex gap-2">
                      <button type="button" className={`${buttonGhost} ${smallButton}`} onClick={() => actions.onEdit(rule)}>
                        {t('alerts.screen.rules.edit')}
                      </button>
                      <button
                        type="button"
                        className={`${buttonGhost} ${smallButton}`}
                        disabled={remove.isPending}
                        onClick={() => { if (window.confirm(t('alerts.screen.rules.confirmRemove'))) remove.mutate(rule.rule_id) }}
                      >
                        {t('alerts.screen.rules.remove')}
                      </button>
                    </span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <Failure t={t} error={remove.error} />
    </div>
  )
}

function Loading({ t }: { t: TFunction }) {
  return <p className="flex items-center gap-2 text-sm text-slate-400"><Loader2 className="w-4 h-4 animate-spin" aria-hidden />{t('common.loading')}</p>
}

function Failure({ t, error }: { t: TFunction; error: unknown }) {
  if (!error) return null
  return <p role="alert" className="px-4 py-2 text-xs text-red-300">{alertingError(error, t)}</p>
}
