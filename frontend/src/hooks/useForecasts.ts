import { useQuery } from '@tanstack/react-query'
import { forecastsApi } from '../services/api'

export const useForecast = (serverId: string, metricName: string) =>
  useQuery({
    queryKey: ['forecast', serverId, metricName],
    queryFn: () => forecastsApi.forecast(serverId, metricName),
    enabled: !!serverId && !!metricName,
    retry: false,
    staleTime: 3_600_000,
    refetchInterval: 3_600_000,
  })

export const useForecastHistory = (serverId: string, metricName: string, days = 30) =>
  useQuery({
    queryKey: ['forecast-history', serverId, metricName, days],
    queryFn: () => forecastsApi.history(serverId, metricName, days),
    enabled: !!serverId && !!metricName,
    staleTime: 1_800_000,   // 30min
    refetchInterval: 1_800_000,
  })

export const useRunway = (serverId: string) =>
  useQuery({
    queryKey: ['runway', serverId],
    queryFn: () => forecastsApi.runway(serverId),
    enabled: !!serverId,
    retry: false,
    staleTime: 3_600_000,
    refetchInterval: 3_600_000,
  })
