import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { alertsApi, type AlertChannelIn } from '../services/api'

export const useChannelTypes = () =>
  useQuery({
    queryKey: ['alert-channel-types'],
    queryFn: () => alertsApi.channelTypes(),
    staleTime: 5 * 60_000,
  })

export const useAlertChannels = (serverId: string) =>
  useQuery({
    queryKey: ['alert-channels', serverId],
    queryFn: () => alertsApi.listChannels(serverId),
    enabled: !!serverId,
    staleTime: 60_000,
  })

export const useNotificationHistory = (serverId: string) =>
  useQuery({
    queryKey: ['alert-notifications', serverId],
    queryFn: () => alertsApi.notifications(serverId),
    enabled: !!serverId,
    refetchInterval: 30_000,
  })

export const useAddChannel = (serverId: string) => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: AlertChannelIn) => alertsApi.addChannel(serverId, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alert-channels', serverId] }),
  })
}

export const useDeleteChannel = (serverId: string) => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (channelId: string) => alertsApi.deleteChannel(serverId, channelId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alert-channels', serverId] }),
  })
}

export const useTestChannel = (serverId: string) => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (channelId: string) => alertsApi.testChannel(serverId, channelId),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['alert-notifications', serverId] }),
  })
}
