import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { useAbout } from '../hooks/useAbout'
import { useMe } from '../hooks/usePermissions'
import { authApi } from '../services/api'
import { unseenReleases } from '../utils/release'
import ReleaseNotes from './ReleaseNotes'

/** Shown once per account after an update: the releases it has not seen yet. */
export default function WhatsNewModal({ onSeeAll }: { onSeeAll: () => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { data: me } = useMe()
  const { data: about } = useAbout()
  const [closed, setClosed] = useState(false)

  if (closed || !me || !about) return null
  const pending = unseenReleases(about.releases, me.last_seen_version)
  if (pending.length === 0) return null

  const close = () => {
    setClosed(true)
    authApi.markReleaseSeen(about.version)
      .then(() => queryClient.invalidateQueries({ queryKey: ['me'] }))
      .catch(() => {
        // Not recorded: the notes come back on the next visit, which is the safe side.
      })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="whats-new-title"
        className="w-full max-w-lg rounded-2xl border border-white/10 bg-brand-slate shadow-2xl overflow-hidden"
      >
        <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-white/10">
          <h2 id="whats-new-title" className="text-base font-bold text-slate-100">{t('whatsNew.title')}</h2>
          <button
            type="button"
            onClick={close}
            aria-label={t('whatsNew.close')}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-100 hover:bg-white/5"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="max-h-[60vh] overflow-y-auto divide-y divide-white/5">
          {pending.map((release) => (
            <div key={release.version} className="px-5 py-4"><ReleaseNotes release={release} /></div>
          ))}
        </div>
        <div className="flex items-center justify-between gap-3 px-5 py-3.5 border-t border-white/10">
          <button type="button" onClick={() => { close(); onSeeAll() }} className="text-sm text-violet-300 hover:underline">
            {t('whatsNew.seeAll')}
          </button>
          <button
            type="button"
            onClick={close}
            className="px-4 py-2 rounded-lg bg-brand-purple text-white text-sm font-semibold hover:bg-brand-purple/90"
          >
            {t('whatsNew.ok')}
          </button>
        </div>
      </div>
    </div>
  )
}
