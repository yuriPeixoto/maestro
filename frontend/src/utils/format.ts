import type { TFunction } from 'i18next'

const SECONDS_PER_MINUTE = 60
const SECONDS_PER_HOUR = 3_600
const SECONDS_PER_DAY = 86_400

export const formatPercent = (value: number | null | undefined): string =>
  value == null ? '—' : `${Math.round(value)}%`

export function relativeTime(iso: string, t: TFunction): string {
  const elapsed = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (elapsed < SECONDS_PER_MINUTE) return t('common.relative.seconds', { count: elapsed })
  if (elapsed < SECONDS_PER_HOUR)   return t('common.relative.minutes', { count: Math.floor(elapsed / SECONDS_PER_MINUTE) })
  if (elapsed < SECONDS_PER_DAY)    return t('common.relative.hours',   { count: Math.floor(elapsed / SECONDS_PER_HOUR) })
  return t('common.relative.days', { count: Math.floor(elapsed / SECONDS_PER_DAY) })
}

export const metricLabel = (metricName: string, t: TFunction): string =>
  t(`metrics.${metricName}`, { defaultValue: metricName })
