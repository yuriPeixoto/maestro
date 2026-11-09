import { useTranslation } from 'react-i18next'
import { useQueries } from '@tanstack/react-query'
import { AlertTriangle, BellOff, CheckCircle, WifiOff, ShieldCheck, ArrowRight } from 'lucide-react'
import Layout from './Layout'
import type { ViewType } from '../App'
import { HealthScore, TrendBar, Sparkline, ServerName } from './primitives'
import type { HealthState } from './primitives'
import type { ServerHealthSnapshot, AlertEvent } from '../services/api'
import { serversApi } from '../services/api'
import { useServers } from '../hooks/useServers'
import { useAlertEvents, useAlertRules } from '../hooks/useAlerts'
import { useSshEvents } from '../hooks/useSecurity'
import { useAttackByHour, useSshBaseline } from '../hooks/useMetrics'
import { useUIStore } from '../store/uiStore'
import type { ServerStatus } from '../types/server'
import { formatDecimal, formatPercent, headlineText, metricLabel, relativeTime } from '../utils/format'
import { serverName } from '../hooks/useServerName'

interface DashboardProps {
  setView: (view: ViewType) => void
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const STATE_COLOR: Record<HealthState | 'quiet', string> = {
  ok:        '#34D399',
  attention: '#F59E0B',
  critical:  '#F87171',
  quiet:     '#94A3B8',
}

const DAY_MS = 86_400_000

interface FleetEntry extends ServerStatus {
  snapshot: ServerHealthSnapshot | null
}

// ── Sub-components ────────────────────────────────────────────────────────────

function FleetTallyDot({ count, state }: { count: number; state: HealthState }) {
  const { t } = useTranslation()
  if (!count) return null
  const color = STATE_COLOR[state]
  return (
    <div className="flex items-center gap-1.5">
      <span style={{
        width: 8, height: 8, borderRadius: '50%', background: color,
        boxShadow: state === 'ok' ? `0 0 6px ${color}88` : 'none',
        flexShrink: 0,
      }} />
      <span className="font-mono text-sm font-bold text-slate-100">{count}</span>
      <span className="text-xs text-slate-400">{t(`health.state.${state}`)}</span>
    </div>
  )
}

function FocusHero({
  server,
  snapshot,
  onOpen,
}: {
  server: FleetEntry
  snapshot: ServerHealthSnapshot | null
  onOpen: () => void
}) {
  const { t } = useTranslation()
  if (!snapshot) return null

  const state = snapshot.state as HealthState
  const conf = {
    ok:        { fg: '#34D399', soft: 'rgba(52,211,153,0.06)',  border: 'rgba(52,211,153,0.20)' },
    attention: { fg: '#F59E0B', soft: 'rgba(245,158,11,0.06)',  border: 'rgba(245,158,11,0.22)' },
    critical:  { fg: '#F87171', soft: 'rgba(239,68,68,0.06)',   border: 'rgba(239,68,68,0.22)'  },
    quiet:     { fg: '#94A3B8', soft: 'rgba(148,163,184,0.06)', border: 'rgba(148,163,184,0.20)' },
  }[state]

  return (
    <div
      className="glass-card"
      style={{
        padding: 24, position: 'relative', overflow: 'hidden',
        borderColor: conf.border,
        background: `linear-gradient(180deg, ${conf.soft} 0%, transparent 50%), rgba(30,41,59,0.4)`,
      }}
    >
      <div className="flex items-center gap-3 mb-4">
        <HealthScore state={state} size="sm" />
        <span className="min-w-0"><ServerName name={serverName(server)} nameClass="text-lg font-bold tracking-tight text-slate-100" inline /></span>
        <span className="flex-1" />
        <button
          onClick={onOpen}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-brand-purple/10 border border-brand-purple/30 text-brand-purple text-xs font-semibold hover:bg-brand-purple/20 transition-colors"
        >
          {t('common.openServer')}
          <ArrowRight size={12} />
        </button>
      </div>

      <p className="text-sm text-slate-100 font-medium mb-5">
        {headlineText(snapshot, t)}
      </p>

      <div className="grid grid-cols-3 gap-8">
        <MetricBlock
          label={t('health.metrics.cpu')}
          hint={t('health.metrics.cpuHint')}
          metric={snapshot.cpu}
          color="#39FF14"
        />
        <MetricBlock
          label={t('health.metrics.memory')}
          metric={snapshot.memory}
          color="#7C3AED"
        />
        <MetricBlock
          label={t('health.metrics.disk')}
          metric={snapshot.disk}
          color="#F59E0B"
        />
      </div>

      {snapshot.critical_services.length > 0 && (
        <div className="flex items-center justify-end gap-2 mt-5 pt-4 border-t border-white/5 flex-wrap">
          <span className="text-[10px] font-mono uppercase tracking-widest text-slate-500">
            {t('common.criticalServices')}
          </span>
          {snapshot.critical_services.map((svc) => (
            <div
              key={svc.name}
              title={`${svc.name} · ${t(svc.ok ? 'common.serviceActive' : 'common.serviceFailed')}`}
              className="flex items-center gap-1 px-1.5 py-0.5 rounded"
              style={{
                background: svc.ok ? 'rgba(57,255,20,0.05)' : 'rgba(239,68,68,0.10)',
                border: `1px solid ${svc.ok ? 'rgba(57,255,20,0.15)' : 'rgba(239,68,68,0.25)'}`,
                fontSize: 11, fontFamily: 'monospace',
                color: svc.ok ? '#39FF14' : '#F87171',
              }}
            >
              <span style={{
                width: 4, height: 4, borderRadius: '50%',
                background: 'currentColor',
                boxShadow: svc.ok ? '0 0 4px currentColor' : 'none',
              }} />
              {svc.name}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function MetricBlock({
  label,
  hint,
  metric,
  color,
}: {
  label: string
  hint?: string
  metric: ServerHealthSnapshot['cpu']
  color: string
}) {
  const { t } = useTranslation()
  if (!metric) return null

  return (
    <div className="flex flex-col gap-1.5 min-w-0">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">{label}</span>
        {hint && <span className="text-[10px] text-slate-500">{hint}</span>}
      </div>
      <span className="font-mono text-2xl font-bold text-slate-100 tabular-nums">
        {formatPercent(metric.value)}
      </span>
      <TrendBar
        value={metric.value ?? 0}
        max={metric.threshold * 1.2}
        threshold={metric.threshold}
        baseline={metric.baseline ?? undefined}
        color={color}
        height={6}
      />
      {metric.spark.length > 1 && (
        <Sparkline data={metric.spark} color={color} width={160} height={20} />
      )}
      {metric.baseline != null && (
        <span className="text-[11px] text-slate-500">
          {t('health.metrics.average7d', { value: formatPercent(metric.baseline) })}
        </span>
      )}
      {metric.projection_hours != null && (
        <div className="text-[11px] text-amber-400 mt-0.5">
          ↗ {t('health.projection', { threshold: Math.round(metric.threshold), hours: metric.projection_hours })}
        </div>
      )}
    </div>
  )
}

function IncidentsCard({
  events,
  openAlerts,
  ruleCount,
  onViewAlerts,
}: {
  events: AlertEvent[]
  openAlerts: number
  ruleCount: number | undefined
  onViewAlerts: () => void
}) {
  const { t } = useTranslation()
  const unwatched = ruleCount === 0

  return (
    <div className="glass-card p-5">
      <div className="flex items-baseline justify-between mb-4">
        <h3 className="text-sm font-bold text-slate-100">{t('dashboard.incidents.title')}</h3>
        <button
          onClick={onViewAlerts}
          className="text-[10px] font-mono text-slate-500 hover:text-brand-purple transition-colors uppercase tracking-widest"
        >
          {unwatched ? t('dashboard.incidents.createRules') : t('common.viewAll')}
        </button>
      </div>

      {unwatched ? (
        <div className="flex items-center gap-3 p-4 rounded-lg bg-slate-500/5 border border-slate-500/20">
          <BellOff size={20} className="text-slate-400 flex-shrink-0" />
          <div>
            <div className="text-sm font-bold text-slate-300">{t('dashboard.incidents.unwatched')}</div>
            <div className="text-xs text-slate-400 mt-0.5">{t('dashboard.incidents.unwatchedDesc')}</div>
          </div>
        </div>
      ) : events.length === 0 && openAlerts === 0 ? (
        <div className="flex items-center gap-3 p-4 rounded-lg bg-brand-neon/5 border border-brand-neon/20">
          <CheckCircle size={20} className="text-brand-neon flex-shrink-0" />
          <div>
            <div className="text-sm font-bold text-brand-neon">{t('dashboard.incidents.quiet')}</div>
            <div className="text-xs text-slate-400 mt-0.5">{t('dashboard.incidents.quietDesc')}</div>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {openAlerts > 0 && (
            <div className="flex items-center gap-2.5 p-2.5 rounded-lg bg-red-500/6 border border-red-500/20">
              <AlertTriangle size={14} className="text-red-400 flex-shrink-0" />
              <span className="text-sm font-bold text-red-400">
                {t('dashboard.incidents.firingNow', { count: openAlerts })}
              </span>
            </div>
          )}
          {events.slice(0, 4).map((e) => (
            <div key={e.event_id} className="flex items-center gap-2.5 py-2 border-b border-white/5 last:border-0">
              {e.state === 'FIRING'
                ? <AlertTriangle size={14} style={{ color: e.severity === 'critical' ? '#F87171' : '#FB923C', flexShrink: 0 }} />
                : <CheckCircle size={14} className="text-brand-neon flex-shrink-0" />
              }
              <span className="text-xs text-slate-200">{metricLabel(e.metric_name, t)}</span>
              <span className="text-[11px] text-slate-500">{t(`alerts.events.stateLabel.${e.state}`)}</span>
              <span className="font-mono text-[11px] text-slate-500">
                {formatDecimal(e.value)} / {e.threshold}
              </span>
              <span className="flex-1" />
              <span className="text-[11px] text-slate-500">{relativeTime(e.triggered_at, t)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function FleetTile({ server, onClick }: { server: FleetEntry; onClick: () => void }) {
  const { t } = useTranslation()
  const h = server.snapshot
  const state = (h?.state ?? 'quiet') as HealthState

  return (
    <button
      onClick={onClick}
      className="glass-card p-4 text-left cursor-pointer relative overflow-hidden"
      style={{ transition: 'all 0.15s ease' }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = 'rgba(124,58,237,0.40)'
        e.currentTarget.style.boxShadow = '0 0 20px rgba(124,58,237,0.10)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = ''
        e.currentTarget.style.boxShadow = ''
      }}
    >
      <div className="flex items-center gap-2.5 mb-3">
        <HealthScore state={state} size="sm" />
        <span className="text-[13px] font-bold text-slate-100 flex-1 truncate min-w-0">
          <ServerName name={serverName(server)} nameClass="text-[13px] font-bold text-slate-100" />
        </span>
      </div>

      {h?.cpu?.value != null ? (
        <div className="grid gap-y-1.5" style={{ gridTemplateColumns: '40px 1fr auto', columnGap: 8, alignItems: 'center' }}>
          <span className="text-[10px] text-slate-500 uppercase font-bold">{t('health.metrics.cpu')}</span>
          <TrendBar value={h.cpu.value} threshold={h.cpu.threshold} baseline={h.cpu.baseline ?? undefined} color="#39FF14" height={4} />
          <span className="font-mono text-xs font-bold text-slate-200">{formatPercent(h.cpu.value)}</span>

          <span className="text-[10px] text-slate-500 uppercase font-bold">{t('health.metrics.memory').slice(0,3)}</span>
          <TrendBar value={h.memory.value ?? 0} threshold={h.memory.threshold} baseline={h.memory.baseline ?? undefined} color="#7C3AED" height={4} />
          <span className="font-mono text-xs font-bold text-slate-200">{formatPercent(h.memory.value)}</span>

          <span className="text-[10px] text-slate-500 uppercase font-bold">{t('health.metrics.disk').slice(0,3)}</span>
          <TrendBar value={h.disk.value ?? 0} threshold={h.disk.threshold} baseline={h.disk.baseline ?? undefined} color="#F59E0B" height={4} />
          <span className="font-mono text-xs font-bold text-slate-200">{formatPercent(h.disk.value)}</span>
        </div>
      ) : (
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <WifiOff size={13} />
          <span>{t('infrastructure.noMetrics')}</span>
        </div>
      )}
    </button>
  )
}

function SecurityPulseCard({
  sshCount,
  baseline,
  delta,
  hourly,
  onViewSecurity,
}: {
  sshCount: number
  baseline: number
  delta: number
  hourly: { hour: number; count: number }[]
  onViewSecurity: () => void
}) {
  const { t, i18n } = useTranslation()
  const deltaColor = delta > 2 ? '#F87171' : delta > 1.3 ? '#F59E0B' : '#34D399'
  const sparkData = hourly.map((h) => h.count)
  const baselinePerHour = baseline / 24

  return (
    <div className="glass-card p-5 grid items-center gap-6" style={{ gridTemplateColumns: 'auto 1fr auto' }}>
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl flex items-center justify-center bg-brand-purple/10 border border-brand-purple/25">
          <ShieldCheck size={20} className="text-brand-purple" />
        </div>
        <div>
          <div className="text-[10px] font-mono font-bold uppercase tracking-widest text-slate-400">
            {t('dashboard.security.label')}
          </div>
          <div className="text-sm text-slate-100 mt-0.5">
            <span className="text-slate-400">{t('dashboard.security.attempts', { count: sshCount })}</span>
            {baseline > 0 && (
              <>
                <span className="text-slate-400"> — </span>
                <span className="font-mono font-bold" style={{ color: deltaColor }}>{delta.toLocaleString(i18n.language, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}×</span>
                <span className="text-slate-400"> {t('dashboard.security.weeklyAvg')}</span>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="flex items-center justify-end">
        {sparkData.length > 0 && (
          <Sparkline
            data={sparkData}
            color="#7C3AED"
            width={220}
            height={36}
            baseline={baselinePerHour}
          />
        )}
      </div>

      <button
        onClick={onViewSecurity}
        className="text-[10px] font-mono text-slate-500 hover:text-brand-purple transition-colors uppercase tracking-widest whitespace-nowrap"
      >
        {t('common.viewDetails')}
      </button>
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function Dashboard({ setView }: DashboardProps) {
  const { t } = useTranslation()
  const setSelectedAgentId = useUIStore((s) => s.setSelectedAgentId)
  const { data: servers, isLoading } = useServers()

  // Load health snapshots for all servers in parallel
  const snapshotQueries = useQueries({
    queries: (servers ?? []).map((s) => ({
      queryKey: ['health-snapshot', s.server_id],
      queryFn: () => serversApi.healthSnapshot(s.server_id),
      refetchInterval: 30_000,
    })),
  })

  const snapshots = (servers ?? []).reduce<Record<string, ServerHealthSnapshot>>((acc, s, i) => {
    const d = snapshotQueries[i]?.data
    if (d) acc[s.server_id] = d
    return acc
  }, {})

  const fleet: FleetEntry[] = (servers ?? []).map((s) => ({
    ...s,
    snapshot: snapshots[s.server_id] ?? null,
  }))

  const counts = fleet.reduce<Record<string, number>>((acc, s) => {
    const st = s.snapshot?.state ?? 'quiet'
    acc[st] = (acc[st] ?? 0) + 1
    return acc
  }, {})

  // Focus server: most actionable one with live data
  const criticalWithData = fleet.find((s) => s.snapshot?.state === 'critical' && s.status !== 'offline')
  const attentionServer  = fleet.find((s) => s.snapshot?.state === 'attention')
  const offlineServer    = fleet.find((s) => s.status === 'offline')
  const focusServer = criticalWithData ?? attentionServer ?? fleet.find((s) => s.status === 'online') ?? fleet[0]

  const primaryServerId = servers?.find((s) => s.status === 'online')?.server_id ?? ''
  const focusServerId   = focusServer?.server_id ?? ''

  // Alert data for focus server
  const { data: eventsData, dataUpdatedAt: eventsFetchedAt } = useAlertEvents(focusServerId)
  const { data: rulesData }  = useAlertRules(focusServerId)

  // Security data
  const { data: sshData }      = useSshEvents(primaryServerId)
  const { data: hourData }     = useAttackByHour(primaryServerId)
  const { data: baselineData } = useSshBaseline(primaryServerId)

  if (isLoading) {
    return (
      <Layout currentView="dashboard" setView={setView} title="Dashboard">
        <p className="text-slate-400 text-sm">{t('common.loading')}</p>
      </Layout>
    )
  }

  // Derived values
  const events24h = (eventsData?.events ?? []).filter(
    (e) => eventsFetchedAt - new Date(e.triggered_at).getTime() < DAY_MS
  )

  const sshCount   = sshData?.stats.attempts_24h ?? 0
  const sshBase    = baselineData?.avg_daily ?? 0
  const sshDelta   = sshBase > 0 ? sshCount / sshBase : 0
  const hourly     = hourData?.hours ?? []

  // Fleet headline
  const headlineText = (() => {
    if (fleet.length === 0) return t('dashboard.headline.noServers')
    if ((counts.critical ?? 0) > 0)
      return t('dashboard.headline.critical', { count: counts.critical })
    if ((counts.attention ?? 0) > 0)
      return t('dashboard.headline.attention', { ok: counts.ok ?? 0, count: counts.attention })
    if ((counts.ok ?? 0) === 0) return t('dashboard.headline.noData')
    if ((counts.quiet ?? 0) > 0)
      return t('dashboard.headline.partial', { ok: counts.ok, count: counts.quiet })
    return t('dashboard.headline.allGood')
  })()

  const navigate = (serverId: string, view: ViewType = 'server') => {
    setSelectedAgentId(serverId)
    setView(view)
  }

  return (
    <Layout currentView="dashboard" setView={setView} title="Dashboard">
      <div className="flex flex-col gap-6">

        {/* Fleet headline + tally */}
        <div className="flex items-center gap-4">
          <h1 className="font-bold text-slate-100" style={{ fontSize: 28, fontWeight: 700, letterSpacing: '-0.02em', margin: 0 }}>
            {headlineText}
          </h1>
          <span className="flex-1" />
          <FleetTallyDot count={counts.ok      ?? 0} state="ok" />
          <FleetTallyDot count={counts.attention ?? 0} state="attention" />
          <FleetTallyDot count={counts.critical  ?? 0} state="critical" />
          <FleetTallyDot count={counts.quiet     ?? 0} state="quiet" />
        </div>

        {/* Offline callout */}
        {offlineServer && offlineServer !== focusServer && (
          <div
            className="glass-card flex items-center gap-3 p-3.5"
            style={{ borderColor: 'rgba(239,68,68,0.22)', background: 'linear-gradient(180deg, rgba(239,68,68,0.05) 0%, transparent 80%), rgba(30,41,59,0.4)' }}
          >
            <WifiOff size={16} style={{ color: '#F87171', flexShrink: 0 }} />
            <span><ServerName name={serverName(offlineServer)} nameClass="text-[13px] font-bold text-slate-100" inline /></span>
            <span className="text-xs text-slate-400">
              {offlineServer.last_seen
                ? t('dashboard.offline.message', { time: relativeTime(offlineServer.last_seen, t) })
                : t('dashboard.offline.messageNever')}
            </span>
            <span className="flex-1" />
            <button
              onClick={() => navigate(offlineServer.server_id)}
              className="text-[10px] font-mono text-slate-400 hover:text-brand-purple transition-colors uppercase tracking-widest"
            >
              {t('common.investigate')}
            </button>
          </div>
        )}

        {/* Focus hero */}
        {focusServer && (
          <FocusHero
            server={focusServer}
            snapshot={focusServer.snapshot}
            onOpen={() => navigate(focusServer.server_id)}
          />
        )}

        {focusServer && (
          <IncidentsCard
            events={events24h}
            openAlerts={focusServer.snapshot?.open_alerts ?? 0}
            ruleCount={rulesData?.rules.length}
            onViewAlerts={() => setView('alerts')}
          />
        )}

        {/* Fleet strip */}
        {fleet.length > 0 && (
          <section>
            <div className="flex items-baseline justify-between mb-3">
              <h2 className="text-sm font-bold text-slate-300">
                {t('dashboard.fleet', { count: fleet.length })}
              </h2>
              <button
                onClick={() => setView('infrastructure')}
                className="text-[10px] font-mono text-slate-500 hover:text-brand-purple transition-colors uppercase tracking-widest"
              >
                {t('common.viewMap')}
              </button>
            </div>
            <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))' }}>
              {fleet.map((s) => (
                <FleetTile
                  key={s.server_id}
                  server={s}
                  onClick={() => navigate(s.server_id)}
                />
              ))}
            </div>
          </section>
        )}

        {/* Security pulse */}
        {sshCount > 0 && (
          <SecurityPulseCard
            sshCount={sshCount}
            baseline={sshBase}
            delta={sshDelta}
            hourly={hourly}
            onViewSecurity={() => setView('security')}
          />
        )}

      </div>
    </Layout>
  )
}
