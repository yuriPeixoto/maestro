import { useTranslation } from 'react-i18next'
import type { Release } from '../services/api'
import { notesFor, releaseDate } from '../utils/release'

/** "**Bold.** rest" -> bold lead-in; notes use no other markup. */
function NoteLine({ text }: { text: string }) {
  const pieces = text.split(/\*\*(.+?)\*\*/g)
  return (
    <li className="grid grid-cols-[14px_minmax(0,1fr)] gap-2 text-sm text-slate-300">
      <span className="mt-2 w-1.5 h-1.5 rounded-full bg-brand-purple" aria-hidden="true" />
      <span>{pieces.map((piece, i) => (i % 2 ? <b key={i} className="text-slate-100 font-semibold">{piece}</b> : piece))}</span>
    </li>
  )
}

export default function ReleaseNotes({ release }: { release: Release }) {
  const { i18n } = useTranslation()
  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-baseline gap-3">
        <span className="font-mono font-semibold text-violet-300">{release.version}</span>
        <span className="text-xs text-slate-500">{releaseDate(release.date, i18n.language)}</span>
      </div>
      <ul className="space-y-2">
        {notesFor(release, i18n.language).map((line) => <NoteLine key={line} text={line} />)}
      </ul>
    </div>
  )
}
