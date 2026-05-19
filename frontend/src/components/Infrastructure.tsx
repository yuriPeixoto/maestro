import { useTranslation } from 'react-i18next'
import { useQueries } from '@tanstack/react-query'
import { Server, Package, CheckCircle, XCircle, HelpCircle, RefreshCw, WifiOff, TrendingUp, TrendingDown, Minus } from 'lucide-react'
import Layout from './Layout'
import type { ViewType } from '../App'
import { HealthScore, TrendBar } from './primitives'
import type { HealthState } from './primitives'
import type { ServerHealthSnapshot } from '../services/api'
import { serversApi } from '../services/api'
import { useServers } from '../hooks/useServers'
import { useInventory } from '../hooks/useInventory'
import { useUIStore } from '../store/uiStore'
import type { ServerStatus } from '../types/server'

interface InfrastructureProps {
  setView: (view: ViewType) => void
}

// ── Inventory table (unchanged from v1 — services + runtimes per server) ─────

function ServiceStatus({ status }: { status: string }) {
  if (status === 'active')   return <CheckCircle className="w-3.5 h-3.5 text-brand-neon" />
  if (status === 'inactive' || status === 'failed')
                             return <XCircle className="w-3.5 h-3.5 text-red-400" />
  return <HelpCircle className="w-3.5 h-3.5 text-slate-500" />
}

function uptimeSince(iso: string | null): string {
  if (!iso) return '—'
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 3600)  return `${Math.floor(diff / 60)}m`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`
  return `${Math.floor(diff / 86400)}d`
}

function InventoryTable({ serverId }: { serverId: string }) {
  const { data, isFetching, isError } = useInventory(serverId)

  if (isError) return <p className="text-xs text-red-400 mt-4">Error loading inventory.</p>
  if (!data)   return <p className="text-xs text-slate-500 mt-4">Loading inventory…</p>

  const daemons  = data.inventory.filter((e) => e.status !== 'n/a' && e.status !== 'unknown')
  const runtimes = data.inventory.filter((e) => e.status === 'n/a'  || e.status === 'unknown')

  return (
    <div className="mt-6 space-y-6">
      {daemons.length > 0 && (
        <div className="glass-card overflow-hidden">
          <div className="px-4 py-3 border-b border-white/5 bg-white/5 flex items-center justify-between">
            <h3 className="text-xs font-bold uppercase tracking-widest text-slate-400 flex items-center gap-2">
              <Server className="w-3.5 h-3.5 text-brand-purple" />
              Services
            </h3>
            {isFetching && <RefreshCw className="w-3 h-3 animate-spin text-slate-500" />}
          </div>
          <table className="w-full text-left">
            <thead className="text-[10px] text-slate-500 uppercase tracking-widest bg-brand-dark/20">
              <tr>
                <th className="px-4 py-2 font-medium">Service</th>
                <th className="px-4 py-2 font-medium">Version</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Uptime</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {daemons.map((e) => (
                <tr key={e.name} className="hover:bg-white/5 transition-colors">
                  <td className="px-4 py-2.5 text-sm font-medium text-slate-200">{e.name}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-slate-400">
                    {e.version === 'not found' ? <span className="text-slate-600">not installed</span> : e.version}
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-1.5">
                      <ServiceStatus status={e.status} />
                      <span className={`text-xs ${e.status === 'active' ? 'text-brand-neon' : e.status === 'failed' ? 'text-red-400' : 'text-slate-500'}`}>
                        {e.status}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-slate-500">
                    {uptimeSince(e.uptime_since)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {runtimes.length > 0 && (
        <div className="glass-card overflow-hidden">
          <div className="px-4 py-3 border-b border-white/5 bg-white/5">
            <h3 className="text-xs font-bold uppercase tracking-widest text-slate-400 flex items-center gap-2">
              <Package className="w-3.5 h-3.5 text-brand-purple" />
              Runtimes
            </h3>
          </div>
          <table className="w-full text-left">
            <thead className="text-[10px] text-slate-500 uppercase tracking-widest bg-brand-dark/20">
              <tr>
                <th className="px-4 py-2 font-medium">Runtime</th>
                <th className="px-4 py-2 font-medium">Version</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {runtimes.map((e) => (
                <tr key={e.name} className="hover:bg-white/5 transition-colors">
                  <td className="px-4 py-2.5 text-sm font-medium text-slate-200">{e.name}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-slate-400">
                    {e.version === 'not found' ? <span className="text-slate-600">not installed</span> : e.version}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Snapshot card ─────────────────────────────────────────────────────────────

function MeterRow({
  label,
  metric,
  color,
}: {
  label: string
  metric: ServerHealthSnapshot['cpu'] | null | undefined
  color: string
}) {
  if (!metric) return null
  const over = metric.value != null && metric.value >= metric.threshold * 0.9
  const TrendIcon = metric.trend === 'up' ? TrendingUp : metric.trend === 'down' ? TrendingDown : Minus
  const trendColor = metric.trend === 'up' && metric.baseline != null && metric.value != null && metric.value > metric.baseline * 1.05
    ? '#F87171' : metric.trend === 'down' ? '#34D399' : '#64748B'

  return (
    <div>
      <div className="grid items-center gap-x-2" style={{ gridTemplateColumns: '40px 1fr 14px auto' }}>
        <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">{label}</span>
        <TrendBar
          value={metric.value ?? 0}
          threshold={metric.threshold}
          baseline={metric.baseline ?? undefined}
          color={color}
          height={5}
        />
        <TrendIcon size={11} style={{ color: trendColor }} />
        <span
          className="font-mono text-xs font-bold text-right"
          style={{ color: over ? '#F87171' : 'var(--tw-text-opacity, #e2e8f0)', minWidth: 36 }}
        >
          {metric.value ?? '—'}%
        </span>
      </div>
      {metric.projection && (
        <div className="text-[10px] text-amber-400 ml-11 mt-0.5">↗ {metric.projection}</div>
      )}
    </div>
  )
}

function SnapshotCard({
  server,
  snapshot,
  onClick,
}: {
  server: ServerStatus
  snapshot: ServerHealthSnapshot | null
  onClick: () => void
}) {
  const { t } = useTranslation()
  const offline = snapshot == null || snapshot.cpu?.value == null
  const state = (snapshot?.state ?? 'quiet') as HealthState
  const stateColor = { ok: '#34D399', attention: '#F59E0B', critical: '#F87171', quiet: '#94A3B8' }[state]

  return (
    <button
      onClick={onClick}
      className="glass-card p-5 text-left cursor-pointer relative overflow-hidden w-full"
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
      {/* State stripe */}
      <div style={{ position: 'absolute', top: 0, right: 0, width: 3, height: '100%', background: stateColor }} />

      {/* Header */}
      <div className="flex items-center gap-2.5 mb-4">
        <div className="w-8 h-8 rounded-lg bg-brand-slate flex items-center justify-center flex-shrink-0">
          <Server size={16} className="text-brand-purple" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-mono text-sm font-bold text-slate-100 truncate">{server.server_id}</div>
          <div className="text-[10px] text-slate-500 uppercase">{server.agent_version ?? 'unknown'}</div>
        </div>
        <HealthScore state={state} size="sm" />
      </div>

      {/* Headline */}
      {snapshot?.headline && (
        <p className="text-xs text-slate-300 mb-3 leading-relaxed">{snapshot.headline}</p>
      )}

      {/* Metrics */}
      {offline ? (
        <div className="flex items-center gap-2 py-3 text-xs text-slate-500">
          <WifiOff size={14} />
          <span>{t('infrastructure.noMetrics')}</span>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <MeterRow label={t('health.metrics.cpu')}    metric={snapshot?.cpu}    color="#39FF14" />
          <MeterRow label={t('health.metrics.memory').slice(0, 3)} metric={snapshot?.memory} color="#7C3AED" />
          <MeterRow label={t('health.metrics.disk')}   metric={snapshot?.disk}   color="#F59E0B" />
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between mt-4 pt-3 border-t border-white/5">
        <div className="flex items-center gap-1">
          {(snapshot?.critical_services ?? []).slice(0, 5).map((svc) => (
            <div
              key={svc.name}
              title={`${svc.name} · ${svc.ok ? 'active' : 'failed'}`}
              style={{
                width: 6, height: 6, borderRadius: '50%',
                background: svc.ok ? '#39FF14' : '#F87171',
                boxShadow: svc.ok ? '0 0 4px rgba(57,255,20,0.5)' : 'none',
              }}
            />
          ))}
          <span className="font-mono text-[10px] text-slate-500 ml-1">
            {t('infrastructure.services', { count: (snapshot?.critical_services ?? []).length })}
          </span>
        </div>
        {(snapshot?.anomalies6h ?? 0) > 0 ? (
          <span className="font-mono text-[10px] text-amber-400">
            {t('health.anomalies6h', { count: snapshot!.anomalies6h })}
          </span>
        ) : (
          <span className="font-mono text-[10px] text-slate-600">0 anomalies</span>
        )}
      </div>
    </button>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function Infrastructure({ setView }: InfrastructureProps) {
  const { t } = useTranslation()
  const { data: servers, isLoading, isError } = useServers()
  const selectedAgentId = useUIStore((s) => s.selectedAgentId)
  const setSelectedAgentId = useUIStore((s) => s.setSelectedAgentId)

  // Health snapshots for all servers in parallel
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

  const serverId = selectedAgentId
    ?? servers?.find((s) => s.status === 'online')?.server_id
    ?? servers?.[0]?.server_id
    ?? ''

  const handleSelect = (id: string) => {
    setSelectedAgentId(id)
    setView('server')
  }

  return (
    <Layout currentView="infrastructure" setView={setView} title={t('infrastructure.title')}>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-slate-100 mb-1.5">{t('infrastructure.title')}</h1>
        <p className="text-slate-400 text-sm">{t('infrastructure.subtitle')}</p>
      </div>

      {isLoading && <p className="text-slate-400 text-sm">{t('common.loading')}</p>}
      {isError   && <p className="text-red-400 text-sm">Error loading servers.</p>}

      {servers && servers.length === 0 && (
        <div className="glass-card p-10 text-center">
          <Server className="w-10 h-10 text-slate-600 mx-auto mb-3" />
          <p className="text-slate-500 text-sm">No servers registered yet.</p>
        </div>
      )}

      <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))' }}>
        {servers?.map((server) => (
          <SnapshotCard
            key={server.server_id}
            server={server}
            snapshot={snapshots[server.server_id] ?? null}
            onClick={() => handleSelect(server.server_id)}
          />
        ))}
      </div>

      {serverId && <InventoryTable serverId={serverId} />}
    </Layout>
  )
}
