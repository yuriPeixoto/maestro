import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { analysisApi, eventsApi, type ServerEventIn } from '../services/api'

export function useServerEvents(serverId: string, eventType?: string) {
  return useQuery({
    queryKey: ['server-events', serverId, eventType],
    queryFn: () => eventsApi.list(serverId, 200, eventType),
    enabled: !!serverId,
    staleTime: 30_000,
  })
}

export function useRegisterEvent(serverId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ServerEventIn) => eventsApi.register(serverId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['server-events', serverId] }),
  })
}

export function useCorrelations(serverId: string) {
  return useQuery({
    queryKey: ['correlations', serverId],
    queryFn: () => analysisApi.correlations(serverId),
    enabled: !!serverId,
    staleTime: 300_000, // 5 min — results are computed nightly
  })
}

export function useTriggerAnalysis(serverId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => analysisApi.runAnalysis(serverId),
    onSuccess: () => setTimeout(() => qc.invalidateQueries({ queryKey: ['correlations', serverId] }), 3000),
  })
}
