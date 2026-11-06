import { useQuery } from '@tanstack/react-query'
import { aboutApi } from '../services/api'

export const useAbout = () =>
  useQuery({
    queryKey: ['about'],
    queryFn: aboutApi.get,
    staleTime: 60_000,
  })
