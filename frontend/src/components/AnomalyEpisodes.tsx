import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAnomalyEpisodes } from '../hooks/useAnomalies'
import type { AnomalyEpisode, EpisodeDeviation } from '../services/api'
import { formatDecimal, formatMetricRange, formatMetricValue, metricLabel } from '../utils/format'

const RANGES = [
  { label: '24h', hours: 24 },
  { label: '7d', hours: 7 * 24 },
  { label: '30d', hours: 30 * 24 },
]
const SHOWN_AT_FIRST = 5
// A deviation this many spreads away is drawn as severe.
const SEVERE_Z = 10
// Room on the bar to the right of the largest of value and normal range.
const BAR_HEADROOM = 1.15
// A normal range under this share of the value reads as zero in the value's unit.
const NEAR_ZERO_SHARE = 0.01

const pad2 = (n: number) => String(n).padStart(2, '0')
const dayTime = (iso: string) => {
  const d = new Date(iso)
  return `${pad2(d.getDate())}/${pad2(d.getMonth() + 1)} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`
}

function DeviationRow({ deviation }: { deviation: EpisodeDeviation }) {
  const { t } = useTranslation()
  const { metric, value, z, normal_low, normal_high } = deviation
  const largest = Math.max(value, normal_high)
  const scale = largest * BAR_HEADROOM || 1
  const pct = (v: number) => Math.min(100, Math.max(0, (v / scale) * 100))
  const bandLeft = pct(normal_low)
  const bandWidth = Math.max(pct(normal_high) - bandLeft, 1.5)
  const zText = `${z > 0 ? '+' : '−'}${formatDecimal(Math.abs(z)).replace(/[,.]0$/, '')}`

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] md:grid-cols-[150px_minmax(0,1fr)_auto] gap-x-3 gap-y-1 items-center">
      <span className="text-sm text-slate-200">{metricLabel(metric, t)}</span>
      <span className="relative hidden md:block h-2 rounded bg-white/10" aria-hidden="true">
        <span
          className="absolute inset-y-0 rounded bg-emerald-400/40"
          style={{ left: `${bandLeft}%`, width: `${bandWidth}%` }}
        />
        <span
          className={`absolute -top-[3px] w-3.5 h-3.5 rounded-full border-2 border-brand-slate -translate-x-1/2 ${
            Math.abs(z) >= SEVERE_Z ? 'bg-red-400' : 'bg-amber-400'
          }`}
          style={{ left: `${pct(value)}%` }}
        />
      </span>
      <span className="text-xs font-mono text-slate-400 whitespace-nowrap">
        <b className="text-slate-200 font-semibold">{formatMetricValue(metric, value, largest)}</b>
        {' · '}
        {normal_high < largest * NEAR_ZERO_SHARE
          ? t('anomalies.normalNearZero')
          : t('anomalies.normal', { range: formatMetricRange(metric, normal_low, normal_high, largest) })}
        {' · z '}
        {zText}
      </span>
    </div>
  )
}

function EpisodeItem({ episode, onSelect }: { episode: AnomalyEpisode; onSelect: (e: AnomalyEpisode) => void }) {
  const { t } = useTranslation()
  return (
    <button
      type="button"
      onClick={() => onSelect(episode)}
      className={`w-full text-left grid grid-cols-1 sm:grid-cols-[112px_minmax(0,1fr)] gap-3 p-3 rounded-xl border bg-white/[0.03] hover:bg-white/[0.06] transition-colors ${
        episode.ongoing ? 'border-amber-500/40' : 'border-white/10'
      }`}
    >
      <span className="flex sm:flex-col gap-2 sm:gap-0.5 items-baseline sm:items-start">
        <span className="font-mono text-sm text-slate-200">{dayTime(episode.started_at)}</span>
        <span className="font-mono text-[11px] text-slate-500">{t('anomalies.minutes', { count: episode.minutes })}</span>
        {episode.ongoing && (
          <span className="mt-1 text-[10px] font-mono px-2 py-0.5 rounded-full border border-amber-500/40 bg-amber-500/10 text-amber-400">
            {t('anomalies.ongoing')}
          </span>
        )}
      </span>
      <span className="grid gap-1.5 min-w-0">
        {episode.deviations.map((d) => <DeviationRow key={d.metric} deviation={d} />)}
        {episode.deviations.length === 0 && <span className="text-xs text-slate-500">{t('anomalies.noDetail')}</span>}
      </span>
    </button>
  )
}

export default function AnomalyEpisodes({
  serverId,
  onSelect,
}: {
  serverId: string
  onSelect: (episode: AnomalyEpisode) => void
}) {
  const { t } = useTranslation()
  const [hours, setHours] = useState(7 * 24)
  const [showAll, setShowAll] = useState(false)
  const { data: episodes, isLoading } = useAnomalyEpisodes(serverId, hours)

  const list = episodes ?? []
  const ongoing = list.filter((e) => e.ongoing).length
  const longest = list.reduce((max, e) => Math.max(max, e.minutes), 0)
  const shown = showAll ? list : list.slice(0, SHOWN_AT_FIRST)

  return (
    <section className="rounded-2xl border border-white/10 bg-brand-slate p-5 space-y-4" aria-labelledby="anomaly-episodes-title">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="anomaly-episodes-title" className="text-sm font-bold text-slate-200">{t('anomalies.title')}</h2>
          <p className="text-xs text-slate-500 mt-0.5">{t('anomalies.subtitle')}</p>
        </div>
        <div className="flex gap-1">
          {RANGES.map((r) => (
            <button
              key={r.label}
              type="button"
              onClick={() => { setHours(r.hours); setShowAll(false) }}
              className={`px-3 py-1 text-xs font-mono rounded-full border transition-colors ${
                hours === r.hours
                  ? 'bg-brand-purple/20 border-brand-purple/50 text-brand-purple'
                  : 'border-white/10 text-slate-400 hover:text-slate-200'
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <p className="text-sm text-slate-500">{t('common.loading')}</p>
      ) : list.length === 0 ? (
        <p className="text-sm text-slate-400">{t('anomalies.none')}</p>
      ) : (
        <>
          <p className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-slate-400">
            <span><b className="font-mono text-slate-200">{list.length}</b> {t('anomalies.episodes', { count: list.length })}</span>
            <span><b className="font-mono text-slate-200">{ongoing}</b> {t('anomalies.ongoingCount', { count: ongoing })}</span>
            <span>{t('anomalies.longest')} <b className="font-mono text-slate-200">{t('anomalies.minutes', { count: longest })}</b></span>
          </p>
          <div className="grid gap-2">
            {shown.map((e) => <EpisodeItem key={e.started_at} episode={e} onSelect={onSelect} />)}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
            <span>{t('anomalies.hint')}</span>
            {list.length > SHOWN_AT_FIRST && (
              <button type="button" onClick={() => setShowAll((v) => !v)} className="text-brand-purple hover:underline">
                {showAll ? t('anomalies.showFewer') : t('anomalies.showAll', { count: list.length })}
              </button>
            )}
          </div>
        </>
      )}
    </section>
  )
}
