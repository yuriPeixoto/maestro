import { useQuery } from '@tanstack/react-query'
import { serversApi } from '../services/api'

export const useServers = () =>
  useQuery({
    queryKey: ['servers'],
    queryFn: serversApi.list,
    refetchInterval: 30_000,
  })

export const useServerStatus = (serverId: string) =>
  useQuery({
    queryKey: ['server', serverId],
    queryFn: () => serversApi.status(serverId),
    refetchInterval: 30_000,
    enabled: !!serverId,
  })
