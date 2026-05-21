import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { alertsApi, type AlertChannelIn, type AlertRuleIn } from '../services/api'

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

export const useAlertChannels = (serverId: string, ruleId: string) =>
  useQuery({
    queryKey: ['alert-channels', serverId, ruleId],
    queryFn: () => alertsApi.listChannels(serverId, ruleId),
    enabled: !!serverId && !!ruleId,
    staleTime: 60_000,
  })

export const useAddChannel = (serverId: string, ruleId: string) => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: AlertChannelIn) => alertsApi.addChannel(serverId, ruleId, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alert-channels', serverId, ruleId] }),
  })
}

export const useDeleteChannel = (serverId: string, ruleId: string) => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (channelId: string) => alertsApi.deleteChannel(serverId, ruleId, channelId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alert-channels', serverId, ruleId] }),
  })
}
