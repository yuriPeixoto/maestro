import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { auditApi, usersApi, type AccountChanges, type AuditFilters, type NewAccount } from '../services/api'

const AUDIT_PAGE_SIZE = 50

export const useAccounts = (enabled: boolean) =>
  useQuery({ queryKey: ['users'], queryFn: usersApi.list, enabled })

export const useRolesMatrix = (enabled: boolean) =>
  useQuery({ queryKey: ['users', 'roles'], queryFn: usersApi.roles, enabled, staleTime: Infinity })

export const useAuditLog = (filters: Omit<AuditFilters, 'before_id' | 'limit'>, enabled: boolean) =>
  useInfiniteQuery({
    queryKey: ['audit', filters],
    queryFn: ({ pageParam }) => auditApi.list({ ...filters, before_id: pageParam, limit: AUDIT_PAGE_SIZE }),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (page) => page.next_before_id ?? undefined,
    enabled,
  })

/** Every account change shows up in the list and, through the trigger, in the audit log. */
const useAccountMutation = <TArgs, TResult>(run: (args: TArgs) => Promise<TResult>) => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: run,
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      queryClient.invalidateQueries({ queryKey: ['audit'] })
    },
  })
}

export const useCreateAccount = () => useAccountMutation((body: NewAccount) => usersApi.create(body))

export const useUpdateAccount = () =>
  useAccountMutation(({ id, changes }: { id: number; changes: AccountChanges }) => usersApi.update(id, changes))

export const useDeactivateAccount = () => useAccountMutation((id: number) => usersApi.deactivate(id))

export const useReactivateAccount = () => useAccountMutation((id: number) => usersApi.reactivate(id))

export const useTemporaryPassword = () => useAccountMutation((id: number) => usersApi.temporaryPassword(id))
