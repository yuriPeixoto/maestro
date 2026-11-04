import { useQuery } from '@tanstack/react-query'
import { anomaliesApi } from '../services/api'

export const useAnomalyEpisodes = (serverId: string, hours: number) =>
  useQuery({
    queryKey: ['anomaly-episodes', serverId, hours],
    queryFn: () => anomaliesApi.episodes(serverId, hours),
    enabled: !!serverId,
    refetchInterval: 60_000,
  })
