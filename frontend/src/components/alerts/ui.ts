import type { TFunction } from 'i18next'
import type { ServerStatus } from '../../types/server'
import type { Place, Scope, ScopedRule, ServerGroup, Silence } from '../../services/alertingApi'
import { formatRuleValue, metricLabel } from '../../utils/format'

export { buttonDanger, buttonGhost, buttonPrimary, fieldClass, hintClass, labelClass } from '../users/ui'

const pillBase = 'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-bold whitespace-nowrap border'

export const pill = {
  global: `${pillBase} bg-violet-500/15 text-violet-300 border-violet-500/35`,
  group: `${pillBase} bg-sky-400/10 text-sky-300 border-sky-400/30`,
  server: `${pillBase} bg-emerald-400/10 text-emerald-300 border-emerald-400/30`,
  off: `${pillBase} bg-slate-400/10 text-slate-300 border-slate-400/25`,
  critical: `${pillBase} bg-red-400/10 text-red-300 border-red-400/30`,
  warning: `${pillBase} bg-yellow-400/10 text-yellow-200 border-yellow-400/30`,
  quiet: `${pillBase} bg-orange-400/10 text-orange-300 border-orange-400/35`,
  noData: `${pillBase} bg-slate-400/10 text-slate-200 border-dashed border-slate-400/50`,
} as const

export const smallButton = 'min-h-[30px] px-2.5 py-1 text-xs'

export const tableHead = 'text-[10px] text-slate-400 uppercase tracking-widest font-bold text-left px-4 py-2.5 bg-brand-dark/40'
export const tableCell = 'px-4 py-3 text-[13px] border-t border-white/5 align-middle'

export const sectionCard = 'glass-card px-5 py-4'

export const OPERATOR_SYMBOL: Record<string, string> = { '>': '>', '<': '<', '>=': '≥', '<=': '≤', '==': '=' }

export const limitText = (rule: Pick<ScopedRule, 'operator' | 'threshold' | 'metric_name'>): string =>
  `${OPERATOR_SYMBOL[rule.operator] ?? rule.operator} ${formatRuleValue(rule.metric_name, rule.threshold)}`

export const ruleName = (rule: Pick<ScopedRule, 'metric_name' | 'severity'>, t: TFunction): string =>
  `${metricLabel(rule.metric_name, t)} · ${t(`alerts.severity.${rule.severity}`)}`

export const placeKey = (place: Place): string => `${place.scope}:${place.server_id ?? ''}:${place.group_id ?? ''}`

export const scopePill = (scope: Scope) => pill[scope]

/** "Every server", "Group Robots", "This server" or the server's name. */
export function placeLabel(
  place: Pick<Place, 'scope' | 'server_id' | 'group_id'>,
  t: TFunction,
  groups: ServerGroup[],
  nameOf?: (serverId: string) => string,
  here?: string,
): string {
  if (place.scope === 'global') return t('alerts.screen.place.global')
  if (place.scope === 'group') {
    const group = groups.find((g) => g.group_id === place.group_id)
    return t('alerts.screen.place.group', { name: group?.name ?? '—' })
  }
  if (here && place.server_id === here) return t('alerts.screen.place.thisServer')
  return nameOf ? nameOf(place.server_id ?? '') : (place.server_id ?? '')
}

/** Whether a silence covers this rule on this server now. */
export function silenceCovers(silence: Silence, server: Pick<ServerStatus, 'server_id' | 'group_id'>, ruleId: string): boolean {
  if (!silence.active) return false
  if (silence.rule_id && silence.rule_id !== ruleId) return false
  if (silence.scope === 'global') return true
  if (silence.scope === 'group') return silence.group_id === server.group_id
  return silence.server_id === server.server_id
}

export const clockTime = (iso: string): string =>
  new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })

export const dateTime = (iso: string): string =>
  new Date(iso).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })

export const minutesUntil = (iso: string): number => Math.max(Math.round((new Date(iso).getTime() - Date.now()) / 60_000), 0)

/** The API answers in English; these are the refusals of this screen a person can act on. */
const KNOWN_ERRORS: [RegExp, string][] = [
  [/already has a rule for this metric and severity/, 'alerts.screen.errors.duplicateRule'],
  [/already has maintenance planned/, 'alerts.screen.errors.overlap'],
  [/already has this label/, 'alerts.screen.errors.labelTaken'],
  [/nickname/i, 'alerts.screen.errors.nicknameTaken'],
  [/still use this group/, 'alerts.screen.errors.groupInUse'],
  [/set for a group or every server/, 'alerts.screen.errors.inherited'],
  [/at most 30 days/, 'alerts.screen.errors.silenceTooLong'],
  [/at most 7 days/, 'alerts.screen.errors.windowTooLong'],
  [/must end in the future/, 'alerts.screen.errors.endInPast'],
  [/acknowledged this alert already/, 'alerts.screen.errors.alreadyAcknowledged'],
]

export function alertingError(error: unknown, t: TFunction): string {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })?.response
  if (response?.status === 403) return t('users.errors.forbidden')
  const detail = typeof response?.data?.detail === 'string' ? response.data.detail : ''
  const known = KNOWN_ERRORS.find(([pattern]) => pattern.test(detail))
  if (known) return t(known[1])
  return response?.status === 422 ? t('users.errors.invalid') : t('users.errors.generic')
}

export const GLOBAL: Place = { scope: 'global' }

/** The places whose channels reach `place`: a server hears global, its group's and its own. */
export function placesReaching(place: Place, groupOfServer: number | null): Place[] {
  if (place.scope !== 'server') return [place]
  const places: Place[] = [GLOBAL]
  if (groupOfServer !== null) places.push({ scope: 'group', group_id: groupOfServer })
  places.push(place)
  return places
}
