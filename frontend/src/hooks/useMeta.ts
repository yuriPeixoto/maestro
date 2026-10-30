import { useQuery } from '@tanstack/react-query'
import { metaApi } from '../services/api'

export const useMeta = () =>
  useQuery({
    queryKey: ['meta'],
    queryFn: metaApi.get,
    staleTime: Infinity,
  })
