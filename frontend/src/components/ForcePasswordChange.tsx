import { useState } from 'react'
import { Zap, Lock, KeyRound, Shield } from 'lucide-react'
import { authApi } from '../services/api'
import { useAuthStore } from '../store/authStore'

const MIN_PASSWORD_LENGTH = 8

const inputClass =
  'w-full bg-brand-dark/80 border border-white/10 rounded-lg py-3 pl-9 pr-4 text-sm focus:outline-none focus:border-brand-purple/60 focus:ring-1 focus:ring-brand-purple/20 transition-all text-slate-100 placeholder-slate-600'

function PasswordField({
  label,
  icon: Icon,
  ...props
}: { label: string; icon: typeof Lock } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="space-y-1.5">
      <label className="text-[10px] text-slate-500 uppercase tracking-widest font-bold">{label}</label>
      <div className="relative group">
        <Icon className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 group-focus-within:text-brand-purple transition-colors" />
        <input type="password" className={inputClass} required {...props} />
      </div>
    </div>
  )
}

export default function ForcePasswordChange() {
  const username = useAuthStore((s) => s.username)
  const logout = useAuthStore((s) => s.logout)
  const passwordChanged = useAuthStore((s) => s.passwordChanged)

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const validate = (): string => {
    if (newPassword.length < MIN_PASSWORD_LENGTH) return `A nova senha precisa ter pelo menos ${MIN_PASSWORD_LENGTH} caracteres.`
    if (newPassword !== confirmation) return 'A confirmação não confere com a nova senha.'
    if (newPassword === currentPassword) return 'A nova senha precisa ser diferente da senha temporária.'
    return ''
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const problem = validate()
    setError(problem)
    if (problem) return

    setSaving(true)
    try {
      await authApi.changePassword(currentPassword, newPassword)
      passwordChanged()
    } catch {
      setError('Não foi possível trocar a senha — confira a senha temporária.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="min-h-screen bg-brand-dark flex items-center justify-center relative overflow-hidden">
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        <div className="absolute -top-32 -left-32 w-[600px] h-[600px] bg-brand-purple/10 rounded-full blur-[120px]" />
        <div className="absolute -bottom-32 -right-32 w-[400px] h-[400px] bg-brand-neon/5 rounded-full blur-[100px]" />
      </div>

      <div className="relative z-10 w-full max-w-sm px-6">
        <div className="flex flex-col items-center mb-8">
          <div className="w-16 h-16 bg-brand-purple rounded-2xl flex items-center justify-center shadow-[0_0_50px_rgba(124,58,237,0.6)] mb-5 ring-1 ring-brand-purple/30">
            <Zap className="w-9 h-9 text-white fill-current" />
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-glow-purple">Maestro</h1>
        </div>

        <div className="glass-card p-8 shadow-[0_0_80px_rgba(0,0,0,0.5)]">
          <div className="flex items-center gap-2 mb-3">
            <Shield className="w-4 h-4 text-brand-purple" />
            <span className="text-xs font-bold text-slate-300 uppercase tracking-widest">Defina sua senha</span>
          </div>
          <p className="text-xs text-slate-400 mb-6 leading-relaxed">
            Olá, <span className="text-slate-200 font-semibold">{username}</span>. Sua senha atual é temporária.
            Escolha uma senha só sua para liberar o acesso.
          </p>

          <form onSubmit={handleSubmit} className="space-y-5">
            <PasswordField
              label="Senha temporária"
              icon={KeyRound}
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              autoComplete="current-password"
              autoFocus
            />
            <PasswordField
              label="Nova senha"
              icon={Lock}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              autoComplete="new-password"
              minLength={MIN_PASSWORD_LENGTH}
            />
            <PasswordField
              label="Confirme a nova senha"
              icon={Lock}
              value={confirmation}
              onChange={(e) => setConfirmation(e.target.value)}
              autoComplete="new-password"
            />

            {error && (
              <div className="flex items-start gap-2 text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2.5">
                <Shield className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={saving || !currentPassword || !newPassword || !confirmation}
              className="w-full bg-brand-purple hover:bg-brand-purple/90 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold py-3 rounded-lg transition-all shadow-[0_0_25px_rgba(124,58,237,0.35)] hover:shadow-[0_0_40px_rgba(124,58,237,0.55)] active:scale-[0.99] text-sm"
            >
              {saving ? 'Salvando...' : 'Salvar e entrar'}
            </button>
          </form>

          <button
            type="button"
            onClick={logout}
            className="w-full mt-4 text-[11px] text-slate-500 hover:text-slate-300 transition-colors"
          >
            Sair
          </button>
        </div>
      </div>
    </div>
  )
}
