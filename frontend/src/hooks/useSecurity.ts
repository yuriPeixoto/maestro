import { useQuery } from '@tanstack/react-query'
import { securityApi } from '../services/api'

export const useSshEvents = (serverId: string) =>
  useQuery({
    queryKey: ['ssh-events', serverId],
    queryFn: () => securityApi.sshEvents(serverId),
    enabled: !!serverId,
    refetchInterval: 30_000,
  })
