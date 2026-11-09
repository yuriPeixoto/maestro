import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { serverMatches, serverName } from '../../hooks/useServerName'
import type { ServerStatus } from '../../types/server'
import { fieldClass } from './ui'

/** Search a server by nickname, label or hostname (a combobox with a list of matches). */
export default function ServerPicker({
  servers, value, onChange,
}: {
  servers: ServerStatus[]
  value: string
  onChange: (serverId: string) => void
}) {
  const { t } = useTranslation()
  const listId = useId()
  const current = servers.find((s) => s.server_id === value)
  const [query, setQuery] = useState<string | null>(null)
  const [active, setActive] = useState(0)
  const open = query !== null
  const matches = servers.filter((s) => serverMatches(s, query ?? ''))

  const choose = (server: ServerStatus) => {
    onChange(server.server_id)
    setQuery(null)
  }

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      if (!open) setQuery('')
      const step = event.key === 'ArrowDown' ? 1 : -1
      setActive((i) => (matches.length ? (i + step + matches.length) % matches.length : 0))
    } else if (event.key === 'Enter' && open && matches[active]) {
      event.preventDefault()
      choose(matches[active])
    } else if (event.key === 'Escape' && open) {
      event.preventDefault()
      setQuery(null)
    }
  }

  return (
    <div className="relative min-w-[280px]">
      <label htmlFor={`${listId}-input`} className="sr-only">{t('alerts.screen.col.server')}</label>
      <input
        id={`${listId}-input`}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-activedescendant={open && matches[active] ? `${listId}-${active}` : undefined}
        autoComplete="off"
        className={fieldClass}
        placeholder={t('alerts.screen.picker.placeholder')}
        value={query ?? (current ? serverName(current).display : '')}
        onFocus={() => { setQuery(''); setActive(0) }}
        onChange={(e) => { setQuery(e.target.value); setActive(0) }}
        onBlur={() => setTimeout(() => setQuery(null), 150)}
        onKeyDown={handleKeyDown}
      />
      {open && (
        <ul id={listId} role="listbox" className="absolute z-20 left-0 right-0 top-11 m-0 p-1.5 list-none rounded-xl border border-white/10 bg-brand-slate shadow-2xl max-h-72 overflow-auto">
          {matches.length === 0 && <li className="px-2.5 py-2 text-sm text-slate-400">{t('alerts.screen.picker.none')}</li>}
          {matches.map((server, index) => {
            const name = serverName(server)
            const details = [server.server_id, name.display !== server.label ? server.label : null, server.group_name]
              .filter(Boolean).join(' · ')
            return (
              <li
                key={server.server_id}
                id={`${listId}-${index}`}
                role="option"
                aria-selected={server.server_id === value}
                onMouseDown={(e) => { e.preventDefault(); choose(server) }}
                className={`px-2.5 py-2 rounded-lg cursor-pointer ${index === active ? 'bg-violet-500/15' : 'hover:bg-white/5'}`}
              >
                <span className="font-semibold text-slate-100">{name.display}</span>
                <span className="block mt-0.5 text-[11px] text-slate-400 font-mono">{details}</span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
