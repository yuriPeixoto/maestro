import { useState } from 'react'
import { Zap, Lock, User, Eye, EyeOff, Shield, Activity } from 'lucide-react'
import { useAuthStore } from '../store/authStore'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const login = useAuthStore((s) => s.login)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(username, password)
    } catch {
      setError('Usuário ou senha inválidos.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-brand-dark flex items-center justify-center relative overflow-hidden">

      {/* Background glows */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        <div className="absolute -top-32 -left-32 w-[600px] h-[600px] bg-brand-purple/10 rounded-full blur-[120px]" />
        <div className="absolute -bottom-32 -right-32 w-[400px] h-[400px] bg-brand-neon/5 rounded-full blur-[100px]" />
      </div>

      {/* Subtle grid */}
      <div
        className="absolute inset-0 opacity-[0.025] pointer-events-none"
        style={{
          backgroundImage:
            'linear-gradient(rgba(255,255,255,0.15) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.15) 1px, transparent 1px)',
          backgroundSize: '48px 48px',
        }}
      />

      {/* Decorative floating metric rows */}
      <div className="absolute top-8 left-8 hidden xl:flex flex-col gap-3 opacity-20 select-none pointer-events-none">
        {['cpu.usage', 'mem.used', 'disk.io'].map((m) => (
          <div key={m} className="flex items-center gap-3 text-[11px] font-mono text-slate-400">
            <Activity className="w-3 h-3 text-brand-purple" />
            <span>{m}</span>
            <span className="text-brand-neon">{(Math.random() * 100).toFixed(1)}%</span>
          </div>
        ))}
      </div>

      <div className="relative z-10 w-full max-w-sm px-6">

        {/* Logo */}
        <div className="flex flex-col items-center mb-10">
          <div className="w-16 h-16 bg-brand-purple rounded-2xl flex items-center justify-center shadow-[0_0_50px_rgba(124,58,237,0.6)] mb-5 ring-1 ring-brand-purple/30">
            <Zap className="w-9 h-9 text-white fill-current" />
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-glow-purple">Maestro</h1>
          <div className="flex items-center gap-2 mt-2">
            <span className="w-12 h-px bg-white/10" />
            <span className="text-[10px] text-slate-500 uppercase tracking-[0.2em] font-medium">Observability Platform</span>
            <span className="w-12 h-px bg-white/10" />
          </div>
        </div>

        {/* Card */}
        <div className="glass-card p-8 shadow-[0_0_80px_rgba(0,0,0,0.5)]">

          {/* Card header */}
          <div className="flex items-center gap-2 mb-7">
            <Shield className="w-4 h-4 text-brand-purple" />
            <span className="text-xs font-bold text-slate-300 uppercase tracking-widest">Acesso Restrito</span>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">

            {/* Username */}
            <div className="space-y-1.5">
              <label className="text-[10px] text-slate-500 uppercase tracking-widest font-bold">
                Usuário
              </label>
              <div className="relative group">
                <User className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 group-focus-within:text-brand-purple transition-colors" />
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full bg-brand-dark/80 border border-white/10 rounded-lg py-3 pl-9 pr-4 text-sm focus:outline-none focus:border-brand-purple/60 focus:ring-1 focus:ring-brand-purple/20 transition-all text-slate-100 placeholder-slate-600"
                  placeholder="username"
                  autoComplete="username"
                  autoFocus
                  required
                />
              </div>
            </div>

            {/* Password */}
            <div className="space-y-1.5">
              <label className="text-[10px] text-slate-500 uppercase tracking-widest font-bold">
                Senha
              </label>
              <div className="relative group">
                <Lock className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 group-focus-within:text-brand-purple transition-colors" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full bg-brand-dark/80 border border-white/10 rounded-lg py-3 pl-9 pr-10 text-sm focus:outline-none focus:border-brand-purple/60 focus:ring-1 focus:ring-brand-purple/20 transition-all text-slate-100 placeholder-slate-600"
                  placeholder="••••••••"
                  autoComplete="current-password"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* Error */}
            {error && (
              <div className="flex items-start gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2.5">
                <Shield className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {/* Submit */}
            <button
              type="submit"
              disabled={loading || !username || !password}
              className="w-full mt-1 relative bg-brand-purple hover:bg-brand-purple/90 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold py-3 rounded-lg transition-all shadow-[0_0_25px_rgba(124,58,237,0.35)] hover:shadow-[0_0_40px_rgba(124,58,237,0.55)] active:scale-[0.99] text-sm overflow-hidden"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Autenticando...
                </span>
              ) : (
                'Entrar'
              )}
            </button>
          </form>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-center gap-2 mt-6">
          <span className="w-1.5 h-1.5 rounded-full bg-brand-neon animate-pulse shadow-[0_0_6px_rgba(57,255,20,0.5)]" />
          <p className="text-[10px] text-slate-600 font-mono">
            Maestro · Staging · 153.75.226.75
          </p>
        </div>
      </div>
    </div>
  )
}
