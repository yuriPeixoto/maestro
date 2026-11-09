import { useQuery } from '@tanstack/react-query'
import { alertsApi } from '../services/api'

export const useAlertEvents = (serverId: string) =>
  useQuery({
    queryKey: ['alert-events', serverId],
    queryFn: () => alertsApi.events(serverId),
    enabled: !!serverId,
    refetchInterval: 30_000,
  })

export const useAlertRules = (serverId: string) =>
  useQuery({
    queryKey: ['alert-rules', serverId],
    queryFn: () => alertsApi.rules(serverId),
    enabled: !!serverId,
    staleTime: 60_000,
  })
