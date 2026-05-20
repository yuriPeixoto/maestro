import { useQuery } from '@tanstack/react-query'
import { securityApi } from '../services/api'

export const useSshEvents = (serverId: string) =>
  useQuery({
    queryKey: ['ssh-events', serverId],
    queryFn: () => securityApi.sshEvents(serverId),
    enabled: !!serverId,
    refetchInterval: 30_000,
  })

export const useUfwSummary = (serverId: string) =>
  useQuery({
    queryKey: ['ufw-summary', serverId],
    queryFn: () => securityApi.ufwSummary(serverId),
    enabled: !!serverId,
    refetchInterval: 60_000,
    staleTime: 30_000,
  })

export const useUfwTopPorts = (serverId: string) =>
  useQuery({
    queryKey: ['ufw-top-ports', serverId],
    queryFn: () => securityApi.ufwTopPorts(serverId),
    enabled: !!serverId,
    refetchInterval: 60_000,
    staleTime: 30_000,
  })
