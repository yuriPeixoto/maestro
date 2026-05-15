import React, { useState } from 'react'
import ReactECharts from 'echarts-for-react'
import * as echarts from 'echarts'
import { ArrowLeft, RefreshCw } from 'lucide-react'
import { useMetricNames, useMetricSeries } from '../hooks/useMetrics'
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
}

const MetricChart: React.FC<MetricChartProps> = ({ serverId, metric, minutes }) => {
  const { data, isFetching } = useMetricSeries(serverId, metric, minutes)
  const cfg = METRIC_CONFIG[metric] ?? { label: metric, unit: '', color: '#94A3B8' }

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1E293B',
      borderColor: cfg.color,
      textStyle: { color: '#F1F5F9', fontSize: 11 },
      formatter: (params: any[]) => {
        const d = new Date(params[0].value[0])
        const t = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
        return `${t}<br/>${params[0].seriesName}: ${params[0].value[1]}`
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

        {/* Summary Cards (#16) */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {summaryMetrics.map((metric) => (
            <SummaryCardWrapper key={metric} serverId={serverId} metric={metric} minutes={minutes} />
          ))}
        </div>

        {/* Charts (#15) */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {chartMetrics.map((metric) => (
            <MetricChart key={metric} serverId={serverId} metric={metric} minutes={minutes} />
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
