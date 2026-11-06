import { useTranslation } from 'react-i18next'
import type { UserRole } from '../../services/api'

const ROLE_STYLE: Record<UserRole, string> = {
  admin: 'bg-brand-purple/15 text-violet-300 border-brand-purple/35',
  operator: 'bg-sky-400/10 text-sky-300 border-sky-400/30',
  viewer: 'bg-slate-400/10 text-slate-300 border-slate-400/25',
}

export default function RoleBadge({ role, muted = false }: { role: UserRole; muted?: boolean }) {
  const { t } = useTranslation()
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full border text-[11px] font-bold whitespace-nowrap ${ROLE_STYLE[role]} ${muted ? 'opacity-60' : ''}`}
    >
      {t(`roles.${role}`)}
    </span>
  )
}
