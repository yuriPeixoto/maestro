import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { alertsApi, type AlertRuleIn } from '../services/api'

export const useWebhookConfig = (serverId: string) =>
  useQuery({
    queryKey: ['webhook-config', serverId],
    queryFn: () => alertsApi.getWebhook(serverId),
    enabled: !!serverId,
    staleTime: 60_000,
  })

export const useSaveWebhook = (serverId: string) => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (url: string) => alertsApi.saveWebhook(serverId, url),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['webhook-config', serverId] }),
  })
}

export const useDeleteWebhook = (serverId: string) => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => alertsApi.deleteWebhook(serverId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['webhook-config', serverId] }),
  })
}

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

export const useCreateAlertRule = (serverId: string) => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: AlertRuleIn) => alertsApi.createRule(serverId, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alert-rules', serverId] }),
  })
}

export const useDeleteAlertRule = (serverId: string) => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (ruleId: string) => alertsApi.deleteRule(serverId, ruleId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alert-rules', serverId] }),
  })
}
