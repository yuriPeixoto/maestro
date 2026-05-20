import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import ReactECharts from 'echarts-for-react'
import { TrendingUp, AlertTriangle, CheckCircle, XCircle, ChevronDown } from 'lucide-react'
import Layout from './Layout'
import type { ViewType } from '../App'
import { useServers } from '../hooks/useServers'
import { useForecast, useForecastHistory, useRunway } from '../hooks/useForecasts'
import type { RunwayMetric } from '../services/api'

interface CapacityPlanningProps {
  setView: (view: ViewType) => void
}

const METRICS = ['disk_usage_percent', 'memory_usage_percent', 'cpu_usage_percent'] as const
type Metric = typeof METRICS[number]

// ── Runway card ───────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<string, { border: string; bg: string; text: string; icon: React.ReactNode }> = {
  safe:     { border: 'border-emerald-500/30', bg: 'bg-emerald-500/8',  text: 'text-emerald-400', icon: <CheckCircle  className="w-4 h-4" /> },
  watch:    { border: 'border-amber-500/30',   bg: 'bg-amber-500/8',   text: 'text-amber-400',   icon: <AlertTriangle className="w-4 h-4" /> },
  critical: { border: 'border-red-500/30',     bg: 'bg-red-500/8',     text: 'text-red-400',     icon: <XCircle       className="w-4 h-4" /> },
  no_data:  { border: 'border-white/10',       bg: 'bg-white/3',       text: 'text-slate-500',   icon: <TrendingUp    className="w-4 h-4" /> },
}

function RunwayCard({ metric, threshold }: { metric: RunwayMetric; threshold: number }) {
  const { t } = useTranslation()
  const s = STATUS_STYLES[metric.status] ?? STATUS_STYLES.no_data
  const metricKey = `capacity.tabs.${metric.metric_name}` as const

  const runwayLabel = () => {
    if (metric.status === 'no_data') return t('capacity.runwayCard.noData')
    if (metric.days_to_threshold === null) return t('capacity.runwayCard.never')
    return t('capacity.runwayCard.daysTo_other', { count: metric.days_to_threshold, threshold })
  }

  return (
    <div className={`flex flex-col gap-2 p-4 rounded-xl border ${s.border} ${s.bg}`}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-mono text-slate-400 uppercase tracking-widest">
          {t(metricKey as any)}
        </span>
        <span className={`${s.text}`}>{s.icon}</span>
      </div>
      <p className={`text-lg font-bold font-mono ${s.text}`}>{runwayLabel()}</p>
      <p className="text-[11px] text-slate-500">
        {t(`capacity.status.${metric.status}`)}
        {metric.current_value != null && (
          <span className="ml-1 text-slate-600">· {metric.current_value.toFixed(1)}%</span>
        )}
      </p>
    </div>
  )
}

// ── Forecast chart ────────────────────────────────────────────────────────────

function ForecastChart({ serverId, metric }: { serverId: string; metric: Metric }) {
  const { t } = useTranslation()
  const { data: history } = useForecastHistory(serverId, metric, 30)
  const { data: forecast, isError, isLoading } = useForecast(serverId, metric)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-500 text-sm">
        {t('common.loading')}
      </div>
    )
  }

  if (isError || !forecast) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-500 text-sm">
        {t('capacity.noForecast')}
      </div>
    )
  }

  if (forecast.status === 'insufficient_data') {
    return (
      <div className="flex items-center justify-center h-64 text-slate-500 text-sm">
        {t('capacity.insufficientData')}
      </div>
    )
  }

  const histDates  = (history ?? []).map((p) => p.date)
  const histValues = (history ?? []).map((p) => p.avg_value)
  const fcDates    = forecast.points.map((p) => p.date)
  const fcValues   = forecast.points.map((p) => p.yhat)
  const fcLower    = forecast.points.map((p) => p.yhat_lower)
  const fcUpper    = forecast.points.map((p) => p.yhat_upper)

  // Confidence band: echarts area between lower and upper
  // Use a stacked area: lower series fills to lower bound, band fills the gap
  const bandData = forecast.points.map((p, i) => p.yhat_upper - Math.max(p.yhat_lower, 0))

  const allDates = [...histDates, ...fcDates]

  // Pad historical series with nulls for forecast dates so x-axis aligns
  const histPadded = [...histValues, ...Array(fcDates.length).fill(null)]
  const fcPadded   = [...Array(histDates.length).fill(null), ...fcValues]
  const lowerPadded = [...Array(histDates.length).fill(null), ...fcLower.map((v) => Math.max(v, 0))]
  const bandPadded  = [...Array(histDates.length).fill(null), ...bandData]

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1e293b',
      borderColor: 'rgba(255,255,255,0.1)',
      textStyle: { color: '#e2e8f0', fontSize: 12 },
      formatter: (params: any[]) => {
        const date = params[0]?.axisValue
        const lines = params
          .filter((p) => p.value != null && p.seriesName !== t('capacity.chart.confidence'))
          .map((p) => `<span style="color:${p.color}">●</span> ${p.seriesName}: <b>${typeof p.value === 'number' ? p.value.toFixed(1) + '%' : '—'}</b>`)
        return `<div style="font-size:11px;line-height:1.8">${date}<br/>${lines.join('<br/>')}</div>`
      },
    },
    grid: { left: 48, right: 24, top: 24, bottom: 32 },
    xAxis: {
      type: 'category',
      data: allDates,
      axisLabel: { color: '#64748b', fontSize: 10, interval: Math.floor(allDates.length / 8) },
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.07)' } },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: { color: '#64748b', fontSize: 10, formatter: '{value}%' },
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.05)' } },
    },
    series: [
      // Historical
      {
        name: t('capacity.chart.historical'),
        type: 'line',
        data: histPadded,
        lineStyle: { color: '#7c3aed', width: 2 },
        itemStyle: { color: '#7c3aed' },
        symbol: 'none',
        connectNulls: false,
      },
      // Forecast
      {
        name: t('capacity.chart.forecast'),
        type: 'line',
        data: fcPadded,
        lineStyle: { color: '#a78bfa', width: 2, type: 'dashed' },
        itemStyle: { color: '#a78bfa' },
        symbol: 'none',
        connectNulls: false,
      },
      // Confidence band — lower base (invisible)
      {
        name: '_lower',
        type: 'line',
        data: lowerPadded,
        lineStyle: { opacity: 0 },
        symbol: 'none',
        stack: 'confidence',
        areaStyle: { opacity: 0 },
        connectNulls: false,
        tooltip: { show: false },
        legendHoverLink: false,
      },
      // Confidence band — upper fill
      {
        name: t('capacity.chart.confidence'),
        type: 'line',
        data: bandPadded,
        lineStyle: { opacity: 0 },
        symbol: 'none',
        stack: 'confidence',
        areaStyle: { color: '#7c3aed', opacity: 0.12 },
        connectNulls: false,
      },
      // 80% warning line
      {
        name: t('capacity.chart.threshold80'),
        type: 'line',
        markLine: {
          silent: true,
          symbol: 'none',
          data: [{ yAxis: 80 }],
          lineStyle: { color: '#f59e0b', type: 'dashed', width: 1, opacity: 0.6 },
          label: { formatter: '80%', color: '#f59e0b', fontSize: 10 },
        },
        data: [],
      },
      // 90% critical line
      {
        name: t('capacity.chart.threshold90'),
        type: 'line',
        markLine: {
          silent: true,
          symbol: 'none',
          data: [{ yAxis: 90 }],
          lineStyle: { color: '#ef4444', type: 'dashed', width: 1, opacity: 0.6 },
          label: { formatter: '90%', color: '#ef4444', fontSize: 10 },
        },
        data: [],
      },
    ],
    legend: {
      data: [t('capacity.chart.historical'), t('capacity.chart.forecast'), t('capacity.chart.confidence')],
      textStyle: { color: '#94a3b8', fontSize: 11 },
      top: 0,
      right: 0,
      itemWidth: 16,
      itemHeight: 2,
    },
  }

  return <ReactECharts option={option} style={{ height: 300 }} notMerge />
}

// ── Main component ────────────────────────────────────────────────────────────

export default function CapacityPlanning({ setView }: CapacityPlanningProps) {
  const { t } = useTranslation()
  const { data: servers } = useServers()
  const [serverId, setServerId] = useState('')
  const [activeMetric, setActiveMetric] = useState<Metric>('disk_usage_percent')
  const [serverOpen, setServerOpen] = useState(false)

  const { data: runway, isLoading: runwayLoading } = useRunway(serverId)

  const selectedServer = servers?.find((s) => s.server_id === serverId)

  return (
    <Layout currentView="capacity" setView={setView} title={t('capacity.title')}>
      <div className="space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t('capacity.title')}</h1>
          <p className="text-sm text-slate-500 mt-1">{t('capacity.subtitle')}</p>
        </div>

        {/* Server selector */}
        <div className="relative w-72">
          <button
            onClick={() => setServerOpen((o) => !o)}
            className="w-full flex items-center justify-between px-4 py-2.5 rounded-xl border border-white/10 bg-brand-slate text-sm text-slate-200 hover:border-brand-purple/40 transition-all"
          >
            <span>{selectedServer?.server_id ?? t('capacity.selectServer')}</span>
            <ChevronDown className="w-4 h-4 text-slate-500" />
          </button>
          {serverOpen && servers && (
            <div className="absolute z-20 mt-1 w-full rounded-xl border border-white/10 bg-brand-dark shadow-xl overflow-hidden">
              {servers.map((s) => (
                <button
                  key={s.server_id}
                  onClick={() => { setServerId(s.server_id); setServerOpen(false) }}
                  className="w-full text-left px-4 py-2.5 text-sm text-slate-300 hover:bg-white/5 hover:text-white transition-colors"
                >
                  {s.server_id}
                </button>
              ))}
            </div>
          )}
        </div>

        {serverId && (
          <>
            {/* Runway cards */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {runwayLoading
                ? METRICS.map((m) => (
                    <div key={m} className="h-24 rounded-xl border border-white/10 bg-white/3 animate-pulse" />
                  ))
                : (runway?.metrics ?? []).map((m) => (
                    <RunwayCard key={m.metric_name} metric={m} threshold={runway!.threshold_pct} />
                  ))}
            </div>

            {/* Metric tabs + chart */}
            <div className="rounded-2xl border border-white/10 bg-brand-slate p-6">
              {/* Tabs */}
              <div className="flex gap-1 mb-6 border-b border-white/5 pb-3">
                {METRICS.map((m) => (
                  <button
                    key={m}
                    onClick={() => setActiveMetric(m)}
                    className={`px-4 py-1.5 rounded-lg text-xs font-mono font-semibold transition-all ${
                      activeMetric === m
                        ? 'bg-brand-purple/20 text-brand-purple border border-brand-purple/30'
                        : 'text-slate-500 hover:text-slate-300 hover:bg-white/5'
                    }`}
                  >
                    {t(`capacity.tabs.${m}` as any)}
                  </button>
                ))}
              </div>

              <ForecastChart serverId={serverId} metric={activeMetric} />
            </div>
          </>
        )}
      </div>
    </Layout>
  )
}
