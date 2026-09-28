import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Mail, Lock, User, Check } from 'lucide-react'
import Layout from './Layout'
import type { ViewType } from '../App'
import { authApi } from '../services/api'
import { useAuthStore } from '../store/authStore'

interface ProfileProps {
  setView: (view: ViewType) => void
}

const inputClass =
  'w-full bg-brand-dark/80 border border-white/10 rounded-lg py-2.5 pl-9 pr-4 text-sm focus:outline-none focus:border-brand-purple/60 focus:ring-1 focus:ring-brand-purple/20 transition-all text-slate-100 placeholder-slate-600'

function Field({ icon: Icon, ...props }: { icon: typeof Mail } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div className="relative group">
      <Icon className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 group-focus-within:text-brand-purple transition-colors" />
      <input className={inputClass} {...props} />
    </div>
  )
}

export default function Profile({ setView }: ProfileProps) {
  const { t } = useTranslation()
  const username = useAuthStore((s) => s.username)
  const setProfile = useAuthStore((s) => s.setProfile)

  const [email, setEmail] = useState('')
  const [emailSaved, setEmailSaved] = useState(false)
  const [emailError, setEmailError] = useState('')

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [passwordSaved, setPasswordSaved] = useState(false)
  const [passwordError, setPasswordError] = useState('')

  useEffect(() => {
    authApi.me().then((info) => {
      setEmail(info.email)
      setProfile({ username: info.username, email: info.email })
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleSaveEmail = async (e: React.FormEvent) => {
    e.preventDefault()
    setEmailError('')
    setEmailSaved(false)
    try {
      const info = await authApi.updateEmail(email)
      setProfile({ username: info.username, email: info.email })
      setEmailSaved(true)
    } catch {
      setEmailError('Erro ao salvar — verifique se o e-mail já está em uso.')
    }
  }

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault()
    setPasswordError('')
    setPasswordSaved(false)
    try {
      await authApi.changePassword(currentPassword, newPassword)
      setPasswordSaved(true)
      setCurrentPassword('')
      setNewPassword('')
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Não foi possível trocar a senha.'
      setPasswordError(msg)
    }
  }

  return (
    <Layout currentView="profile" setView={setView} title={t('nav.profile')}>
      <div className="flex flex-col gap-6 max-w-lg">

        <div className="glass-card p-6">
          <h3 className="text-sm font-bold flex items-center gap-2 mb-5">
            <User size={14} className="text-brand-purple" />
            {t('profile.title')}
          </h3>

          <form onSubmit={handleSaveEmail} className="flex flex-col gap-4">
            <div className="space-y-1.5">
              <label className="text-[10px] text-slate-500 uppercase tracking-widest font-bold">
                {t('profile.username')}
              </label>
              <Field icon={User} type="text" value={username ?? ''} disabled />
            </div>

            <div className="space-y-1.5">
              <label className="text-[10px] text-slate-500 uppercase tracking-widest font-bold">
                {t('profile.email')}
              </label>
              <Field
                icon={Mail}
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            {emailError && <p className="text-xs text-red-400">{emailError}</p>}
            {emailSaved && (
              <p className="text-xs text-brand-neon flex items-center gap-1.5">
                <Check size={12} /> {t('profile.emailSaved')}
              </p>
            )}

            <button
              type="submit"
              className="self-start bg-brand-purple hover:bg-brand-purple/90 text-white font-semibold text-sm px-5 py-2 rounded-lg transition-all shadow-[0_0_20px_rgba(124,58,237,0.3)]"
            >
              {t('profile.saveEmail')}
            </button>
          </form>
        </div>

        <div className="glass-card p-6">
          <h3 className="text-sm font-bold flex items-center gap-2 mb-5">
            <Lock size={14} className="text-brand-purple" />
            {t('profile.changePassword')}
          </h3>

          <form onSubmit={handleChangePassword} className="flex flex-col gap-4">
            <div className="space-y-1.5">
              <label className="text-[10px] text-slate-500 uppercase tracking-widest font-bold">
                {t('profile.currentPassword')}
              </label>
              <Field
                icon={Lock}
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-[10px] text-slate-500 uppercase tracking-widest font-bold">
                {t('profile.newPassword')}
              </label>
              <Field
                icon={Lock}
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                autoComplete="new-password"
                minLength={8}
                required
              />
              <p className="text-[11px] text-slate-600">{t('profile.minLength')}</p>
            </div>

            {passwordError && <p className="text-xs text-red-400">{passwordError}</p>}
            {passwordSaved && (
              <p className="text-xs text-brand-neon flex items-center gap-1.5">
                <Check size={12} /> {t('profile.passwordChanged')}
              </p>
            )}

            <button
              type="submit"
              className="self-start bg-brand-purple hover:bg-brand-purple/90 text-white font-semibold text-sm px-5 py-2 rounded-lg transition-all shadow-[0_0_20px_rgba(124,58,237,0.3)]"
            >
              {t('profile.changePassword')}
            </button>
          </form>
        </div>

      </div>
    </Layout>
  )
}
