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
