import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown } from 'lucide-react'
import type { AccountUser, AuditEntry, AuditFilters } from '../../services/api'
import { useAuditLog } from '../../hooks/useUsers'
import {
  ACTION_GROUPS, actionLabel, actorKind, diffLines, eventTags, formatDateTime, targetLabel, whereFrom,
} from './auditFormat'
import { buttonGhost, fieldClass, labelClass } from './ui'

const OUTSIDE = 'outside'
const DEFAULT_RANGE_DAYS = 7
const MS_PER_DAY = 86_400_000

const isoDay = (date: Date) => {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 10)
}

/** The API takes instants: a day from the picker starts at local midnight, "until" includes its day. */
const dayStart = (day: string) => new Date(`${day}T00:00:00`).toISOString()
const nextDayStart = (day: string) => new Date(new Date(`${day}T00:00:00`).getTime() + MS_PER_DAY).toISOString()

const TAG_TONE = {
  bad: 'text-red-300',
  good: 'text-green-300',
  neutral: 'text-slate-300',
} as const

function WhatCell({ entry }: { entry: AuditEntry }) {
  const { t } = useTranslation()
  const label = actionLabel(entry, t)
  const lines = diffLines(entry, t)
  const tags = eventTags(entry, t)
  const refused = entry.action === 'auth.login_failed'

  const tagList = tags.map((tag) => (
    <span key={tag.text} className={`ml-1.5 px-2 py-0.5 rounded-md text-[11px] bg-white/5 ${TAG_TONE[tag.tone]}`}>{tag.text}</span>
  ))

  if (lines.length === 0) {
    return <span><b className={refused ? 'text-red-300' : ''}>{label}</b>{tagList}</span>
  }
  return (
    <details className="group">
      <summary className="cursor-pointer list-none inline-flex items-center gap-1 rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet-400 [&::-webkit-details-marker]:hidden">
        <b>{label}</b>
        <ChevronDown size={14} className="text-slate-400 transition-transform group-open:rotate-180" aria-hidden="true" />
        {tagList}
      </summary>
      <dl className="mt-2 font-mono text-xs leading-relaxed grid grid-cols-[auto_1fr] gap-x-2">
        {lines.map((line) => (
          <div key={line.field} className="contents">
            <dt className="text-slate-400">{line.label}:</dt>
            <dd>
              {line.before !== null && (
                <><del className="text-red-300">{line.before}</del><span className="text-slate-500" aria-hidden="true"> → </span></>
              )}
              <ins className="text-green-300 no-underline">{line.after}</ins>
            </dd>
          </div>
        ))}
      </dl>
    </details>
  )
}

function WhoCell({ entry }: { entry: AuditEntry }) {
  const { t } = useTranslation()
  const kind = actorKind(entry)
  if (kind === 'anonymous') return <span className="text-slate-400">{t('audit.anonymous')}</span>
  if (kind === 'account') return <span className="font-mono">{entry.actor}</span>
  return (
    <span>
      <span className="text-amber-200">{entry.actor}</span>
      <span className="block text-[11px] text-slate-400">{t('audit.outsideHint')}</span>
    </span>
  )
}

export default function AuditPanel({ users }: { users: AccountUser[] }) {
  const { t } = useTranslation()
  const today = new Date()
  const [who, setWho] = useState('')
  const [action, setAction] = useState('')
  const [from, setFrom] = useState(isoDay(new Date(today.getTime() - DEFAULT_RANGE_DAYS * MS_PER_DAY)))
  const [to, setTo] = useState(isoDay(today))

  const filters: Omit<AuditFilters, 'before_id' | 'limit'> = {
    ...(who === OUTSIDE ? { outside: true } : who ? { actor_user_id: Number(who) } : {}),
    ...(action ? { action } : {}),
    ...(from ? { since: dayStart(from) } : {}),
    ...(to ? { until: nextDayStart(to) } : {}),
  }
  const log = useAuditLog(filters, true)
  const entries = log.data?.pages.flatMap((page) => page.entries) ?? []
  const people = [...users].sort((a, b) => a.username.localeCompare(b.username))

  return (
    <section id="panel-audit" role="tabpanel" aria-labelledby="tab-audit" className="flex flex-col gap-4">
      <div className="grid gap-3 grid-cols-[repeat(auto-fit,minmax(180px,1fr))]">
        <div>
          <label className={labelClass} htmlFor="f-who">{t('audit.filters.who')}</label>
          <select id="f-who" className={fieldClass} value={who} onChange={(e) => setWho(e.target.value)}>
            <option value="">{t('audit.filters.everyone')}</option>
            {people.map((user) => <option key={user.id} value={user.id}>{user.username}</option>)}
            <option value={OUTSIDE}>{t('audit.filters.outside')}</option>
          </select>
        </div>
        <div>
          <label className={labelClass} htmlFor="f-what">{t('audit.filters.what')}</label>
          <select id="f-what" className={fieldClass} value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="">{t('audit.filters.everything')}</option>
            {ACTION_GROUPS.map((group) => (
              <option key={group} value={group}>{t(`audit.groups.${group.slice(0, -1)}`)}</option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelClass} htmlFor="f-from">{t('audit.filters.from')}</label>
          <input id="f-from" type="date" className={fieldClass} value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />
        </div>
        <div>
          <label className={labelClass} htmlFor="f-to">{t('audit.filters.to')}</label>
          <input id="f-to" type="date" className={fieldClass} value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
        </div>
      </div>

      <div className="glass-card overflow-x-auto hover:!shadow-none">
        <table className="w-full text-left">
          <thead className="text-[10px] text-slate-400 uppercase tracking-widest bg-brand-dark/40">
            <tr>
              <th className="px-4 py-2.5 font-bold">{t('audit.columns.when')}</th>
              <th className="px-4 py-2.5 font-bold">{t('audit.columns.who')}</th>
              <th className="px-4 py-2.5 font-bold">{t('audit.columns.what')}</th>
              <th className="px-4 py-2.5 font-bold">{t('audit.columns.target')}</th>
              <th className="px-4 py-2.5 font-bold hidden md:table-cell">{t('audit.columns.from')}</th>
            </tr>
          </thead>
          <tbody>
            {log.isPending && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-sm text-slate-400 border-t border-white/5">{t('common.loading')}</td></tr>
            )}
            {log.isError && (
              <tr><td colSpan={5} role="alert" className="px-4 py-8 text-center text-sm text-red-300 border-t border-white/5">{t('audit.loadError')}</td></tr>
            )}
            {log.isSuccess && entries.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-sm text-slate-400 border-t border-white/5">{t('audit.empty')}</td></tr>
            )}
            {entries.map((entry) => {
              const outside = actorKind(entry) === 'outside'
              return (
                <tr key={entry.id} className={`border-t border-white/5 align-top ${outside ? 'bg-amber-300/[0.04]' : 'hover:bg-white/[0.02]'}`}>
                  <td className="px-4 py-3 text-[13px] font-mono whitespace-nowrap" title={new Date(entry.occurred_at).toLocaleString()}>
                    {formatDateTime(entry.occurred_at)}
                  </td>
                  <td className="px-4 py-3 text-[13px]"><WhoCell entry={entry} /></td>
                  <td className="px-4 py-3 text-[13px]"><WhatCell entry={entry} /></td>
                  <td className="px-4 py-3 text-[13px]">{targetLabel(entry, t)}</td>
                  <td className="px-4 py-3 text-[13px] font-mono text-slate-400 hidden md:table-cell">{whereFrom(entry)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-t border-white/5 text-xs text-slate-400">
          <span>{t('audit.footnote')}</span>
          {log.hasNextPage && (
            <button type="button" className={`${buttonGhost} min-h-8 py-1.5`} disabled={log.isFetchingNextPage} onClick={() => log.fetchNextPage()}>
              {log.isFetchingNextPage ? t('common.loading') : t('audit.older')}
            </button>
          )}
        </div>
      </div>
    </section>
  )
}
