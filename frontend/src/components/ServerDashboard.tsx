import React, { useMemo, useState } from 'react'
import ReactECharts from 'echarts-for-react'
import * as echarts from 'echarts'
import { ArrowLeft, RefreshCw, Activity } from 'lucide-react'
import { useMetricNames, useMetricSeries, useAnomalyScores } from '../hooks/useMetrics'
import MetricCard from './MetricCard'
import Layout from './Layout'
import type { ViewType } from '../App'

interface ServerDashboardProps {
  serverId: string
  setView: (view: ViewType) => void
}

const TIME_RANGES = [
  { label: '15m', minutes: 15 },
  { label: '1h', minutes: 60 },
  { label: '6h', minutes: 360 },
  { label: '24h', minutes: 1440 },
]

const METRIC_CONFIG: Record<string, { label: string; unit: string; color: string; thresholds?: { amber: number; red: number } }> = {
  cpu_usage_percent:        { label: 'CPU',         unit: '%',      color: '#39FF14', thresholds: { amber: 70, red: 90 } },
  memory_usage_percent:     { label: 'Memória',     unit: '%',      color: '#7C3AED', thresholds: { amber: 75, red: 90 } },
  disk_usage_percent:       { label: 'Disco',       unit: '%',      color: '#F59E0B', thresholds: { amber: 80, red: 95 } },
  disk_read_bytes_per_sec:  { label: 'Disco Leitura', unit: 'B/s', color: '#06B6D4' },
  disk_write_bytes_per_sec: { label: 'Disco Escrita', unit: 'B/s', color: '#EC4899' },
  net_bytes_recv_per_sec:   { label: 'Rede ↓',      unit: 'B/s',   color: '#10B981' },
  net_bytes_sent_per_sec:   { label: 'Rede ↑',      unit: 'B/s',   color: '#F97316' },
  process_count:            { label: 'Processos',   unit: '',       color: '#94A3B8' },
}

interface MetricChartProps {
  serverId: string
  metric: string
  minutes: number
  showAnomalies?: boolean
}

const MetricChart: React.FC<MetricChartProps> = ({ serverId, metric, minutes, showAnomalies = false }) => {
  const { data, isFetching } = useMetricSeries(serverId, metric, minutes)
  const { data: anomalyData } = useAnomalyScores(serverId, metric, minutes, showAnomalies)
  const cfg = METRIC_CONFIG[metric] ?? { label: metric, unit: '', color: '#94A3B8' }

  // Build sorted timestamp→value lookup for anomaly scatter positioning
  const metricLookup = useMemo(() => {
    const entries = (data?.data ?? []).map(
      (p) => [new Date(p.timestamp).getTime(), p.value] as [number, number]
    )
    return entries.sort((a, b) => a[0] - b[0])
  }, [data])

  const nearestValue = (ts: string): number | null => {
    if (!metricLookup.length) return null
    const t = new Date(ts).getTime()
    let best = metricLookup[0]
    for (const entry of metricLookup) {
      if (Math.abs(entry[0] - t) < Math.abs(best[0] - t)) best = entry
      if (entry[0] > t + 5 * 60_000) break
    }
    return best[1]
  }

  const anomalyPoints = useMemo(() => {
    if (!showAnomalies || !anomalyData) return { amber: [], red: [] }
    const amber: { value: [string, number]; score: number }[] = []
    const red: { value: [string, number]; score: number }[] = []
    for (const a of anomalyData.data) {
      if (a.score < 0.5) continue
      const v = nearestValue(a.timestamp)
      if (v === null) continue
      const point = { value: [a.timestamp, parseFloat(v.toFixed(2))] as [string, number], score: a.score }
      if (a.score >= 0.8) red.push(point)
      else amber.push(point)
    }
    return { amber, red }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anomalyData, showAnomalies, metricLookup])

  const scatterTooltip = {
    trigger: 'item' as const,
    formatter: (p: any) => {
      const d = new Date(p.value[0])
      const t = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
      return `${t}<br/>Anomalia: <b>${p.data.score.toFixed(2)}</b>`
    },
    backgroundColor: '#1E293B',
    borderColor: '#EF4444',
    textStyle: { color: '#F1F5F9', fontSize: 11 },
  }

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1E293B',
      borderColor: cfg.color,
      textStyle: { color: '#F1F5F9', fontSize: 11 },
      formatter: (params: any[]) => {
        const line = params.find((p: any) => p.seriesType === 'line')
        if (!line) return ''
        const d = new Date(line.value[0])
        const t = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
        return `${t}<br/>${line.seriesName}: ${line.value[1]}`
      },
    },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '8%', containLabel: true },
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: '#334155' } },
      axisLabel: {
        color: '#64748B',
        fontSize: 10,
        formatter: (value: number) => {
          const d = new Date(value)
          return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
        },
      },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: '#1E293B' } },
      axisLabel: { color: '#64748B', fontSize: 10 },
    },
    series: [
      {
        name: cfg.label,
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: data?.data.map((p) => [p.timestamp, parseFloat(p.value.toFixed(2))]) ?? [],
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: `${cfg.color}33` },
            { offset: 1, color: `${cfg.color}00` },
          ]),
        },
        lineStyle: { width: 2, color: cfg.color },
      },
      ...(showAnomalies
        ? [
            {
              name: 'Anomalia média',
              type: 'scatter',
              data: anomalyPoints.amber,
              symbolSize: 8,
              itemStyle: { color: '#F59E0B', borderColor: '#78350F', borderWidth: 1 },
              tooltip: scatterTooltip,
              z: 10,
            },
            {
              name: 'Anomalia alta',
              type: 'scatter',
              data: anomalyPoints.red,
              symbolSize: 10,
              itemStyle: { color: '#EF4444', borderColor: '#7F1D1D', borderWidth: 1 },
              tooltip: scatterTooltip,
              z: 11,
            },
          ]
        : []),
    ],
  }

  return (
    <section className="glass-card p-5">
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-sm font-semibold text-slate-300">{cfg.label}</h3>
        {isFetching && <RefreshCw className="w-3 h-3 text-slate-500 animate-spin" />}
      </div>
      <div className="h-[200px]">
        <ReactECharts option={option} style={{ height: '100%', width: '100%' }} />
      </div>
    </section>
  )
}

const ServerDashboard: React.FC<ServerDashboardProps> = ({ serverId, setView }) => {
  const [minutes, setMinutes] = useState(60)
  const [showAnomalies, setShowAnomalies] = useState(false)
  const { data: metricNames } = useMetricNames(serverId)

  const summaryMetrics = ['cpu_usage_percent', 'memory_usage_percent', 'disk_usage_percent', 'process_count']
  const chartMetrics = metricNames?.metrics ?? Object.keys(METRIC_CONFIG)

  return (
    <Layout currentView="infrastructure" setView={setView} title={serverId}>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <button
            onClick={() => setView('infrastructure')}
            className="flex items-center gap-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Servidores
          </button>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowAnomalies((v) => !v)}
              title="Exibir pontos de anomalia nos gráficos"
              className={`flex items-center gap-1.5 px-3 py-1 text-xs font-mono rounded border transition-colors ${
                showAnomalies
                  ? 'bg-brand-purple/20 border-brand-purple/50 text-brand-purple'
                  : 'border-white/10 text-slate-400 hover:text-slate-200'
              }`}
            >
              <Activity className="w-3 h-3" />
              Anomalias
            </button>
            <div className="flex gap-1">
              {TIME_RANGES.map((r) => (
                <button
                  key={r.label}
                  onClick={() => setMinutes(r.minutes)}
                  className={`px-3 py-1 text-xs font-mono rounded transition-colors ${
                    minutes === r.minutes
                      ? 'bg-brand-purple text-white'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Summary Cards (#16) */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {summaryMetrics.map((metric) => (
            <SummaryCardWrapper key={metric} serverId={serverId} metric={metric} minutes={minutes} />
          ))}
        </div>

        {/* Charts (#15) */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {chartMetrics.map((metric) => (
            <MetricChart key={metric} serverId={serverId} metric={metric} minutes={minutes} showAnomalies={showAnomalies} />
          ))}
        </div>
      </div>
    </Layout>
  )
}

const SummaryCardWrapper: React.FC<{ serverId: string; metric: string; minutes: number }> = ({
  serverId, metric, minutes,
}) => {
  const { data } = useMetricSeries(serverId, metric, minutes)
  const cfg = METRIC_CONFIG[metric] ?? { label: metric, unit: '', color: '#94A3B8' }
  return (
    <MetricCard
      label={cfg.label}
      unit={cfg.unit}
      data={data?.data ?? []}
      thresholds={(cfg as typeof METRIC_CONFIG[string]).thresholds}
    />
  )
}

export default ServerDashboard
