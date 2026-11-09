import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { Loader2 } from 'lucide-react'
import Dialog from '../users/Dialog'
import Segmented from './Segmented'
import { useCreateMaintenance, useCreateSilence, useRulesAt } from '../../hooks/useAlerting'
import { serverName } from '../../hooks/useServerName'
import type { Place, ServerGroup } from '../../services/alertingApi'
import type { ServerStatus } from '../../types/server'
import { alertingError, buttonGhost, buttonPrimary, fieldClass, hintClass, labelClass, placeKey, ruleName } from './ui'

const DURATIONS = [30, 60, 240]
const NEXT_MORNING_HOUR = 8
const REASON_MAX = 500
const MINUTES_PER_HOUR = 60

function nextMorning(): Date {
  const at = new Date()
  at.setDate(at.getDate() + 1)
  at.setHours(NEXT_MORNING_HOUR, 0, 0, 0)
  return at
}

const durationLabel = (minutes: number, t: TFunction) =>
  minutes < MINUTES_PER_HOUR ? t('alerts.screen.quiet.min', { count: minutes }) : t('alerts.screen.quiet.hours', { count: minutes / MINUTES_PER_HOUR })

/** The local datetime-local value of a date (the input has no time zone). */
const localInput = (date: Date) => {
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return shifted.toISOString().slice(0, 16)
}

const MS_PER_HOUR = 3_600_000
const hoursFromNow = (hours: number) => new Date(Date.now() + hours * MS_PER_HOUR)

type Deadline = { minutes: number } | { morning: true } | { custom: string }

/** Silence a place, for one rule or all, for a while, with a reason. */
export function SilenceDialog({ servers, groups, initial, onClose }: {
  servers: ServerStatus[]
  groups: ServerGroup[]
  initial?: Place
  onClose: () => void
}) {
  const { t } = useTranslation()
  const create = useCreateSilence()
  const places: Place[] = [
    ...servers.map((s): Place => ({ scope: 'server', server_id: s.server_id })),
    ...groups.map((g): Place => ({ scope: 'group', group_id: g.group_id })),
    { scope: 'global' },
  ]
  const [where, setWhere] = useState(placeKey(initial ?? places[0]))
  const place = places.find((p) => placeKey(p) === where) ?? places[0]
  const { data: rules = [] } = useRulesAt(place, true)
  const { data: globalRules = [] } = useRulesAt({ scope: 'global' }, place.scope !== 'global')
  const choices = place.scope === 'global' ? rules : [...rules, ...globalRules]
  const [ruleId, setRuleId] = useState('')
  const [deadline, setDeadline] = useState<Deadline>({ minutes: 60 })
  const [reason, setReason] = useState('')

  const placeName = (p: Place) => {
    if (p.scope === 'global') return t('alerts.screen.place.global')
    if (p.scope === 'group') return t('alerts.screen.place.group', { name: groups.find((g) => g.group_id === p.group_id)?.name ?? '—' })
    const server = servers.find((s) => s.server_id === p.server_id)
    const name = server ? serverName(server) : null
    return name?.renamed ? `${name.display} (${name.hostname})` : (p.server_id ?? '')
  }

  const submitLabel = 'minutes' in deadline
    ? t('alerts.screen.quiet.silenceFor', { duration: durationLabel(deadline.minutes, t) })
    : t('alerts.screen.quiet.silence')

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    const ends = 'minutes' in deadline ? {}
      : 'morning' in deadline ? { ends_at: nextMorning().toISOString() } : { ends_at: new Date(deadline.custom).toISOString() }
    create.mutate({
      ...place, rule_id: ruleId || null, reason: reason.trim(),
      ...('minutes' in deadline ? { duration_minutes: deadline.minutes } : ends),
    }, { onSuccess: onClose })
  }

  const chip = (active: boolean) => `${buttonGhost} min-h-[30px] px-2.5 py-1 text-xs ${active ? 'border-violet-400/60 text-violet-100' : ''}`

  return (
    <Dialog
      title={t('alerts.screen.quiet.silenceTitle')}
      onClose={onClose}
      dismissible={!create.isPending}
      footer={(
        <>
          <button type="button" className={buttonGhost} onClick={onClose} disabled={create.isPending}>{t('common.cancel')}</button>
          <button type="submit" form="silence-form" className={buttonPrimary} disabled={create.isPending || !reason.trim()}>
            {create.isPending && <Loader2 className="w-4 h-4 animate-spin" aria-hidden />}{submitLabel}
          </button>
        </>
      )}
    >
      <form id="silence-form" onSubmit={submit}>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className={labelClass} htmlFor="silence-where">{t('alerts.screen.quiet.where')}</label>
            <select id="silence-where" className={fieldClass} value={where} onChange={(e) => { setWhere(e.target.value); setRuleId('') }}>
              {places.map((p) => <option key={placeKey(p)} value={placeKey(p)}>{placeName(p)}</option>)}
            </select>
          </div>
          <div>
            <label className={labelClass} htmlFor="silence-rule">{t('alerts.screen.quiet.rule')}</label>
            <select id="silence-rule" className={fieldClass} value={ruleId} onChange={(e) => setRuleId(e.target.value)}>
              <option value="">{t('alerts.screen.quiet.allRules')}</option>
              {choices.map((r) => <option key={r.rule_id} value={r.rule_id}>{ruleName(r, t)}</option>)}
            </select>
          </div>
        </div>
        <span className={`${labelClass} mt-4`}>{t('alerts.screen.quiet.howLong')}</span>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('alerts.screen.quiet.howLong')}>
          {DURATIONS.map((m) => (
            <button key={m} type="button" aria-pressed={'minutes' in deadline && deadline.minutes === m}
              className={chip('minutes' in deadline && deadline.minutes === m)} onClick={() => setDeadline({ minutes: m })}>
              {durationLabel(m, t)}
            </button>
          ))}
          <button type="button" aria-pressed={'morning' in deadline} className={chip('morning' in deadline)} onClick={() => setDeadline({ morning: true })}>
            {t('alerts.screen.quiet.untilMorning')}
          </button>
          <button type="button" aria-pressed={'custom' in deadline} className={chip('custom' in deadline)}
            onClick={() => setDeadline({ custom: localInput(hoursFromNow(2)) })}>
            {t('alerts.screen.quiet.choose')}
          </button>
        </div>
        {'custom' in deadline && (
          <input type="datetime-local" aria-label={t('alerts.screen.quiet.until')} className={`${fieldClass} mt-2 font-mono`}
            value={deadline.custom} onChange={(e) => setDeadline({ custom: e.target.value })} required />
        )}
        <p className={hintClass}>{t('alerts.screen.quiet.deadlineHint')}</p>
        <label className={`${labelClass} mt-4`} htmlFor="silence-reason">
          {t('alerts.screen.quiet.reason')} <span className="text-red-300" aria-hidden>*</span>
        </label>
        <textarea id="silence-reason" className={fieldClass} rows={2} required aria-required="true" maxLength={REASON_MAX}
          value={reason} onChange={(e) => setReason(e.target.value)} />
        <p className={hintClass}>{t('alerts.screen.quiet.reasonHint')}</p>
        {create.isError && <p role="alert" className="mt-2 text-xs text-red-300">{alertingError(create.error, t)}</p>}
      </form>
    </Dialog>
  )
}

const WEEKDAYS = [1, 2, 3, 4, 5, 6, 7]
const MAINTENANCE_DURATIONS = [30, 60, 120, 180, 240, 360, 480]
const DEFAULT_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone

/** Plan work on one server: once, or every week at a local time. */
export function MaintenanceDialog({ servers, onClose }: { servers: ServerStatus[]; onClose: () => void }) {
  const { t } = useTranslation()
  const create = useCreateMaintenance()
  const [serverId, setServerId] = useState(servers[0]?.server_id ?? '')
  const [weekly, setWeekly] = useState(true)
  const [days, setDays] = useState<number[]>([])
  const [start, setStart] = useState('02:00')
  const [duration, setDuration] = useState(180)
  const [until, setUntil] = useState('')
  const [zone, setZone] = useState(DEFAULT_ZONE)
  const [from, setFrom] = useState(() => localInput(hoursFromNow(1)))
  const [to, setTo] = useState(() => localInput(hoursFromNow(2)))
  const [reason, setReason] = useState('')

  const toggle = (day: number) => setDays((d) => (d.includes(day) ? d.filter((x) => x !== day) : [...d, day].sort()))

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    create.mutate(weekly
      ? { server_id: serverId, reason: reason.trim(), weekly: { weekdays: days, local_start: start, duration_minutes: duration, time_zone: zone.trim(), repeat_until: until || null } }
      : { server_id: serverId, reason: reason.trim(), starts_at: new Date(from).toISOString(), ends_at: new Date(to).toISOString() },
    { onSuccess: onClose })
  }

  return (
    <Dialog
      title={t('alerts.screen.quiet.maintenanceTitle')}
      onClose={onClose}
      dismissible={!create.isPending}
      footer={(
        <>
          <button type="button" className={buttonGhost} onClick={onClose} disabled={create.isPending}>{t('common.cancel')}</button>
          <button type="submit" form="maintenance-form" className={buttonPrimary}
            disabled={create.isPending || !reason.trim() || (weekly && days.length === 0)}>
            {create.isPending && <Loader2 className="w-4 h-4 animate-spin" aria-hidden />}{t('alerts.screen.quiet.plan')}
          </button>
        </>
      )}
    >
      <form id="maintenance-form" onSubmit={submit}>
        <label className={labelClass} htmlFor="maintenance-server">{t('alerts.screen.col.server')}</label>
        <select id="maintenance-server" className={fieldClass} value={serverId} onChange={(e) => setServerId(e.target.value)}>
          {servers.map((s) => {
            const name = serverName(s)
            return <option key={s.server_id} value={s.server_id}>{name.renamed ? `${name.display} (${name.hostname})` : name.display}</option>
          })}
        </select>
        <div className="my-3.5">
          <Segmented label={t('alerts.screen.quiet.frequency')}
            options={[{ value: 'once', label: t('alerts.screen.quiet.once') }, { value: 'weekly', label: t('alerts.screen.quiet.weekly') }]}
            value={weekly ? 'weekly' : 'once'} onChange={(v) => setWeekly(v === 'weekly')} />
        </div>
        {weekly ? (
          <>
            <span className={labelClass}>{t('alerts.screen.quiet.days')}</span>
            <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('alerts.screen.quiet.days')}>
              {WEEKDAYS.map((day) => (
                <button key={day} type="button" aria-pressed={days.includes(day)} aria-label={t(`alerts.screen.quiet.weekday.${day}`)}
                  onClick={() => toggle(day)}
                  className={`w-10 h-9 rounded-lg border text-xs font-bold transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet-400 ${
                    days.includes(day) ? 'bg-violet-500/20 text-violet-100 border-violet-500/50' : 'border-white/10 text-slate-400 hover:bg-white/5'
                  }`}>
                  {t(`alerts.screen.quiet.weekdayShort.${day}`)}
                </button>
              ))}
            </div>
            <div className="grid gap-3 sm:grid-cols-2 mt-3">
              <div>
                <label className={labelClass} htmlFor="maintenance-start">{t('alerts.screen.quiet.startsAt')}</label>
                <input id="maintenance-start" type="time" required className={`${fieldClass} font-mono`} value={start} onChange={(e) => setStart(e.target.value)} />
              </div>
              <div>
                <label className={labelClass} htmlFor="maintenance-duration">{t('alerts.screen.quiet.lasts')}</label>
                <select id="maintenance-duration" className={fieldClass} value={duration} onChange={(e) => setDuration(Number(e.target.value))}>
                  {MAINTENANCE_DURATIONS.map((m) => <option key={m} value={m}>{durationLabel(m, t)}</option>)}
                </select>
              </div>
              <div>
                <label className={labelClass} htmlFor="maintenance-until">{t('alerts.screen.quiet.repeatUntil')}</label>
                <input id="maintenance-until" type="date" className={`${fieldClass} font-mono`} value={until} onChange={(e) => setUntil(e.target.value)} />
              </div>
              <div>
                <label className={labelClass} htmlFor="maintenance-zone">{t('alerts.screen.quiet.zone')}</label>
                <input id="maintenance-zone" required className={`${fieldClass} font-mono`} value={zone} onChange={(e) => setZone(e.target.value)} />
              </div>
            </div>
          </>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className={labelClass} htmlFor="maintenance-from">{t('alerts.screen.quiet.from')}</label>
              <input id="maintenance-from" type="datetime-local" required className={`${fieldClass} font-mono`} value={from} onChange={(e) => setFrom(e.target.value)} />
            </div>
            <div>
              <label className={labelClass} htmlFor="maintenance-to">{t('alerts.screen.quiet.until')}</label>
              <input id="maintenance-to" type="datetime-local" required className={`${fieldClass} font-mono`} value={to} onChange={(e) => setTo(e.target.value)} />
            </div>
          </div>
        )}
        <label className={`${labelClass} mt-4`} htmlFor="maintenance-reason">
          {t('alerts.screen.quiet.reason')} <span className="text-red-300" aria-hidden>*</span>
        </label>
        <textarea id="maintenance-reason" className={fieldClass} rows={2} required aria-required="true" maxLength={REASON_MAX}
          value={reason} onChange={(e) => setReason(e.target.value)} />
        {create.isError && <p role="alert" className="mt-3 text-xs text-red-300">{alertingError(create.error, t)}</p>}
      </form>
    </Dialog>
  )
}
