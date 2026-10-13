import { create } from 'zustand'
import { persist } from 'zustand/middleware'

const TOO_MANY_REQUESTS = 429

export class LoginThrottledError extends Error {}

interface AuthState {
  token: string | null
  username: string | null
  email: string | null
  mustChangePassword: boolean
  login: (identifier: string, password: string) => Promise<void>
  logout: () => void
  passwordChanged: () => void
  setProfile: (profile: { username: string; email: string }) => void
  isAuthenticated: boolean
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      username: null,
      email: null,
      mustChangePassword: false,
      isAuthenticated: false,

      login: async (identifier, password) => {
        const res = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: identifier, password }),
        })
        if (res.status === TOO_MANY_REQUESTS) throw new LoginThrottledError()
        if (!res.ok) throw new Error('Invalid credentials')
        const data: { access_token: string; username: string; must_change_password: boolean } = await res.json()
        set({
          token: data.access_token,
          username: data.username,
          mustChangePassword: data.must_change_password,
          isAuthenticated: true,
        })
      },

      logout: () => {
        // Best-effort — JWT is stateless server-side, so this never blocks local logout.
        fetch('/api/auth/logout', { method: 'POST' }).catch(() => undefined)
        set({ token: null, username: null, email: null, mustChangePassword: false, isAuthenticated: false })
      },

      passwordChanged: () => set({ mustChangePassword: false }),

      setProfile: (profile) => set({ username: profile.username, email: profile.email }),
    }),
    {
      name: 'maestro-auth',
      partialize: (s) => ({
        token: s.token,
        username: s.username,
        email: s.email,
        mustChangePassword: s.mustChangePassword,
        isAuthenticated: s.isAuthenticated,
      }),
    }
  )
)
