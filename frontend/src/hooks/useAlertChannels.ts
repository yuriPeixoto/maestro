import { useQuery } from '@tanstack/react-query'
import { alertsApi } from '../services/api'

export const useChannelTypes = () =>
  useQuery({
    queryKey: ['alert-channel-types'],
    queryFn: () => alertsApi.channelTypes(),
    staleTime: 5 * 60_000,
  })

export const useNotificationHistory = (serverId: string) =>
  useQuery({
    queryKey: ['alert-notifications', serverId],
    queryFn: () => alertsApi.notifications(serverId),
    enabled: !!serverId,
    refetchInterval: 30_000,
  })
