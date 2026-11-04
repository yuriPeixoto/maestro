import { useQuery } from '@tanstack/react-query'
import { aboutApi, authApi } from '../services/api'

export const useAbout = () =>
  useQuery({
    queryKey: ['about'],
    queryFn: aboutApi.get,
    staleTime: 60_000,
  })

export const useMe = () =>
  useQuery({
    queryKey: ['me'],
    queryFn: authApi.me,
    staleTime: Infinity,
  })
