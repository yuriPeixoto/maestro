import { useQuery } from '@tanstack/react-query'
import { metricsApi } from '../services/api'

export const useMetricNames = (serverId: string) =>
  useQuery({
    queryKey: ['metric-names', serverId],
    queryFn: () => metricsApi.names(serverId),
    enabled: !!serverId,
    staleTime: 60_000,
  })

export const useMetricSeries = (serverId: string, metric: string, minutes: number) =>
  useQuery({
    queryKey: ['metric-series', serverId, metric, minutes],
    queryFn: () => metricsApi.series(serverId, metric, minutes),
    enabled: !!serverId && !!metric,
    refetchInterval: 30_000,
  })

export const useAnomalyScores = (serverId: string, metric: string, minutes: number, enabled = true) =>
  useQuery({
    queryKey: ['anomaly-scores', serverId, metric, minutes],
    queryFn: () => metricsApi.anomalyScores(serverId, metric, minutes),
    enabled: enabled && !!serverId && !!metric,
    refetchInterval: 60_000,
  })
