import { useQuery } from '@tanstack/react-query'
import { securityApi, dbConnectionsApi } from '../services/api'

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

export const useVulnerabilities = (serverId: string) =>
  useQuery({
    queryKey: ['vulnerabilities', serverId],
    queryFn: () => securityApi.vulnerabilities(serverId),
    enabled: !!serverId,
    refetchInterval: 3_600_000,  // hourly — scanner runs daily
    staleTime: 1_800_000,
  })

export const useDBSnapshot = (serverId: string) =>
  useQuery({
    queryKey: ['db-snapshot', serverId],
    queryFn: () => dbConnectionsApi.snapshot(serverId),
    enabled: !!serverId,
    refetchInterval: 30_000,
  })

export const useDBHistory = (serverId: string, dbType: string, minutes = 60) =>
  useQuery({
    queryKey: ['db-history', serverId, dbType, minutes],
    queryFn: () => dbConnectionsApi.history(serverId, dbType, minutes),
    enabled: !!serverId && !!dbType,
    refetchInterval: 30_000,
  })
