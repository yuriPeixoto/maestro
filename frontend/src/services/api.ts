import axios from 'axios'
import type { ServerStatus } from '../types/server'
import { useAuthStore } from '../store/authStore'

const http = axios.create({ baseURL: '/api' })

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
}

export interface SshEventsResponse {
  server_id: string
  stats: SshStats
  events: SshEvent[]
}

export const securityApi = {
  sshEvents: (serverId: string): Promise<SshEventsResponse> =>
    http.get<SshEventsResponse>(`/security/${serverId}/ssh-events`).then((r) => r.data),
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

export const authApi = {
  me: (): Promise<{ username: string }> =>
    http.get<{ username: string }>('/auth/me').then((r) => r.data),
}

export interface AlertEvent {
  event_id: string
  rule_id: string
  metric_name: string
  value: number
  threshold: number
  severity: 'warning' | 'critical'
  state: 'FIRING' | 'RESOLVED'
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

export interface AlertRuleIn {
  metric_name: string
  operator: string
  threshold: number
  severity: 'warning' | 'critical'
  cooldown_minutes: number
  alert_mode?: string
  ml_score_threshold?: number
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

export interface WebhookConfig {
  server_id: string
  url: string | null
}

export const alertsApi = {
  events: (serverId: string, limit = 100): Promise<AlertEventsResponse> =>
    http.get<AlertEventsResponse>(`/alerts/${serverId}/events`, { params: { limit } }).then((r) => r.data),
  rules: (serverId: string): Promise<AlertRulesResponse> =>
    http.get<AlertRulesResponse>(`/alerts/${serverId}/rules`).then((r) => r.data),
  createRule: (serverId: string, body: AlertRuleIn): Promise<AlertRule> =>
    http.post<AlertRule>(`/alerts/${serverId}/rules`, body).then((r) => r.data),
  deleteRule: (serverId: string, ruleId: string): Promise<void> =>
    http.delete(`/alerts/${serverId}/rules/${ruleId}`).then(() => undefined),
  getWebhook: (serverId: string): Promise<WebhookConfig> =>
    http.get<WebhookConfig>(`/alerts/${serverId}/webhook`).then((r) => r.data),
  saveWebhook: (serverId: string, url: string): Promise<WebhookConfig> =>
    http.put<WebhookConfig>(`/alerts/${serverId}/webhook`, { url }).then((r) => r.data),
  deleteWebhook: (serverId: string): Promise<void> =>
    http.delete(`/alerts/${serverId}/webhook`).then(() => undefined),
}
