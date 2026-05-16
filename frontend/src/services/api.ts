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
