import { useQuery } from '@tanstack/react-query'
import { inventoryApi } from '../services/api'

export const useInventory = (serverId: string) =>
  useQuery({
    queryKey: ['inventory', serverId],
    queryFn: () => inventoryApi.get(serverId),
    enabled: !!serverId,
    staleTime: 5 * 60_000,
    refetchInterval: 30_000,
  })
