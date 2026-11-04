import type { TFunction } from 'i18next'
import i18n from '../../i18n'
import type { PeakMetric, RunwayMetric } from '../../services/api'
import { formatDecimal, formatPercent, metricLabel } from '../../utils/format'

const DAYS_PER_MONTH = 30
const DAYS_PER_YEAR = 365
// Below this, a runway reads better in days than in months.
const RUNWAY_DAYS_SHOWN_UP_TO = 60

const pad2 = (n: number) => String(n).padStart(2, '0')

/** "29/10" from "2026-10-29". */
export const shortDate = (isoDate: string) => {
  const [, month, day] = isoDate.split('-')
  return `${pad2(Number(day))}/${pad2(Number(month))}`
}

/** "12 dias", "3 meses", "mais de 1 ano", "mais de 2 anos". */
export function runwayLength(days: number, t: TFunction): string {
  if (days >= 2 * DAYS_PER_YEAR) return t('capacity.disk.overYears', { count: 2 })
  if (days >= DAYS_PER_YEAR) return t('capacity.disk.overYears', { count: 1 })
  if (days > RUNWAY_DAYS_SHOWN_UP_TO) return t('capacity.disk.months', { count: Math.round(days / DAYS_PER_MONTH) })
  return t('capacity.disk.days', { count: days })
}

/** Big line of the disk card: how long until the threshold at the current pace. */
export function diskHeadline(disk: RunwayMetric, threshold: number, t: TFunction): string {
  if (disk.status === 'no_data') return t('capacity.disk.noForecast')
  if (disk.current_value == null) return t('capacity.disk.noRecent')
  if (disk.days_to_threshold === 0) return t('capacity.disk.already', { threshold })
  if (disk.days_to_threshold_at_trend == null) return t('capacity.disk.notRising')
  return runwayLength(disk.days_to_threshold_at_trend, t)
}

/** "Hoje em 47,4%, subindo 0,04 pp/dia desde o degrau de 27/10." */
export function diskDetail(disk: RunwayMetric, t: TFunction): string {
  const now = disk.current_value == null ? '—' : formatPercent(disk.current_value)
  const perDay = disk.trend_per_day ?? 0
  if (perDay <= 0) return t('capacity.disk.detailFlat', { value: now })
  const rate = perDay.toLocaleString(i18n.language, { maximumFractionDigits: 2 })
  return disk.level_shift_on
    ? t('capacity.disk.detailSinceShift', { value: now, rate, date: shortDate(disk.level_shift_on) })
    : t('capacity.disk.detail', { value: now, rate })
}

/** Sentence above the disk chart. */
export function diskSentence(disk: RunwayMetric, threshold: number, t: TFunction): string {
  if (disk.current_value == null) return t('capacity.sentence.noValue', { metric: metricLabel(disk.metric_name, t).toLowerCase() })
  const value = formatPercent(disk.current_value)
  const perDay = disk.trend_per_day ?? 0
  if (disk.status === 'no_data') return `${t('capacity.sentence.value', { metric: metricLabel(disk.metric_name, t), value })} ${t('capacity.sentence.noForecast')}`
  if (perDay <= 0) return t('capacity.disk.sentenceFlat', { value })
  const perMonth = formatDecimal(perDay * DAYS_PER_MONTH)
  const when = disk.days_to_threshold_at_trend == null ? '—' : runwayLength(disk.days_to_threshold_at_trend, t)
  return t('capacity.disk.sentence', { value, perMonth, threshold, when })
}

/** Big line of a CPU or memory card. */
export function peakHeadline(peak: PeakMetric, t: TFunction): string {
  if (peak.status === 'no_data' || peak.headroom_pct == null) return t('capacity.peaks.noData')
  if (peak.headroom_pct <= 0) return t('capacity.peaks.overLimit')
  return t('capacity.peaks.headroom', { points: formatDecimal(peak.headroom_pct).replace(/[,.]0$/, '') })
}

export function peakDetail(peak: PeakMetric, days: number, t: TFunction): string {
  if (!peak.worst) return t('capacity.peaks.noDataDetail')
  return t('capacity.peaks.detail', {
    date: shortDate(peak.worst.date),
    peak: formatPercent(peak.worst.peak),
    critical: formatPercent(peak.critical_pct),
    days,
    count: peak.minutes_above_critical,
  })
}

export function peakSentence(peak: PeakMetric, days: number, t: TFunction): string {
  const metric = metricLabel(peak.metric_name, t)
  if (!peak.worst || peak.headroom_pct == null) return t('capacity.sentence.noValue', { metric: metric.toLowerCase() })
  const base = peak.headroom_pct > 0
    ? t('capacity.peaks.sentenceBelow', {
      days, date: shortDate(peak.worst.date), metric, peak: formatPercent(peak.worst.peak),
      points: formatDecimal(peak.headroom_pct).replace(/[,.]0$/, ''), critical: formatPercent(peak.critical_pct),
    })
    : t('capacity.peaks.sentenceAbove', {
      days, metric, critical: formatPercent(peak.critical_pct), count: peak.minutes_above_critical,
    })
  return `${base} ${t(`capacity.peaks.trend.${peak.trend}`)}`
}
