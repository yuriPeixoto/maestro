import { useTranslation } from 'react-i18next'
import { Check, Minus } from 'lucide-react'
import { useRolesMatrix } from '../../hooks/useUsers'

export default function RolesPanel() {
  const { t } = useTranslation()
  const { data: matrix, isPending, isError } = useRolesMatrix(true)

  return (
    <section id="panel-roles" role="tabpanel" aria-labelledby="tab-roles" className="flex flex-col gap-3">
      <div className="glass-card overflow-x-auto hover:!shadow-none">
        {isPending && <p className="px-4 py-8 text-center text-sm text-slate-400">{t('common.loading')}</p>}
        {isError && <p role="alert" className="px-4 py-8 text-center text-sm text-red-300">{t('roles.loadError')}</p>}
        {matrix && (
          <table className="w-full text-left">
            <thead className="text-[10px] text-slate-400 uppercase tracking-widest bg-brand-dark/40">
              <tr>
                <th className="px-4 py-2.5 font-bold">{t('roles.matrix.what')}</th>
                {matrix.roles.map(({ role }) => (
                  <th key={role} className="px-4 py-2.5 font-bold text-center">{t(`roles.${role}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {matrix.permissions.map((permission) => (
                <tr key={permission} className="border-t border-white/5">
                  <td className="px-4 py-3 text-[13px]">{t(`roles.permissions.${permission.replace('.', '_')}`, { defaultValue: permission })}</td>
                  {matrix.roles.map(({ role, permissions }) => (
                    <td key={role} className="px-4 py-3 text-center">
                      {permissions.includes(permission) ? (
                        <Check size={16} className="inline text-green-300" aria-label={t('roles.matrix.allowed')} />
                      ) : (
                        <Minus size={16} className="inline text-slate-500" aria-label={t('roles.matrix.notAllowed')} />
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <p className="text-xs text-slate-400 leading-relaxed">{t('roles.matrix.footnote')}</p>
    </section>
  )
}
