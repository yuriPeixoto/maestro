import { useQuery } from '@tanstack/react-query'
import { metricsApi, securityApi, alertsApi, serversApi } from '../services/api'

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

export const useHealthSnapshot = (serverId: string, enabled = true) =>
  useQuery({
    queryKey: ['health-snapshot', serverId],
    queryFn: () => serversApi.healthSnapshot(serverId),
    enabled: enabled && !!serverId,
    refetchInterval: 30_000,
  })

export const useAttackers = (serverId: string) =>
  useQuery({
    queryKey: ['attackers', serverId],
    queryFn: () => securityApi.attackers(serverId),
    enabled: !!serverId,
    refetchInterval: 60_000,
  })

export const useAttackByHour = (serverId: string) =>
  useQuery({
    queryKey: ['attack-by-hour', serverId],
    queryFn: () => securityApi.attackByHour(serverId),
    enabled: !!serverId,
    refetchInterval: 60_000,
  })

export const useSshBaseline = (serverId: string) =>
  useQuery({
    queryKey: ['ssh-baseline', serverId],
    queryFn: () => securityApi.sshBaseline(serverId),
    enabled: !!serverId,
    staleTime: 300_000,
  })

export const useRulePatterns = (serverId: string) =>
  useQuery({
    queryKey: ['rule-patterns', serverId],
    queryFn: () => alertsApi.rulePatterns(serverId),
    enabled: !!serverId,
    refetchInterval: 60_000,
  })
