import axios from 'axios'
import type { ServerStatus } from '../types/server'

const http = axios.create({ baseURL: '/api' })

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

export const logsApi = {
  files: (serverId: string): Promise<LogFilesResponse> =>
    http.get<LogFilesResponse>(`/logs/${serverId}`).then((r) => r.data),
  history: (serverId: string, logFile: string, lines = 200): Promise<LogHistoryResponse> =>
    http
      .get<LogHistoryResponse>(`/logs/${serverId}/${logFile}/history`, { params: { lines } })
      .then((r) => r.data),
}
