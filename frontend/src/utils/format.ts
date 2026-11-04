import type { TFunction } from 'i18next'
import i18n from '../i18n'
import type { ServerHealthSnapshot } from '../services/api'

const SECONDS_PER_MINUTE = 60
const SECONDS_PER_HOUR = 3_600
const SECONDS_PER_DAY = 86_400

const ONE_DECIMAL = { minimumFractionDigits: 1, maximumFractionDigits: 1 }

export const formatDecimal = (value: number): string => value.toLocaleString(i18n.language, ONE_DECIMAL)

export const formatPercent = (value: number | null | undefined): string =>
  value == null ? '—' : `${formatDecimal(value)}%`

export function headlineText(snapshot: ServerHealthSnapshot, t: TFunction): string {
  const { value, ...params } = snapshot.headline_params
  const options: Record<string, number | string> = value == null ? params : { ...params, value: formatDecimal(value) }
  return t(`health.headline.${snapshot.headline_code}`, options)
}

export function relativeTime(iso: string, t: TFunction): string {
  const elapsed = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (elapsed < SECONDS_PER_MINUTE) return t('common.relative.seconds', { count: elapsed })
  if (elapsed < SECONDS_PER_HOUR)   return t('common.relative.minutes', { count: Math.floor(elapsed / SECONDS_PER_MINUTE) })
  if (elapsed < SECONDS_PER_DAY)    return t('common.relative.hours',   { count: Math.floor(elapsed / SECONDS_PER_HOUR) })
  return t('common.relative.days', { count: Math.floor(elapsed / SECONDS_PER_DAY) })
}

export const metricLabel = (metricName: string, t: TFunction): string =>
  t(`metrics.${metricName}`, { defaultValue: metricName })

export const HEARTBEAT_AGE_METRIC = 'heartbeat_age_seconds'

const SECONDS_SHOWN_UP_TO = 2 * SECONDS_PER_MINUTE
const MINUTES_SHOWN_UP_TO = 2 * SECONDS_PER_HOUR

export function formatDuration(seconds: number): string {
  if (seconds < SECONDS_SHOWN_UP_TO) return `${Math.round(seconds)} s`
  if (seconds < MINUTES_SHOWN_UP_TO) return `${Math.round(seconds / SECONDS_PER_MINUTE)} min`
  return `${formatDecimal(seconds / SECONDS_PER_HOUR)} h`
}

const RATE_UNITS = ['B/s', 'KB/s', 'MB/s', 'GB/s']
const BYTES_PER_UNIT = 1024

/** The rate unit that keeps `bytesPerSec` between 1 and 1024. */
function rateUnit(bytesPerSec: number): number {
  let unit = 0
  let value = Math.abs(bytesPerSec)
  while (value >= BYTES_PER_UNIT && unit < RATE_UNITS.length - 1) {
    value /= BYTES_PER_UNIT
    unit += 1
  }
  return unit
}

const inUnit = (bytesPerSec: number, unit: number) => formatDecimal(bytesPerSec / BYTES_PER_UNIT ** unit)

/** A metric value with its unit: %, B/s to GB/s, or a plain count. `unitFrom` picks the rate unit. */
export function formatMetricValue(metricName: string, value: number, unitFrom: number = value): string {
  if (metricName.endsWith('_percent')) return formatPercent(value)
  if (metricName.endsWith('_per_sec')) {
    const unit = rateUnit(unitFrom)
    return `${inUnit(value, unit)} ${RATE_UNITS[unit]}`
  }
  return Math.round(value).toLocaleString(i18n.language)
}

/** A "normal" range in one unit: "5,4–8,2%", "0,2–0,4 MB/s". `unitFrom` picks the rate unit. */
export function formatMetricRange(metricName: string, low: number, high: number, unitFrom: number = high): string {
  if (metricName.endsWith('_percent')) return `${formatDecimal(low)}–${formatDecimal(high)}%`
  if (metricName.endsWith('_per_sec')) {
    const unit = rateUnit(unitFrom)
    return `${inUnit(low, unit)}–${inUnit(high, unit)} ${RATE_UNITS[unit]}`
  }
  return `${Math.round(low).toLocaleString(i18n.language)}–${Math.round(high).toLocaleString(i18n.language)}`
}

/** A rule's value with its unit: percent metrics get %, the heartbeat age a duration. */
export function formatRuleValue(metricName: string, value: number | null | undefined): string {
  if (value == null) return '—'
  if (metricName === HEARTBEAT_AGE_METRIC) return formatDuration(value)
  if (metricName.endsWith('_percent')) return formatPercent(value)
  return formatDecimal(value)
}
