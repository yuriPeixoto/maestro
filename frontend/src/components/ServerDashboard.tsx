import { useMemo, useState } from 'react'
import ReactECharts from 'echarts-for-react'
import * as echarts from 'echarts'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, RefreshCw, Activity, Server, Cpu, MemoryStick, HardDrive } from 'lucide-react'
import { useMetricNames, useMetricSeries, useAnomalyScores, useHealthSnapshot } from '../hooks/useMetrics'
import Layout from './Layout'
import type { ViewType } from '../App'
import { TrendBar, HealthScore } from './primitives'
import type { HealthState } from './primitives'

interface ServerDashboardProps {
  serverId: string
  setView: (view: ViewType) => void
}

const TIME_RANGES = [
  { label: '15m', minutes: 15 },
  { label: '1h',  minutes: 60 },
  { label: '6h',  minutes: 360 },
  { label: '24h', minutes: 1440 },
]

const METRIC_CFG: Record<string, { label: string; unit: string; color: string; threshold?: number }> = {
  cpu_usage_percent:        { label: 'CPU',           unit: '%',   color: '#39FF14', threshold: 80 },
  memory_usage_percent:     { label: 'Memory',        unit: '%',   color: '#7C3AED', threshold: 90 },
  disk_usage_percent:       { label: 'Disk',          unit: '%',   color: '#F59E0B', threshold: 95 },
  disk_read_bytes_per_sec:  { label: 'Disk Read',     unit: 'B/s', color: '#06B6D4' },
  disk_write_bytes_per_sec: { label: 'Disk Write',    unit: 'B/s', color: '#EC4899' },
  net_bytes_recv_per_sec:   { label: 'Net ↓',         unit: 'B/s', color: '#10B981' },
  net_bytes_sent_per_sec:   { label: 'Net ↑',         unit: 'B/s', color: '#F97316' },
  process_count:            { label: 'Processes',     unit: '',    color: '#94A3B8' },
}

const TABS = ['health', 'io', 'processes'] as const
type Tab = typeof TABS[number]

const TAB_METRICS: Record<Tab, string[]> = {
  health:    ['cpu_usage_percent', 'memory_usage_percent', 'disk_usage_percent'],
  io:        ['disk_read_bytes_per_sec', 'disk_write_bytes_per_sec', 'net_bytes_recv_per_sec', 'net_bytes_sent_per_sec'],
  processes: ['process_count'],
}

// ── Chart ─────────────────────────────────────────────────────────────────────

function MetricChart({
  serverId, metric, minutes, showAnomalies, threshold, baseline,
}: {
  serverId: string
  metric: string
  minutes: number
  showAnomalies: boolean
  threshold?: number
  baseline?: number | null
}) {
  const { data, isFetching } = useMetricSeries(serverId, metric, minutes)
  const { data: anomalyData } = useAnomalyScores(serverId, metric, minutes, showAnomalies)
  const cfg = METRIC_CFG[metric] ?? { label: metric, unit: '', color: '#94A3B8' }

  const metricLookup = useMemo(() => {
    return (data?.data ?? [])
      .map((p) => [new Date(p.timestamp).getTime(), p.value] as [number, number])
      .sort((a, b) => a[0] - b[0])
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
    const red:   { value: [string, number]; score: number }[] = []
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

  const markLines = []
  if (threshold != null) {
    markLines.push({
      name: 'Threshold', yAxis: threshold,
      lineStyle: { color: '#F87171', type: 'dashed', width: 1 },
      label: { formatter: `${threshold}`, color: '#F87171', fontSize: 9 },
    })
  }
  if (baseline != null) {
    markLines.push({
      name: 'Baseline', yAxis: baseline,
      lineStyle: { color: 'rgba(255,255,255,0.25)', type: 'dotted', width: 1 },
      label: { formatter: `${baseline}`, color: '#94A3B8', fontSize: 9 },
    })
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
        return `${t}<br/>${line.seriesName}: ${line.value[1]}${cfg.unit}`
      },
    },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '12%', containLabel: true },
    xAxis: {
      type: 'time',
      axisLine: { lineStyle: { color: '#334155' } },
      axisLabel: {
        color: '#64748B', fontSize: 10,
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
        markLine: markLines.length > 0
          ? { silent: true, symbol: 'none', data: markLines }
          : undefined,
      },
      ...(showAnomalies ? [
        {
          name: 'Anomaly mid',
          type: 'scatter',
          data: anomalyPoints.amber,
          symbolSize: 8,
          itemStyle: { color: '#F59E0B', borderColor: '#78350F', borderWidth: 1 },
          tooltip: {
            trigger: 'item' as const,
            formatter: (p: any) => {
              const d = new Date(p.value[0])
              const t = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
              return `${t}<br/>Anomaly: <b>${p.data.score.toFixed(2)}</b>`
            },
            backgroundColor: '#1E293B', borderColor: '#F59E0B',
            textStyle: { color: '#F1F5F9', fontSize: 11 },
          },
          z: 10,
        },
        {
          name: 'Anomaly high',
          type: 'scatter',
          data: anomalyPoints.red,
          symbolSize: 10,
          itemStyle: { color: '#EF4444', borderColor: '#7F1D1D', borderWidth: 1 },
          tooltip: {
            trigger: 'item' as const,
            formatter: (p: any) => {
              const d = new Date(p.value[0])
              const t = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
              return `${t}<br/>Anomaly: <b>${p.data.score.toFixed(2)}</b>`
            },
            backgroundColor: '#1E293B', borderColor: '#EF4444',
            textStyle: { color: '#F1F5F9', fontSize: 11 },
          },
          z: 11,
        },
      ] : []),
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

// ── Narrative hero ────────────────────────────────────────────────────────────

function NarrativeHero({ serverId }: { serverId: string }) {
  const { t } = useTranslation()
  const { data: snap, isLoading } = useHealthSnapshot(serverId)

  if (isLoading || !snap) {
    return (
      <div className="glass-card p-6 mb-6 flex items-center gap-3 text-slate-500 text-sm">
        <RefreshCw className="w-4 h-4 animate-spin" />
        <span>{t('common.loading')}</span>
      </div>
    )
  }

  const state = snap.state as HealthState
  const metricRows = [
    { key: 'cpu',    label: t('health.metrics.cpu'),    icon: Cpu,         metric: snap.cpu,    color: '#39FF14' },
    { key: 'memory', label: t('health.metrics.memory'), icon: MemoryStick, metric: snap.memory, color: '#7C3AED' },
    { key: 'disk',   label: t('health.metrics.disk'),   icon: HardDrive,   metric: snap.disk,   color: '#F59E0B' },
  ]

  return (
    <div className="glass-card p-5 mb-6">
      {/* Header row */}
      <div className="flex items-start gap-4 mb-5">
        <div className="w-10 h-10 rounded-xl bg-brand-slate flex items-center justify-center flex-shrink-0">
          <Server className="w-5 h-5 text-brand-purple" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <h2 className="font-mono text-base font-bold text-slate-100">{serverId}</h2>
            <HealthScore state={state} size="sm" />
          </div>
          {snap.headline && (
            <p className="text-sm text-slate-300 mt-1 leading-relaxed">{snap.headline}</p>
          )}
        </div>
        {snap.anomalies6h > 0 && (
          <span className="text-[11px] font-mono text-amber-400 bg-amber-400/10 border border-amber-400/20 px-2 py-1 rounded-md shrink-0">
            {t('health.anomalies6h', { count: snap.anomalies6h })}
          </span>
        )}
      </div>

      {/* Metric bars */}
      <div className="space-y-3">
        {metricRows.map(({ key, label, icon: Icon, metric, color }) => {
          if (!metric || metric.value == null) return null
          const over = metric.value >= metric.threshold * 0.9
          return (
            <div key={key} className="grid items-center gap-x-3" style={{ gridTemplateColumns: '20px 56px 1fr auto' }}>
              <Icon size={12} className="text-slate-500" />
              <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">{label}</span>
              <TrendBar
                value={metric.value}
                threshold={metric.threshold}
                baseline={metric.baseline ?? undefined}
                color={color}
                height={5}
              />
              <span className={`font-mono text-xs font-bold text-right ${over ? 'text-red-400' : 'text-slate-200'}`}
                    style={{ minWidth: 40 }}>
                {metric.value}%
              </span>
            </div>
          )
        })}
      </div>

      {/* Critical services */}
      {snap.critical_services.length > 0 && (
        <div className="flex items-center gap-2 mt-4 pt-3 border-t border-white/5 flex-wrap">
          <span className="text-[10px] text-slate-500 uppercase tracking-widest">{t('common.criticalServices')}</span>
          {snap.critical_services.slice(0, 8).map((svc) => (
            <div
              key={svc.name}
              title={`${svc.name} · ${svc.ok ? 'active' : 'failed'}`}
              className="flex items-center gap-1"
            >
              <div style={{
                width: 6, height: 6, borderRadius: '50%',
                background: svc.ok ? '#39FF14' : '#F87171',
                boxShadow: svc.ok ? '0 0 4px rgba(57,255,20,0.5)' : 'none',
              }} />
              <span className="text-[10px] text-slate-500">{svc.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function ServerDashboard({ serverId, setView }: ServerDashboardProps) {
  const { t } = useTranslation()
  const [minutes, setMinutes] = useState(60)
  const [showAnomalies, setShowAnomalies] = useState(false)
  const [activeTab, setActiveTab] = useState<Tab>('health')

  const { data: metricNames } = useMetricNames(serverId)
  const { data: snap } = useHealthSnapshot(serverId)
  const available = new Set(metricNames?.metrics ?? [])

  const baselines: Record<string, number | null> = {
    cpu_usage_percent:    snap?.cpu?.baseline    ?? null,
    memory_usage_percent: snap?.memory?.baseline ?? null,
    disk_usage_percent:   snap?.disk?.baseline   ?? null,
  }

  const tabMetrics = TAB_METRICS[activeTab].filter(
    (m) => available.size === 0 || available.has(m)
  )

  const tabLabel: Record<Tab, string> = {
    health:    t('server.tabs.health'),
    io:        t('server.tabs.io'),
    processes: t('server.tabs.processes'),
  }

  return (
    <Layout currentView="infrastructure" setView={setView} title={serverId}>
      <div className="space-y-6">
        {/* Back + controls */}
        <div className="flex items-center justify-between flex-wrap gap-3">
          <button
            onClick={() => setView('infrastructure')}
            className="flex items-center gap-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            {t('infrastructure.title')}
          </button>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowAnomalies((v) => !v)}
              className={`flex items-center gap-1.5 px-3 py-1 text-xs font-mono rounded border transition-colors ${
                showAnomalies
                  ? 'bg-brand-purple/20 border-brand-purple/50 text-brand-purple'
                  : 'border-white/10 text-slate-400 hover:text-slate-200'
              }`}
            >
              <Activity className="w-3 h-3" />
              {t('server.anomalySummary')}
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

        {/* Narrative hero */}
        <NarrativeHero serverId={serverId} />

        {/* Tabs */}
        <div className="flex gap-1 border-b border-white/10 pb-0">
          {TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 text-xs font-bold uppercase tracking-widest rounded-t transition-colors ${
                activeTab === tab
                  ? 'text-brand-purple border-b-2 border-brand-purple bg-brand-purple/5'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {tabLabel[tab]}
            </button>
          ))}
        </div>

        {/* Charts grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {tabMetrics.map((metric) => (
            <MetricChart
              key={metric}
              serverId={serverId}
              metric={metric}
              minutes={minutes}
              showAnomalies={showAnomalies}
              threshold={METRIC_CFG[metric]?.threshold}
              baseline={baselines[metric]}
            />
          ))}
          {tabMetrics.length === 0 && (
            <p className="text-slate-500 text-sm lg:col-span-2">{t('common.noData')}</p>
          )}
        </div>
      </div>
    </Layout>
  )
}
