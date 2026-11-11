import type { TFunction } from 'i18next'
import i18n from '../../i18n'
import type { AuditEntry, AuditTarget, UserRole } from '../../services/api'
import { formatRuleValue, metricLabel } from '../../utils/format'

/** Action groups for the filter: prefixes the API matches ("users." is every account change). */
export const ACTION_GROUPS = [
  'users.', 'alert_rules.', 'alert_channels.', 'alert_silences.', 'maintenance_windows.', 'alert_state.', 'servers.',
  'server_groups.', 'auth.',
] as const

const ANONYMOUS = 'anonymous'
// What the worker signs its changes with; only the API's database user can (app.audit.WORKER_ACTOR).
export const WORKER_ACTOR = 'maestro-worker'
// The trigger writes these in place of a secret's value.
const CHANGED = '[changed]'
const REDACTED = '[redacted]'

// Never worth a line: the row's key and bookkeeping the trigger already skips on updates.
const HIDDEN_FIELDS = new Set([
  'id', 'rule_id', 'channel_id', 'silence_id', 'window_id', 'created_at', 'updated_at', 'last_seen_version', 'created_by', 'ended_by',
])
// On a new row, only what says what it is.
const SHOWN_ON_INSERT: Record<string, string[]> = {
  users: ['username', 'email', 'full_name', 'role'],
  alert_rules: ['scope', 'server_id', 'metric_name', 'operator', 'threshold', 'severity', 'cooldown_minutes', 'alert_mode'],
  alert_channels: ['scope', 'server_id', 'channel_type', 'rule_id'],
  alert_silences: ['scope', 'server_id', 'reason'],
  maintenance_windows: ['server_id', 'reason', 'weekdays', 'local_start'],
  servers: ['server_id', 'label'],
  server_groups: ['name'],
}
const TIMESTAMP_FIELDS = new Set(['deactivated_at', 'deleted_at', 'last_login_at', 'locked_until'])

export type ActorKind = 'account' | 'anonymous' | 'worker' | 'outside'

export function actorKind(entry: AuditEntry): ActorKind {
  if (entry.actor_user_id !== null) return 'account'
  if (entry.actor === ANONYMOUS) return 'anonymous'
  return entry.actor === WORKER_ACTOR ? 'worker' : 'outside'
}

const changedFields = (entry: AuditEntry): string[] => {
  const before = entry.before ?? {}
  const after = entry.after ?? {}
  return Object.keys(after).filter(
    (key) => !HIDDEN_FIELDS.has(key) && JSON.stringify(before[key]) !== JSON.stringify(after[key]),
  )
}

/** The action as the screen names it. A plain update that only moved the role reads as such. */
export function actionKey(entry: AuditEntry): string {
  if (entry.action === 'users.update' && entry.before) {
    const fields = changedFields(entry)
    if (fields.length === 1 && fields[0] === 'role') return 'users.role'
  }
  return entry.action
}

export const actionLabel = (entry: AuditEntry, t: TFunction): string =>
  t(`audit.actions.${actionKey(entry).replace('.', '_')}`, { defaultValue: entry.action })

const formatDateTime = (iso: string): string =>
  new Date(iso).toLocaleString(i18n.language, { dateStyle: 'short', timeStyle: 'short' })

function formatValue(field: string, value: unknown, t: TFunction, entry: AuditEntry): string {
  if (value === CHANGED) return t('audit.values.changed')
  if (value === REDACTED) return t('audit.values.hidden')
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return t(value ? 'audit.values.yes' : 'audit.values.no')
  if (field === 'role') return t(`roles.${value as UserRole}`, { defaultValue: String(value) })
  if (field === 'metric_name') return metricLabel(String(value), t)
  if (field === 'threshold' && typeof value === 'number') {
    const metric = String(entry.after?.metric_name ?? entry.before?.metric_name ?? '')
    return formatRuleValue(metric, value)
  }
  if (field === 'cooldown_minutes') return `${value} min`
  if (field === 'channel_type') return t(`alerts.channels.type.${value}`, { defaultValue: String(value) })
  if (field === 'severity') return t(`audit.values.severity.${value}`, { defaultValue: String(value) })
  if (field === 'scope') return t(`audit.values.scope.${value}`, { defaultValue: String(value) })
  if (TIMESTAMP_FIELDS.has(field) && typeof value === 'string') return formatDateTime(value)
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export interface DiffLine {
  field: string
  label: string
  before: string | null
  after: string
}

/** What changed, field by field, in words. A new row lists what it was created with. */
export function diffLines(entry: AuditEntry, t: TFunction): DiffLine[] {
  const label = (field: string) => t(`audit.fields.${field}`, { defaultValue: field })
  const after = entry.after ?? {}

  if (!entry.before) {
    const shown = SHOWN_ON_INSERT[entry.target_table ?? ''] ?? []
    return shown
      .filter((field) => after[field] !== null && after[field] !== undefined)
      .map((field) => ({ field, label: label(field), before: null, after: formatValue(field, after[field], t, entry) }))
  }
  if (!entry.after) return []

  const lines: DiffLine[] = changedFields(entry).map((field) => {
    // Moving this mark ends every session started before it.
    if (field === 'sessions_valid_after') {
      return { field, label: t('audit.fields.sessions'), before: null, after: t('audit.values.sessionsEnded') }
    }
    return {
      field,
      label: label(field),
      before: formatValue(field, entry.before?.[field], t, entry),
      after: formatValue(field, after[field], t, entry),
    }
  })
  // The lockout column is not audited, but a temporary password always clears it.
  if (entry.action === 'users.temporary_password') {
    lines.push({ field: 'locked_until', label: t('audit.fields.lockout'), before: null, after: t('audit.values.released') })
  }
  return lines
}

/** Short tags for events that change no row: why a login was refused, how a test went. */
export function eventTags(entry: AuditEntry, t: TFunction): { text: string; tone: 'bad' | 'good' | 'neutral' }[] {
  const details = entry.after ?? {}
  if (entry.action === 'auth.login_failed') {
    const tags: { text: string; tone: 'bad' | 'good' | 'neutral' }[] = [
      { text: t(`audit.reasons.${String(details.reason)}`, { defaultValue: String(details.reason) }), tone: 'neutral' },
    ]
    if (details.locked) tags.push({ text: t('audit.reasons.locked'), tone: 'bad' })
    return tags
  }
  if (entry.action === 'alert_channels.test') {
    return [details.ok ? { text: t('audit.values.delivered'), tone: 'good' } : { text: t('audit.values.notDelivered'), tone: 'bad' }]
  }
  if (entry.action.endsWith('.truncate')) {
    return [{ text: t('audit.values.rowsRemoved', { count: Number(details.rows ?? 0) }), tone: 'bad' }]
  }
  return []
}

/** Where a rule, channel or silence applies, as the audit line names it. */
function placeText(place: { scope: string; server_id: string | null; group_id: number | null }, t: TFunction): string {
  if (place.scope === 'global') return t('audit.values.scope.global')
  if (place.scope === 'group') return t('audit.values.groupNumber', { id: place.group_id })
  return place.server_id ?? '—'
}

export function targetLabel(entry: AuditEntry, t: TFunction): string {
  const info: AuditTarget | null = entry.target_info
  const table = (name: string) => t(`audit.tables.${name}`, { defaultValue: name })
  if (!info) {
    if (!entry.target_table) return '—'
    return entry.target_id ? `${table(entry.target_table)} · ${entry.target_id.slice(0, 8)}` : table(entry.target_table)
  }
  const removed = 'deleted' in info && info.deleted ? ` · ${t('audit.values.removed')}` : ''
  switch (info.kind) {
    case 'user':
      return info.full_name || info.username
    case 'rule': {
      const rule = `${metricLabel(info.metric_name, t)} ${info.operator} ${formatRuleValue(info.metric_name, info.threshold)}`
      return `${table('alert_rules')} · ${rule} (${placeText(info, t)})${removed}`
    }
    case 'channel': {
      const type = t(`alerts.channels.type.${info.channel_type}`, { defaultValue: info.channel_type })
      return `${table('alert_channels')} · ${type} (${placeText(info, t)})${removed}`
    }
    case 'server':
      return `${table('servers')} · ${info.label ? `${info.label} (${info.server_id})` : info.server_id}`
    case 'group':
      return `${table('server_groups')} · ${info.name}${removed}`
    case 'silence':
      return `${table('alert_silences')} · ${placeText(info, t)} · “${info.reason}”`
    case 'maintenance':
      return `${table('maintenance_windows')} · ${info.server_id} · “${info.reason}”${removed}`
    case 'alert':
      return `${table('alert_state')} · ${metricLabel(info.metric_name, t)} · ${t(`audit.values.severity.${info.severity}`, { defaultValue: info.severity })} (${info.server_id})`
  }
}

// Order matters: Edge and Opera say "Chrome" too, Chrome says "Safari".
const BROWSERS: [RegExp, string][] = [
  [/Edg\//, 'Edge'],
  [/OPR\//, 'Opera'],
  [/Firefox\//, 'Firefox'],
  [/Chrome\//, 'Chrome'],
  [/Safari\//, 'Safari'],
  [/curl\//, 'curl'],
]

export function browserName(userAgent: string | null): string | null {
  if (!userAgent) return null
  const match = BROWSERS.find(([pattern]) => pattern.test(userAgent))
  return match ? match[1] : userAgent.split(/[\s/]/)[0]
}

export const whereFrom = (entry: AuditEntry): string =>
  [entry.source_ip, browserName(entry.user_agent)].filter(Boolean).join(' · ') || '—'

export { formatDateTime }
