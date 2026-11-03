import { useTranslation } from 'react-i18next'

interface PaginationProps {
  page: number
  totalPages: number
  onChange: (page: number) => void
}

export default function Pagination({ page, totalPages, onChange }: PaginationProps) {
  const { t } = useTranslation()
  if (totalPages <= 1) return null

  return (
    <div className="px-4 py-2.5 border-t border-white/5 flex items-center justify-end gap-3 text-xs">
      <button
        onClick={() => onChange(page - 1)}
        disabled={page === 1}
        className="text-slate-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
      >
        {t('common.previous')}
      </button>
      <span className="font-mono text-slate-500">
        {t('common.pageOf', { page, total: totalPages })}
      </span>
      <button
        onClick={() => onChange(page + 1)}
        disabled={page === totalPages}
        className="text-slate-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
      >
        {t('common.next')}
      </button>
    </div>
  )
}
