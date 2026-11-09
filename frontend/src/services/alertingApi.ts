/**
 * Alerting by place (ADR-013) and the alert cycle (ADR-014): rules and channels for every
 * server, a group or one server; silences and maintenance; groups and shared labels; open
 * alerts and acknowledging; deliveries waiting for a retry.
 */
import { http, type AlertRule, type ChannelType, type DeliveryResult } from './api'

export type Scope = 'global' | 'group' | 'server'

export interface Place {
  scope: Scope
  server_id?: string | null
  group_id?: number | null
}

export interface ScopedRule extends Omit<AlertRule, 'server_id'> {
  scope: Scope
  server_id: string | null
  group_id: number | null
  enabled: boolean
}

export interface ScopedRuleIn extends Place {
  metric_name: string
  operator: string
  threshold: number
  severity: 'warning' | 'critical'
  cooldown_minutes: number
  alert_mode?: string
  ml_score_threshold?: number
  enabled?: boolean
}

export type RuleChanges = Partial<Pick<ScopedRule, 'operator' | 'threshold' | 'cooldown_minutes' | 'alert_mode' | 'ml_score_threshold' | 'enabled'>>

export interface ResolvedRule {
  rule: ScopedRule
  /** Rules of broader places for the same metric and severity that `rule` overrides. */
  overrides: ScopedRule[]
}

export interface ScopedChannel {
  channel_id: string
  scope: Scope
  server_id: string | null
  group_id: number | null
  rule_id: string | null
  channel_type: ChannelType
  config: Record<string, string | boolean>
  created_at: string
}

export interface ScopedChannelIn extends Place {
  channel_type: ChannelType
  config: Record<string, string>
  rule_id: string | null
}

export interface Silence {
  silence_id: string
  scope: Scope
  server_id: string | null
  group_id: number | null
  rule_id: string | null
  starts_at: string
  ends_at: string
  reason: string
  created_by: string
  created_at: string
  active: boolean
}

export interface SilenceIn extends Place {
  rule_id: string | null
  reason: string
  duration_minutes?: number
  ends_at?: string
}

export interface Weekly {
  weekdays: number[]
  local_start: string
  duration_minutes: number
  time_zone: string
  repeat_until: string | null
}

export interface MaintenanceWindow {
  window_id: string
  server_id: string
  reason: string
  created_by: string
  created_at: string
  starts_at: string | null
  ends_at: string | null
  weekly: Weekly | null
  next_starts_at: string | null
  next_ends_at: string | null
  active: boolean
}

export interface MaintenanceIn {
  server_id: string
  reason: string
  starts_at?: string
  ends_at?: string
  weekly?: Weekly
}

export interface ServerGroup {
  group_id: number
  name: string
  description: string | null
}

export type OpenState = 'FIRING' | 'NO_DATA'

export interface OpenAlert {
  rule_id: string
  server_id: string
  scope: Scope
  metric_name: string
  operator: string
  threshold: number
  severity: 'warning' | 'critical'
  cooldown_minutes: number
  value: number | null
  state: OpenState
  since: string | null
  acknowledged_at: string | null
  acknowledged_by: string | null
  quiet: 'silence' | 'maintenance' | null
}

export interface PendingRetry {
  retry_id: number
  channel_id: string
  attempts: number
  max_attempts: number
  next_attempt_at: string
  first_attempt_at: string
  last_error: string
  kinds: string[]
}

const placeParams = (place: Place) => ({
  scope: place.scope,
  server_id: place.scope === 'server' ? place.server_id : undefined,
  group_id: place.scope === 'group' ? place.group_id : undefined,
})

const server = (id: string) => encodeURIComponent(id)

export const alertingApi = {
  allRules: (): Promise<ScopedRule[]> => http.get<ScopedRule[]>('/alerts/rules').then((r) => r.data),
  rulesAt: (place: Place): Promise<ScopedRule[]> =>
    http.get<ScopedRule[]>('/alerts/rules', { params: placeParams(place) }).then((r) => r.data),
  resolvedRules: (serverId: string): Promise<ResolvedRule[]> =>
    http.get<ResolvedRule[]>(`/alerts/${server(serverId)}/resolved-rules`).then((r) => r.data),
  createRule: (body: ScopedRuleIn): Promise<ScopedRule> =>
    http.post<ScopedRule>('/alerts/rules', { ...body, ...placeParams(body) }).then((r) => r.data),
  updateRule: (ruleId: string, changes: RuleChanges): Promise<ScopedRule> =>
    http.patch<ScopedRule>(`/alerts/rules/${ruleId}`, changes).then((r) => r.data),
  deleteRule: (ruleId: string): Promise<void> => http.delete(`/alerts/rules/${ruleId}`).then(() => undefined),

  channelsAt: (place: Place): Promise<ScopedChannel[]> =>
    http.get<ScopedChannel[]>('/alerts/channels', { params: placeParams(place) }).then((r) => r.data),
  createChannel: (body: ScopedChannelIn): Promise<ScopedChannel> =>
    http.post<ScopedChannel>('/alerts/channels', { ...body, ...placeParams(body) }).then((r) => r.data),
  moveChannel: (channelId: string, place: Place): Promise<ScopedChannel> =>
    http.post<ScopedChannel>(`/alerts/channels/${channelId}/move`, placeParams(place)).then((r) => r.data),
  testChannel: (channelId: string): Promise<DeliveryResult> =>
    http.post<DeliveryResult>(`/alerts/channels/${channelId}/test`).then((r) => r.data),
  deleteChannel: (channelId: string): Promise<void> =>
    http.delete(`/alerts/channels/${channelId}`).then(() => undefined),

  silences: (): Promise<Silence[]> => http.get<Silence[]>('/alerts/silences').then((r) => r.data),
  createSilence: (body: SilenceIn): Promise<Silence> =>
    http.post<Silence>('/alerts/silences', { ...body, ...placeParams(body) }).then((r) => r.data),
  endSilence: (silenceId: string): Promise<void> =>
    http.post(`/alerts/silences/${silenceId}/end`).then(() => undefined),

  maintenance: (): Promise<MaintenanceWindow[]> =>
    http.get<MaintenanceWindow[]>('/alerts/maintenance').then((r) => r.data),
  createMaintenance: (body: MaintenanceIn): Promise<MaintenanceWindow> =>
    http.post<MaintenanceWindow>('/alerts/maintenance', body).then((r) => r.data),
  cancelMaintenance: (windowId: string): Promise<void> =>
    http.delete(`/alerts/maintenance/${windowId}`).then(() => undefined),

  groups: (): Promise<ServerGroup[]> => http.get<ServerGroup[]>('/server-groups').then((r) => r.data),
  createGroup: (name: string): Promise<ServerGroup> =>
    http.post<ServerGroup>('/server-groups', { name }).then((r) => r.data),
  deleteGroup: (groupId: number): Promise<void> => http.delete(`/server-groups/${groupId}`).then(() => undefined),
  /** Admins: null clears the label or takes the server out of its group. */
  updateServer: (serverId: string, changes: { label?: string | null; group_id?: number | null }): Promise<void> =>
    http.patch(`/servers/${server(serverId)}`, changes).then(() => undefined),

  openAlerts: (): Promise<OpenAlert[]> => http.get<OpenAlert[]>('/alerts/open').then((r) => r.data),
  acknowledge: (serverId: string, ruleId: string): Promise<OpenAlert> =>
    http.post<OpenAlert>(`/alerts/${server(serverId)}/rules/${ruleId}/acknowledge`).then((r) => r.data),
  retries: (serverId: string): Promise<PendingRetry[]> =>
    http.get<PendingRetry[]>(`/alerts/${server(serverId)}/retries`).then((r) => r.data),
}
