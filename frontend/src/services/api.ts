import axios from 'axios'
import type { ServerStatus } from '../types/server'
import { useAuthStore } from '../store/authStore'

export const http = axios.create({ baseURL: '/api' })

http.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401) useAuthStore.getState().logout()
    return Promise.reject(error)
  }
)

export interface DataPoint {
  timestamp: string
  value: number
}

export interface MetricSeries {
  server_id: string
  metric: string
  minutes: number
  data: DataPoint[]
}

export interface MetricNames {
  server_id: string
  metrics: string[]
}

export const serversApi = {
  list: (): Promise<ServerStatus[]> =>
    http.get<ServerStatus[]>('/servers').then((r) => r.data),
  status: (serverId: string): Promise<ServerStatus> =>
    http.get<ServerStatus>(`/servers/${serverId}/status`).then((r) => r.data),
  healthSnapshot: (serverId: string): Promise<ServerHealthSnapshot> =>
    http.get<ServerHealthSnapshot>(`/servers/${serverId}/health-snapshot`).then((r) => r.data),
  /** Any role: the caller's own name for the server. */
  setNickname: (serverId: string, nickname: string): Promise<void> =>
    http.put(`/servers/${encodeURIComponent(serverId)}/nickname`, { nickname }).then(() => undefined),
  clearNickname: (serverId: string): Promise<void> =>
    http.delete(`/servers/${encodeURIComponent(serverId)}/nickname`).then(() => undefined),
}

export interface Meta {
  client_name: string
}

export const metaApi = {
  get: (): Promise<Meta> => http.get<Meta>('/meta').then((r) => r.data),
}

export const metricsApi = {
  names: (serverId: string): Promise<MetricNames> =>
    http.get<MetricNames>(`/metrics/${serverId}`).then((r) => r.data),
  series: (serverId: string, metric: string, minutes: number): Promise<MetricSeries> =>
    http
      .get<MetricSeries>(`/metrics/${serverId}/${metric}`, { params: { minutes } })
      .then((r) => r.data),
  anomalyScores: (serverId: string, metric: string, minutes: number): Promise<AnomalyScoresResponse> =>
    http
      .get<AnomalyScoresResponse>(`/metrics/${serverId}/${metric}/anomaly-scores`, { params: { minutes } })
      .then((r) => r.data),
}

export interface LogFilesResponse {
  server_id: string
  log_files: string[]
}

export interface LogLine {
  server_id: string
  log_file: string
  timestamp: string
  line: string
}

export interface LogHistoryResponse {
  server_id: string
  log_file: string
  lines: LogLine[]
}

export interface RuntimeEntry {
  name: string
  version: string
  status: string
  uptime_since: string | null
}

export interface InventoryResponse {
  server_id: string
  inventory: RuntimeEntry[]
}

export interface SshEvent {
  timestamp: string
  type: string
  action: string
  username: string
  source_ip: string
  result: string
}

export interface SshStats {
  attempts_1h: number
  attempts_24h: number
  unique_ips_24h: number
  top_target: string | null
  source_available: boolean
}

export interface SshEventsResponse {
  server_id: string
  stats: SshStats
  events: SshEvent[]
}

export interface UfwSummaryResponse {
  server_id: string
  is_active: boolean
  blocks_24h: number
}

export interface UfwPortEntry {
  port: number
  proto: string
  blocks: number
}

export interface UfwTopPortsResponse {
  server_id: string
  ports: UfwPortEntry[]
}

export const securityApi = {
  sshEvents: (serverId: string): Promise<SshEventsResponse> =>
    http.get<SshEventsResponse>(`/security/${serverId}/ssh-events`).then((r) => r.data),
  attackers: (serverId: string): Promise<AttackersResponse> =>
    http.get<AttackersResponse>(`/security/${serverId}/attackers`).then((r) => r.data),
  attackByHour: (serverId: string): Promise<AttackByHourResponse> =>
    http.get<AttackByHourResponse>(`/security/${serverId}/attack-by-hour`).then((r) => r.data),
  sshBaseline: (serverId: string): Promise<SshBaselineResponse> =>
    http.get<SshBaselineResponse>(`/security/${serverId}/ssh-baseline`).then((r) => r.data),
  ufwSummary: (serverId: string): Promise<UfwSummaryResponse> =>
    http.get<UfwSummaryResponse>(`/security/${serverId}/ufw/summary`).then((r) => r.data),
  ufwTopPorts: (serverId: string): Promise<UfwTopPortsResponse> =>
    http.get<UfwTopPortsResponse>(`/security/${serverId}/ufw/top-ports`).then((r) => r.data),
  vulnerabilities: (serverId: string): Promise<VulnerabilitiesResponse> =>
    http.get<VulnerabilitiesResponse>(`/security/${serverId}/vulnerabilities`).then((r) => r.data),
}

export const inventoryApi = {
  get: (serverId: string): Promise<InventoryResponse> =>
    http.get<InventoryResponse>(`/inventory/${serverId}`).then((r) => r.data),
}

export const logsApi = {
  files: (serverId: string): Promise<LogFilesResponse> =>
    http.get<LogFilesResponse>(`/logs/${serverId}`).then((r) => r.data),
  history: (serverId: string, logFile: string, lines = 200): Promise<LogHistoryResponse> =>
    http
      .get<LogHistoryResponse>(`/logs/${serverId}/${logFile}/history`, { params: { lines } })
      .then((r) => r.data),
}

/** app.permissions on the API: what a role may do. */
export type Permission =
  | 'view' | 'alerts.manage' | 'alerts.acknowledge' | 'servers.manage' | 'events.create' | 'analysis.run'
  | 'agents.manage' | 'users.manage' | 'audit.view'

export type UserRole = 'viewer' | 'operator' | 'admin'

export interface UserInfo {
  id: number
  username: string
  email: string
  full_name: string | null
  role: UserRole
  permissions: Permission[]
  must_change_password: boolean
  last_seen_version: string | null
}

export const authApi = {
  me: (): Promise<UserInfo> =>
    http.get<UserInfo>('/auth/me').then((r) => r.data),
  markReleaseSeen: (version: string): Promise<void> =>
    http.post('/auth/me/release-seen', { version }).then(() => undefined),
  updateEmail: (email: string): Promise<UserInfo> =>
    http.patch<UserInfo>('/auth/me', { email }).then((r) => r.data),
  changePassword: (currentPassword: string, newPassword: string): Promise<void> =>
    http
      .post('/auth/change-password', { current_password: currentPassword, new_password: newPassword })
      .then(() => undefined),
  logout: (): Promise<void> =>
    http.post('/auth/logout').then(() => undefined),
}

// ── About and release notes ──────────────────────────────────────────────────

export interface Release {
  version: string
  date: string
  notes: Record<string, string[]>
}

export interface AgentVersion {
  server_id: string
  version: string
  last_seen: string | null
}

export interface AboutResponse {
  version: string
  clickhouse_version: string | null
  agents: AgentVersion[]
  releases: Release[]
}

export const aboutApi = {
  get: (): Promise<AboutResponse> => http.get<AboutResponse>('/about').then((r) => r.data),
}

export interface AccountUser {
  id: number
  username: string
  email: string
  full_name: string | null
  role: UserRole
  active: boolean
  must_change_password: boolean
  created_at: string
  updated_at: string
  deactivated_at: string | null
  last_login_at: string | null
  last_seen_at: string | null
}

export interface NewAccount {
  username: string
  email: string
  full_name: string | null
  role: UserRole
}

export interface AccountChanges {
  email?: string
  full_name?: string
  role?: UserRole
}

export interface RolesMatrix {
  permissions: Permission[]
  roles: { role: UserRole; permissions: Permission[] }[]
}

export const usersApi = {
  list: (): Promise<AccountUser[]> =>
    http.get<AccountUser[]>('/users').then((r) => r.data),
  /** Without a password the API generates one and returns it this once. */
  create: (body: NewAccount): Promise<AccountUser & { temporary_password: string | null }> =>
    http.post<AccountUser & { temporary_password: string | null }>('/users', body).then((r) => r.data),
  update: (id: number, changes: AccountChanges): Promise<AccountUser> =>
    http.patch<AccountUser>(`/users/${id}`, changes).then((r) => r.data),
  // Accounts are never deleted: a deactivated one keeps its audit history.
  deactivate: (id: number): Promise<AccountUser> =>
    http.post<AccountUser>(`/users/${id}/deactivate`).then((r) => r.data),
  reactivate: (id: number): Promise<AccountUser> =>
    http.post<AccountUser>(`/users/${id}/reactivate`).then((r) => r.data),
  temporaryPassword: (id: number): Promise<string> =>
    http.post<{ temporary_password: string }>(`/users/${id}/temporary-password`).then((r) => r.data.temporary_password),
  roles: (): Promise<RolesMatrix> =>
    http.get<RolesMatrix>('/users/roles').then((r) => r.data),
}

// ── Audit log ────────────────────────────────────────────────────────────────

type AuditPlace = { scope: 'global' | 'group' | 'server'; server_id: string | null; group_id: number | null }

export type AuditTarget =
  | { kind: 'user'; username: string; full_name: string | null }
  | ({ kind: 'rule'; metric_name: string; operator: string; threshold: number; deleted: boolean } & AuditPlace)
  | ({ kind: 'channel'; channel_type: string; deleted: boolean } & AuditPlace)
  | { kind: 'server'; server_id: string; label: string | null }
  | { kind: 'group'; name: string; deleted: boolean }
  | ({ kind: 'silence'; reason: string } & AuditPlace)
  | { kind: 'maintenance'; server_id: string; reason: string; weekly: boolean; deleted: boolean }
  | { kind: 'alert'; server_id: string; metric_name: string; severity: string }

export interface AuditEntry {
  id: number
  occurred_at: string
  actor_user_id: number | null
  actor: string
  source_ip: string | null
  user_agent: string | null
  action: string
  target_table: string | null
  target_id: string | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  target_info: AuditTarget | null
}

export interface AuditPage {
  entries: AuditEntry[]
  next_before_id: number | null
}

export interface AuditFilters {
  actor_user_id?: number
  outside?: boolean
  /** Exact name, or a prefix ending in "." */
  action?: string
  since?: string
  until?: string
  before_id?: number
  limit?: number
}

export const auditApi = {
  list: (filters: AuditFilters): Promise<AuditPage> =>
    http.get<AuditPage>('/audit', { params: filters }).then((r) => r.data),
}

export interface AlertEvent {
  event_id: string
  rule_id: string
  metric_name: string
  value: number
  threshold: number
  severity: 'warning' | 'critical'
  state: 'FIRING' | 'RESOLVED' | 'NO_DATA'
  triggered_at: string
}

export interface AlertRule {
  rule_id: string
  server_id: string
  metric_name: string
  operator: string
  threshold: number
  severity: 'warning' | 'critical'
  cooldown_minutes: number
  created_at: string
  alert_mode: string
  ml_score_threshold: number
}

export interface AnomalyScore {
  timestamp: string
  score: number
}

export interface AnomalyScoresResponse {
  server_id: string
  metric: string
  minutes: number
  data: AnomalyScore[]
}

export interface AlertEventsResponse {
  server_id: string
  events: AlertEvent[]
}

export interface AlertRulesResponse {
  server_id: string
  rules: AlertRule[]
}

// ── Health snapshot ──────────────────────────────────────────────────────────

export interface MetricHealth {
  value: number | null
  baseline: number | null
  threshold: number
  attention: number
  trend: 'up' | 'down' | 'stable'
  spark: number[]
  projection_hours: number | null
}

export interface CriticalService {
  name: string
  ok: boolean
}

export interface ServerHealthSnapshot {
  server_id: string
  state: 'ok' | 'attention' | 'critical' | 'quiet'
  cpu: MetricHealth
  memory: MetricHealth
  disk: MetricHealth
  anomalies6h: number
  open_alerts: number
  critical_services: CriticalService[]
  headline_code: string
  headline_params: Record<string, number>
}

// ── Security V2 ──────────────────────────────────────────────────────────────

export interface Attacker {
  ip: string
  attempts: number
  users: string[]
  last_seen: string
}

export interface AttackHourBucket {
  hour: number
  count: number
}

export interface AttackersResponse {
  server_id: string
  attackers: Attacker[]
}

export interface AttackByHourResponse {
  server_id: string
  hours: AttackHourBucket[]
}

export interface SshBaselineResponse {
  server_id: string
  avg_daily: number
}

// ── Alert patterns ────────────────────────────────────────────────────────────

// ── Capacity planning / forecasting ─────────────────────────────────────────

export interface ForecastPoint {
  date: string
  yhat: number
  yhat_lower: number
  yhat_upper: number
}

export interface ForecastResponse {
  server_id: string
  metric_name: string
  status: 'ok' | 'insufficient_data' | 'error'
  horizon_days: number
  trained_at: string
  points: ForecastPoint[]
  trend_per_day: number | null
  level_shift_on: string | null
}

export type CapacityStatus = 'safe' | 'watch' | 'critical' | 'no_data'

export interface RunwayMetric {
  metric_name: string
  days_to_threshold: number | null
  current_value: number | null
  status: CapacityStatus
  trend_per_day: number | null
  level_shift_on: string | null
  days_to_threshold_at_trend: number | null
}

export interface DailyPeak {
  date: string
  peak: number
  minutes_above_critical: number
}

export interface PeakMetric {
  metric_name: string
  attention_pct: number
  critical_pct: number
  days: DailyPeak[]
  worst: DailyPeak | null
  headroom_pct: number | null
  minutes_above_critical: number
  trend: 'rising' | 'stable' | 'falling' | 'unknown'
  status: CapacityStatus
}

export interface PeaksResponse {
  server_id: string
  days: number
  window_minutes: number
  metrics: PeakMetric[]
}

export interface CollectionProgress {
  days_collected: number
  min_days: number
  weekly_pattern_days: number
  window_days: number
  state: 'learning' | 'preliminary' | 'evolving' | 'complete'
  complete_on: string | null
}

export interface RunwayResponse {
  server_id: string
  threshold_pct: number
  horizon_days: number
  collection: CollectionProgress
  metrics: RunwayMetric[]
}

export interface DailyPoint {
  date: string
  avg_value: number
}

export const forecastsApi = {
  forecast: (serverId: string, metricName: string): Promise<ForecastResponse> =>
    http.get<ForecastResponse>(`/forecasts/${serverId}/${metricName}`).then((r) => r.data),
  history: (serverId: string, metricName: string, days = 30): Promise<DailyPoint[]> =>
    http.get<DailyPoint[]>(`/forecasts/${serverId}/${metricName}/history`, { params: { days } }).then((r) => r.data),
  runway: (serverId: string): Promise<RunwayResponse> =>
    http.get<RunwayResponse>(`/forecasts/${serverId}/runway`).then((r) => r.data),
  peaks: (serverId: string, days = 30): Promise<PeaksResponse> =>
    http.get<PeaksResponse>(`/forecasts/${serverId}/peaks`, { params: { days } }).then((r) => r.data),
}

// ── Anomaly episodes ─────────────────────────────────────────────────────────

export interface EpisodeDeviation {
  metric: string
  value: number
  z: number
  normal_low: number
  normal_high: number
  peak_at: string
}

export interface AnomalyEpisode {
  started_at: string
  ended_at: string
  minutes: number
  ongoing: boolean
  deviations: EpisodeDeviation[]
}

export const anomaliesApi = {
  episodes: (serverId: string, hours: number): Promise<AnomalyEpisode[]> =>
    http.get<AnomalyEpisode[]>(`/anomalies/${serverId}/episodes`, { params: { hours } }).then((r) => r.data),
}

export const alertsApi = {
  events: (serverId: string, limit = 100): Promise<AlertEventsResponse> =>
    http.get<AlertEventsResponse>(`/alerts/${serverId}/events`, { params: { limit } }).then((r) => r.data),
  rules: (serverId: string): Promise<AlertRulesResponse> =>
    http.get<AlertRulesResponse>(`/alerts/${serverId}/rules`).then((r) => r.data),
  channelTypes: (): Promise<ChannelTypesResponse> =>
    http.get<ChannelTypesResponse>('/alerts/channel-types').then((r) => r.data),
  notifications: (serverId: string, limit = 50): Promise<NotificationRecord[]> =>
    http.get<NotificationRecord[]>(`/alerts/${serverId}/notifications`, { params: { limit } }).then((r) => r.data),
}

// ── Alert channels ────────────────────────────────────────────────────────────

export type ChannelType = 'webhook' | 'email' | 'slack' | 'telegram'

export interface ChannelTypesResponse {
  types: ChannelType[]
}

export interface AlertChannel {
  channel_id: string
  /** null: the channel takes every rule of the server */
  rule_id: string | null
  channel_type: ChannelType
  config: Record<string, string | boolean>
  created_at: string
}

export interface DeliveryResult {
  ok: boolean
  error: string
}

export interface NotificationRecord {
  sent_at: string
  channel_id: string
  channel_type: ChannelType
  rule_id: string | null
  kind: 'firing' | 'resolved' | 'no_data' | 'data_back' | 'reminder' | 'acknowledged' | 'test'
  ok: boolean
  error: string
}

// ── Server events ─────────────────────────────────────────────────────────────

export interface ServerEvent {
  event_id: string
  server_id: string
  event_type: string
  label: string
  metadata: Record<string, unknown>
  occurred_at: string
}

export interface ServerEventIn {
  event_type: string
  label: string
  metadata?: Record<string, unknown>
  occurred_at?: string
}

export const eventsApi = {
  list: (serverId: string, limit = 100, eventType?: string): Promise<ServerEvent[]> =>
    http.get<ServerEvent[]>(`/events/${serverId}`, { params: { limit, event_type: eventType } }).then((r) => r.data),
  register: (serverId: string, body: ServerEventIn): Promise<ServerEvent> =>
    http.post<ServerEvent>(`/events/${serverId}`, body).then((r) => r.data),
}

// ── Correlation analysis ─────────────────────────────────────────────────────

export interface CorrelationResult {
  event_type: string
  metric_name: string
  sample_count: number
  avg_delta: number
  avg_delta_pct: number
  p_value: number
  significant: boolean
  window_before_m: number
  window_after_m: number
  computed_at: string
  summary: string
}

export const analysisApi = {
  correlations: (serverId: string): Promise<CorrelationResult[]> =>
    http.get<CorrelationResult[]>(`/analysis/${serverId}/correlations`).then((r) => r.data),
  runAnalysis: (serverId: string): Promise<{ status: string }> =>
    http.post<{ status: string }>(`/analysis/${serverId}/correlations/run`).then((r) => r.data),
}

// ── Vulnerabilities ───────────────────────────────────────────────────────────

export interface VulnEntry {
  runtime: string
  version: string
  cve_id: string
  severity: 'critical' | 'high' | 'medium' | 'low' | null
  summary: string
  fixed_version: string | null
  published_at: string | null
}

export interface VulnerabilitiesResponse {
  server_id: string
  scanned_at: string | null
  vulnerabilities: VulnEntry[]
}

// ── DB Connections ────────────────────────────────────────────────────────────

export interface DBConnectionEntry {
  user: string
  host: string
  db: string
  command: string
  state: string
  elapsed_sec: number
  query: string
  client: string
}

export interface DBSnapshotResponse {
  server_id: string
  db_type: string
  captured_at: string
  connections: DBConnectionEntry[]
}

export interface DBSnapshotsResponse {
  server_id: string
  snapshots: DBSnapshotResponse[]
}

export interface DBHistoryPoint {
  timestamp: string
  total: number
  long_running: number
}

export interface DBHistoryResponse {
  server_id: string
  db_type: string
  data: DBHistoryPoint[]
}

export const dbConnectionsApi = {
  snapshot: (serverId: string): Promise<DBSnapshotsResponse> =>
    http.get<DBSnapshotsResponse>(`/db-connections/${serverId}`).then((r) => r.data),
  history: (serverId: string, dbType: string, minutes = 60): Promise<DBHistoryResponse> =>
    http
      .get<DBHistoryResponse>(`/db-connections/${serverId}/history`, { params: { db_type: dbType, minutes } })
      .then((r) => r.data),
}
