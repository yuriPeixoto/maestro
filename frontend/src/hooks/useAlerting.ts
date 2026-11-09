import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  alertingApi,
  type MaintenanceIn,
  type Place,
  type RuleChanges,
  type ScopedChannelIn,
  type ScopedRuleIn,
  type SilenceIn,
} from '../services/alertingApi'
import { serversApi } from '../services/api'

const REFRESH_MS = 30_000

// Every query of this screen starts with "alerting", so a change refreshes all of it at once:
// a rule edited at one place changes what wins on every server.
const KEY = 'alerting'

const useInvalidate = () => {
  const queryClient = useQueryClient()
  return () => Promise.all([
    queryClient.invalidateQueries({ queryKey: [KEY] }),
    queryClient.invalidateQueries({ queryKey: ['servers'] }),
    queryClient.invalidateQueries({ queryKey: ['alert-notifications'] }),
  ])
}

const useChange = <TArgs,>(mutationFn: (args: TArgs) => Promise<unknown>) => {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn, onSuccess: invalidate })
}

export const useAllRules = () =>
  useQuery({ queryKey: [KEY, 'rules', 'all'], queryFn: alertingApi.allRules, refetchInterval: REFRESH_MS })

export const useRulesAt = (place: Place, enabled = true) =>
  useQuery({
    queryKey: [KEY, 'rules', place.scope, place.server_id ?? null, place.group_id ?? null],
    queryFn: () => alertingApi.rulesAt(place),
    enabled,
  })

export const useResolvedRules = (serverId: string) =>
  useQuery({
    queryKey: [KEY, 'resolved', serverId],
    queryFn: () => alertingApi.resolvedRules(serverId),
    enabled: !!serverId,
    refetchInterval: REFRESH_MS,
  })

/** The channels at each of these places, in order. */
export const useChannelsAt = (places: Place[]) =>
  useQueries({
    queries: places.map((place) => ({
      queryKey: [KEY, 'channels', place.scope, place.server_id ?? null, place.group_id ?? null],
      queryFn: () => alertingApi.channelsAt(place),
    })),
  })

export const useSilences = () =>
  useQuery({ queryKey: [KEY, 'silences'], queryFn: alertingApi.silences, refetchInterval: REFRESH_MS })

export const useMaintenance = () =>
  useQuery({ queryKey: [KEY, 'maintenance'], queryFn: alertingApi.maintenance, refetchInterval: REFRESH_MS })

export const useGroups = () => useQuery({ queryKey: [KEY, 'groups'], queryFn: alertingApi.groups })

export const useOpenAlerts = () =>
  useQuery({ queryKey: [KEY, 'open'], queryFn: alertingApi.openAlerts, refetchInterval: REFRESH_MS })

export const useRetries = (serverId: string) =>
  useQuery({
    queryKey: [KEY, 'retries', serverId],
    queryFn: () => alertingApi.retries(serverId),
    enabled: !!serverId,
    refetchInterval: REFRESH_MS,
  })

export const useCreateRule = () => useChange((body: ScopedRuleIn) => alertingApi.createRule(body))
export const useUpdateRule = () =>
  useChange(({ ruleId, changes }: { ruleId: string; changes: RuleChanges }) => alertingApi.updateRule(ruleId, changes))
export const useDeleteRule = () => useChange((ruleId: string) => alertingApi.deleteRule(ruleId))

export const useCreateChannel = () => useChange((body: ScopedChannelIn) => alertingApi.createChannel(body))
export const useMoveChannel = () =>
  useChange(({ channelId, place }: { channelId: string; place: Place }) => alertingApi.moveChannel(channelId, place))
export const useDeleteChannel = () => useChange((channelId: string) => alertingApi.deleteChannel(channelId))
export const useTestChannel = () => useChange((channelId: string) => alertingApi.testChannel(channelId))

export const useCreateSilence = () => useChange((body: SilenceIn) => alertingApi.createSilence(body))
export const useEndSilence = () => useChange((silenceId: string) => alertingApi.endSilence(silenceId))
export const useCreateMaintenance = () => useChange((body: MaintenanceIn) => alertingApi.createMaintenance(body))
export const useCancelMaintenance = () => useChange((windowId: string) => alertingApi.cancelMaintenance(windowId))

export const useCreateGroup = () => useChange((name: string) => alertingApi.createGroup(name))
export const useDeleteGroup = () => useChange((groupId: number) => alertingApi.deleteGroup(groupId))
export const useUpdateServer = () =>
  useChange(({ serverId, changes }: { serverId: string; changes: { label?: string | null; group_id?: number | null } }) =>
    alertingApi.updateServer(serverId, changes))

export const useAcknowledge = () =>
  useChange(({ serverId, ruleId }: { serverId: string; ruleId: string }) => alertingApi.acknowledge(serverId, ruleId))

// Any role: a nickname is the caller's own preference.
export const useSetNickname = () =>
  useChange(({ serverId, nickname }: { serverId: string; nickname: string }) => serversApi.setNickname(serverId, nickname))
export const useClearNickname = () => useChange((serverId: string) => serversApi.clearNickname(serverId))
