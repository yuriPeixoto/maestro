import { useTranslation } from 'react-i18next'
import ReactECharts from 'echarts-for-react'
import i18n from '../../i18n'
import { useForecast, useForecastHistory } from '../../hooks/useForecasts'
import type { CollectionProgress } from '../../services/api'
import { shortDate } from './capacityText'

interface AxisTooltipParam {
  axisValue: string
  value: number | null
  seriesName: string
  color: string
}

const HISTORY_DAYS = 30
// Space above and below the data, in percentage points, so the line does not touch the edges.
const Y_MARGIN = 1

/** Disk usage: daily averages, the trend since the last level shift, and its likely range. */
export default function ForecastChart({
  serverId, metric, collection,
}: { serverId: string; metric: string; collection: CollectionProgress | undefined }) {
  const { t } = useTranslation()
  const { data: history } = useForecastHistory(serverId, metric, HISTORY_DAYS)
  const { data: forecast, isError, isLoading } = useForecast(serverId, metric)

  const placeholder = (text: string) => (
    <div className="flex items-center justify-center h-64 text-slate-500 text-sm">{text}</div>
  )
  if (isLoading) return placeholder(t('common.loading'))
  if (isError || !forecast || forecast.status === 'error') return placeholder(t('capacity.noForecast'))
  if (forecast.status === 'insufficient_data') {
    return placeholder(t('capacity.insufficientData', {
      min: collection?.min_days,
      count: collection ? Math.max(collection.min_days - collection.days_collected, 0) : 0,
    }))
  }

  const hist = history ?? []
  const histDates = hist.map((p) => shortDate(p.date))
  const fcDates = forecast.points.map((p) => shortDate(p.date))
  const allDates = [...histDates, ...fcDates]
  const lastValue = hist.length ? hist[hist.length - 1].avg_value : null

  // The forecast line starts at the last measured day so the two lines join.
  const nulls = (n: number) => Array(n).fill(null)
  const histPadded = [...hist.map((p) => p.avg_value), ...nulls(fcDates.length)]
  const join = hist.length ? [...nulls(hist.length - 1), lastValue] : []
  const fcPadded = [...join, ...forecast.points.map((p) => p.yhat)]
  const lowerPadded = [...join, ...forecast.points.map((p) => Math.max(p.yhat_lower, 0))]
  const bandPadded = [...(hist.length ? [...nulls(hist.length - 1), 0] : []),
    ...forecast.points.map((p) => p.yhat_upper - Math.max(p.yhat_lower, 0))]

  const values = [...hist.map((p) => p.avg_value), ...forecast.points.flatMap((p) => [p.yhat_lower, p.yhat_upper])]
  const yMin = Math.max(0, Math.floor(Math.min(...values) - Y_MARGIN))
  const yMax = Math.min(100, Math.ceil(Math.max(...values) + Y_MARGIN))

  const shiftLabel = forecast.level_shift_on ? shortDate(forecast.level_shift_on) : null
  const shiftMark = shiftLabel && histDates.includes(shiftLabel)
    ? [{
      xAxis: shiftLabel,
      lineStyle: { color: '#f59e0b', type: 'dashed', width: 1 },
      label: { formatter: t('capacity.chart.shift', { date: shiftLabel }), color: '#f59e0b', fontSize: 10, position: 'end' },
    }]
    : []

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1e293b',
      borderColor: 'rgba(255,255,255,0.1)',
      textStyle: { color: '#e2e8f0', fontSize: 12 },
      formatter: (params: AxisTooltipParam[]) => {
        const lines = params
          .filter((p) => p.value != null && !p.seriesName.startsWith('_'))
          .map((p) => `<span style="color:${p.color}">●</span> ${p.seriesName}: <b>${
            (p.value as number).toLocaleString(i18n.language, { maximumFractionDigits: 2 })}%</b>`)
        return `<div style="font-size:11px;line-height:1.8">${params[0]?.axisValue}<br/>${lines.join('<br/>')}</div>`
      },
    },
    grid: { left: 48, right: 24, top: 28, bottom: 32 },
    xAxis: {
      type: 'category',
      data: allDates,
      axisLabel: { color: '#64748b', fontSize: 10, interval: Math.floor(allDates.length / 8) },
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.07)' } },
    },
    yAxis: {
      type: 'value', min: yMin, max: yMax,
      axisLabel: { color: '#64748b', fontSize: 10, formatter: '{value}%' },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
    },
    series: [
      {
        name: t('capacity.chart.historical'), type: 'line', data: histPadded, symbol: 'none',
        lineStyle: { color: '#8b5cf6', width: 2 }, itemStyle: { color: '#8b5cf6' },
        markLine: { silent: true, symbol: 'none', data: shiftMark },
      },
      {
        name: t('capacity.chart.forecast'), type: 'line', data: fcPadded, symbol: 'none',
        lineStyle: { color: '#c4b5fd', width: 2, type: 'dashed' }, itemStyle: { color: '#c4b5fd' },
      },
      {
        name: '_lower', type: 'line', data: lowerPadded, symbol: 'none', stack: 'band',
        lineStyle: { opacity: 0 }, areaStyle: { opacity: 0 }, tooltip: { show: false },
      },
      {
        name: t('capacity.chart.confidence'), type: 'line', data: bandPadded, symbol: 'none', stack: 'band',
        lineStyle: { opacity: 0 }, areaStyle: { color: '#8b5cf6', opacity: 0.18 }, tooltip: { show: false },
      },
    ],
    legend: {
      data: [t('capacity.chart.historical'), t('capacity.chart.forecast'), t('capacity.chart.confidence')],
      textStyle: { color: '#94a3b8', fontSize: 11 }, top: 0, right: 0, itemWidth: 16, itemHeight: 2,
    },
  }

  return <ReactECharts option={option} style={{ height: 300 }} notMerge />
}
