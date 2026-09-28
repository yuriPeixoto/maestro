import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Users as UsersIcon, Plus, Trash2 } from 'lucide-react'
import Layout from './Layout'
import type { ViewType } from '../App'
import { usersApi, type AccountUser } from '../services/api'
import { useAuthStore } from '../store/authStore'

interface UsersProps {
  setView: (view: ViewType) => void
}

const inputClass =
  'bg-brand-dark/80 border border-white/10 rounded-lg py-2 px-3 text-sm focus:outline-none focus:border-brand-purple/60 focus:ring-1 focus:ring-brand-purple/20 transition-all text-slate-100 placeholder-slate-600'

export default function Users({ setView }: UsersProps) {
  const { t } = useTranslation()
  const selfId = useAuthStore((s) => s.username)
  const [users, setUsers] = useState<AccountUser[]>([])
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  const reload = () => usersApi.list().then(setUsers)

  useEffect(() => {
    reload()
  }, [])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      await usersApi.create(username, email, password)
      setUsername('')
      setEmail('')
      setPassword('')
      reload()
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Erro ao criar usuário.'
      setError(msg)
    }
  }

  const handleDelete = async (u: AccountUser) => {
    if (u.username === selfId) return
    await usersApi.remove(u.id)
    reload()
  }

  return (
    <Layout currentView="users" setView={setView} title={t('nav.users')}>
      <div className="flex flex-col gap-6">

        <div>
          <h1 className="text-xl font-bold mb-1">{t('users.title')}</h1>
          <p className="text-xs text-slate-500">{t('users.subtitle')}</p>
        </div>

        <div className="glass-card p-6">
          <h3 className="text-sm font-bold flex items-center gap-2 mb-4">
            <Plus size={14} className="text-brand-purple" />
            {t('users.newUser')}
          </h3>
          <form onSubmit={handleCreate} className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-widest font-bold">{t('users.username')}</label>
              <input className={inputClass} value={username} onChange={(e) => setUsername(e.target.value)} required />
            </div>
            <div className="space-y-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-widest font-bold">{t('users.email')}</label>
              <input className={inputClass} type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </div>
            <div className="space-y-1">
              <label className="text-[10px] text-slate-500 uppercase tracking-widest font-bold">{t('users.password')}</label>
              <input className={inputClass} type="password" minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} required />
            </div>
            <button
              type="submit"
              className="bg-brand-purple hover:bg-brand-purple/90 text-white font-semibold text-sm px-5 py-2 rounded-lg transition-all shadow-[0_0_20px_rgba(124,58,237,0.3)]"
            >
              {t('users.create')}
            </button>
          </form>
          {error && <p className="text-xs text-red-400 mt-3">{error}</p>}
        </div>

        <div className="glass-card overflow-hidden">
          <div className="px-4 py-3 border-b border-white/5 bg-white/5">
            <h3 className="text-sm font-bold flex items-center gap-2">
              <UsersIcon size={14} className="text-brand-purple" />
              {t('users.title')} <span className="text-slate-500 font-normal">({users.length})</span>
            </h3>
          </div>
          <table className="w-full text-left">
            <thead className="text-[10px] text-slate-500 uppercase tracking-widest bg-brand-dark/20">
              <tr>
                <th className="px-4 py-2 font-medium">{t('users.username')}</th>
                <th className="px-4 py-2 font-medium">{t('users.email')}</th>
                <th className="px-4 py-2 font-medium">{t('users.createdAt')}</th>
                <th className="px-4 py-2 font-medium" />
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {users.map((u) => (
                <tr key={u.id} className="hover:bg-white/5 transition-colors">
                  <td className="px-4 py-2.5 text-sm font-mono text-slate-100">{u.username}</td>
                  <td className="px-4 py-2.5 text-sm font-mono text-slate-400">{u.email}</td>
                  <td className="px-4 py-2.5 text-xs font-mono text-slate-500">
                    {new Date(u.created_at).toLocaleDateString('pt-BR')}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    {u.username !== selfId && (
                      <button
                        onClick={() => handleDelete(u)}
                        className="text-slate-500 hover:text-red-400 transition-colors"
                        title={t('common.delete') ?? ''}
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                    {u.username === selfId && (
                      <span className="text-[10px] text-slate-600" title={t('users.cannotDeleteSelf') ?? ''}>—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

      </div>
    </Layout>
  )
}
