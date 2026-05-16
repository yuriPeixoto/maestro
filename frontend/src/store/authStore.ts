import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AuthState {
  token: string | null
  username: string | null
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  isAuthenticated: boolean
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      username: null,
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

      logout: () => set({ token: null, username: null, isAuthenticated: false }),
    }),
    {
      name: 'maestro-auth',
      partialize: (s) => ({ token: s.token, username: s.username, isAuthenticated: s.isAuthenticated }),
    }
  )
)
