import { useQuery } from '@tanstack/react-query'
import { authApi, type Permission } from '../services/api'
import { useAuthStore } from '../store/authStore'

// A role changed by an admin applies on the next request; this keeps the screen close behind.
const ROLE_REFRESH_MS = 30_000

/** The caller's account from GET /auth/me, keyed by username so another login never reads it. */
export const useMe = () => {
  const username = useAuthStore((s) => s.username)
  return useQuery({
    queryKey: ['me', username],
    queryFn: authApi.me,
    enabled: username !== null,
    staleTime: ROLE_REFRESH_MS,
    refetchInterval: ROLE_REFRESH_MS,
  })
}

/**
 * What the caller's role allows (app.permissions on the API). The screen hides what is not
 * allowed; the API refuses it anyway. Until /auth/me answers, nothing beyond viewing is allowed.
 */
export const usePermissions = () => {
  const { data: me } = useMe()
  const granted = new Set(me?.permissions ?? [])
  return {
    role: me?.role ?? null,
    can: (permission: Permission) => granted.has(permission),
  }
}
