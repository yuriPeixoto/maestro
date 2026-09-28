import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AuthState {
  token: string | null
  username: string | null
  email: string | null
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  setProfile: (profile: { username: string; email: string }) => void
  isAuthenticated: boolean
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      username: null,
      email: null,
      isAuthenticated: false,

      login: async (username, password) => {
        const res = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password }),
        })
        if (!res.ok) throw new Error('Invalid credentials')
        const data: { access_token: string } = await res.json()
        set({ token: data.access_token, username, isAuthenticated: true })
      },

      logout: () => {
        // Best-effort — JWT is stateless server-side, so this never blocks local logout.
        fetch('/api/auth/logout', { method: 'POST' }).catch(() => undefined)
        set({ token: null, username: null, email: null, isAuthenticated: false })
      },

      setProfile: (profile) => set({ username: profile.username, email: profile.email }),
    }),
    {
      name: 'maestro-auth',
      partialize: (s) => ({ token: s.token, username: s.username, email: s.email, isAuthenticated: s.isAuthenticated }),
    }
  )
)
