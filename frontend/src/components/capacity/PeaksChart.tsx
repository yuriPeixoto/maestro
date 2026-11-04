import { useTranslation } from 'react-i18next'
import ReactECharts from 'echarts-for-react'
import type { PeakMetric } from '../../services/api'
import { formatPercent } from '../../utils/format'
import { shortDate } from './capacityText'

interface TooltipParam {
  axisValue: string
  value: number
}

/** Each day's highest 5-minute average against the attention and critical limits. */
export default function PeaksChart({ peak, height }: { peak: PeakMetric; height: number }) {
  const { t } = useTranslation()

  if (peak.days.length === 0) {
    return <div className="flex items-center justify-center text-slate-500 text-sm" style={{ height }}>{t('capacity.peaks.noDataDetail')}</div>
  }

  const limitLine = (value: number, color: string, label: string) => ({
    yAxis: value,
    lineStyle: { color, type: 'dashed', width: 1, opacity: 0.8 },
    label: { formatter: label, color, fontSize: 10, position: 'insideEndTop' },
  })

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1e293b',
      borderColor: 'rgba(255,255,255,0.1)',
      textStyle: { color: '#e2e8f0', fontSize: 12 },
      formatter: (params: TooltipParam[]) =>
        `${params[0].axisValue}<br/>${t('capacity.peaks.tooltip')}: <b>${formatPercent(params[0].value)}</b>`,
    },
    grid: { left: 44, right: 16, top: 20, bottom: 28 },
    xAxis: {
      type: 'category',
      data: peak.days.map((d) => shortDate(d.date)),
      axisLabel: { color: '#64748b', fontSize: 10 },
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.07)' } },
    },
    yAxis: {
      type: 'value', min: 0, max: 100,
      axisLabel: { color: '#64748b', fontSize: 10, formatter: '{value}%' },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
    },
    series: [{
      name: t('capacity.peaks.tooltip'),
      type: 'line',
      data: peak.days.map((d) => d.peak),
      lineStyle: { color: '#8b5cf6', width: 2 },
      itemStyle: { color: '#8b5cf6' },
      symbol: 'circle',
      symbolSize: 6,
      markLine: {
        silent: true,
        symbol: 'none',
        data: [
          limitLine(peak.attention_pct, '#f59e0b', t('capacity.peaks.attentionLine', { value: peak.attention_pct })),
          limitLine(peak.critical_pct, '#f87171', t('capacity.peaks.criticalLine', { value: peak.critical_pct })),
        ],
      },
    }],
  }

  return <ReactECharts option={option} style={{ height }} notMerge />
}
