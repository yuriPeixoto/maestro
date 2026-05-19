import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronUp, MapPin, Users, ShieldCheck, Shield } from 'lucide-react'
import Layout from './Layout'
import type { ViewType } from '../App'
import { HealthScore } from './primitives'
import type { HealthState } from './primitives'
import { useServers } from '../hooks/useServers'
import { useSshEvents } from '../hooks/useSecurity'
import { useAttackers, useAttackByHour, useSshBaseline } from '../hooks/useMetrics'
import { useUIStore } from '../store/uiStore'
import type { SshEvent } from '../services/api'

interface SecurityProps {
  setView: (view: ViewType) => void
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function relative(iso: string): string {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60)    return `${diff}s ago`
  if (diff < 3600)  return `${Math.floor(diff / 60)}min ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

// ── Hourly bar chart ──────────────────────────────────────────────────────────

function HourlyBars({ hourly, baselinePerHour, color }: { hourly: { hour: number; count: number }[], baselinePerHour: number, color: string }) {
  const max = Math.max(...hourly.map((h) => h.count), baselinePerHour, 1)
  const basePct = (baselinePerHour / max) * 100

  return (
    <div style={{ position: 'relative', height: 80, display: 'flex', alignItems: 'flex-end', gap: 3 }}>
      {hourly.map((h, i) => {
        const pct = (h.count / max) * 100
        const over = h.count > baselinePerHour * 2
        return (
          <div
            key={i}
            title={`${h.hour}h · ${h.count} attempts`}
            style={{
              flex: 1,
              height: `${Math.max(pct, 1)}%`,
              background: over ? '#F87171' : color,
              opacity: over ? 1 : 0.7,
              borderRadius: '2px 2px 0 0',
              minHeight: 2,
            }}
          />
        )
      })}
      {/* Baseline line */}
      <div style={{
        position: 'absolute', left: 0, right: 0,
        bottom: `${basePct}%`,
        height: 1,
        background: 'rgba(255,255,255,0.35)',
        pointerEvents: 'none',
      }} />
    </div>
  )
}

// ── Threat hero ───────────────────────────────────────────────────────────────

function ThreatHero({
  today,
  baseline,
  ratio,
  state,
  hourly,
  peakHour,
}: {
  today: number
  baseline: number
  ratio: number
  state: HealthState
  hourly: { hour: number; count: number }[]
  peakHour: { hour: number; count: number }
}) {
  const { t } = useTranslation()
  const conf = {
    ok:        { fg: '#34D399', soft: 'rgba(52,211,153,0.06)', border: 'rgba(52,211,153,0.20)', label: 'normal' },
    attention: { fg: '#F59E0B', soft: 'rgba(245,158,11,0.06)', border: 'rgba(245,158,11,0.22)', label: 'elevated' },
    critical:  { fg: '#F87171', soft: 'rgba(239,68,68,0.06)',  border: 'rgba(239,68,68,0.22)',  label: 'critical' },
    quiet:     { fg: '#94A3B8', soft: 'rgba(148,163,184,0.06)', border: 'rgba(148,163,184,0.20)', label: 'normal' },
  }[state]

  const peakLabel = `${String(peakHour.hour).padStart(2, '0')}:00–${String(peakHour.hour + 1).padStart(2, '0')}:00`

  return (
    <div
      className="glass-card"
      style={{
        padding: 24, position: 'relative', overflow: 'hidden',
        borderColor: conf.border,
        background: `linear-gradient(180deg, ${conf.soft} 0%, transparent 50%), rgba(30,41,59,0.4)`,
      }}
    >
      <div className="grid items-center gap-8" style={{ gridTemplateColumns: 'auto 1fr' }}>
        <div>
          <div className="flex items-center gap-2 mb-2.5">
            <span className="text-[10px] font-mono font-bold uppercase tracking-widest" style={{ color: conf.fg }}>
              {t('security.ssh24h')}
            </span>
            <HealthScore state={state} size="sm" />
          </div>
          <div className="flex items-baseline gap-3">
            <span className="font-mono font-bold text-slate-100 tabular-nums" style={{ fontSize: 44, letterSpacing: '-0.02em', lineHeight: 1 }}>
              {today.toLocaleString()}
            </span>
            <span className="text-sm text-slate-400">{t('security.attempts')}</span>
          </div>
          <div className="text-sm text-slate-300 mt-2.5" style={{ lineHeight: 1.55, maxWidth: 360 }}>
            {t('security.weeklyAvg7d')}: <span className="font-mono">{baseline.toLocaleString()}</span>
            {' — '}
            <span className="font-mono font-bold" style={{ color: conf.fg }}>{ratio.toFixed(1)}× {conf.label}</span>
            <br />
            {t('security.peakAt')} <span className="font-mono">{peakLabel}</span>
            {' with '}<span className="font-mono">{peakHour.count}</span>{' attempts.'}
          </div>
        </div>

        <div>
          <HourlyBars hourly={hourly} baselinePerHour={baseline / 24} color={conf.fg} />
          <div className="flex justify-between mt-1.5 font-mono text-[9px] text-slate-600">
            <span>00h</span><span>06h</span><span>12h</span><span>18h</span><span>24h</span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Attacker row ──────────────────────────────────────────────────────────────

function AttackerRow({ attacker }: { attacker: { ip: string; attempts: number; users: string[]; last_seen: string; blocked: boolean } }) {
  const [expanded, setExpanded] = useState(false)
  const { t } = useTranslation()
  const sev = attacker.attempts >= 500 ? 'critical' : attacker.attempts >= 100 ? 'attention' : 'ok'
  const sevColor = { ok: '#34D399', attention: '#F59E0B', critical: '#F87171' }[sev]

  return (
    <div className="border-t border-white/5">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full p-3.5 text-left transition-colors hover:bg-white/3"
        style={{ display: 'grid', gridTemplateColumns: 'auto 1fr auto auto auto auto', gap: 16, alignItems: 'center' }}
      >
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: sevColor, flexShrink: 0, boxShadow: sev === 'ok' ? `0 0 6px ${sevColor}88` : 'none' }} />
        <div>
          <div className="font-mono text-[13px] font-bold text-slate-100">{attacker.ip}</div>
          <div className="text-[11px] text-slate-500 mt-0.5 flex items-center gap-1">
            <MapPin size={10} />
            <span className="font-mono">{attacker.ip.startsWith('10.') || attacker.ip.startsWith('192.168.') ? 'private' : 'public'}</span>
            <span className="mx-1.5 text-slate-700">·</span>
            <span>{relative(attacker.last_seen)}</span>
          </div>
        </div>
        <div className="text-right">
          <div className="font-mono text-base font-bold" style={{ color: sevColor }}>{attacker.attempts.toLocaleString()}</div>
          <div className="text-[10px] text-slate-500">{t('security.attackers.attempts', { count: attacker.attempts }).split(' ')[0]}</div>
        </div>
        <div className="text-right">
          <div className="font-mono text-sm text-slate-300">{attacker.users.length}</div>
          <div className="text-[10px] text-slate-500">users</div>
        </div>
        {attacker.blocked
          ? <span className="text-[10px] px-2 py-0.5 rounded-full border bg-brand-neon/10 text-brand-neon border-brand-neon/20 font-mono font-bold">BLOCKED</span>
          : <span className="text-[10px] px-2 py-0.5 rounded-full border bg-orange-500/10 text-orange-400 border-orange-500/20 font-mono font-bold">ACTIVE</span>
        }
        {expanded ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
      </button>

      {expanded && (
        <div className="px-3.5 pb-4 pl-10 flex flex-col gap-2">
          <div className="text-xs text-slate-400">{t('security.attackers.users')}</div>
          <div className="flex flex-wrap gap-1.5">
            {attacker.users.map((u) => (
              <span key={u} className="px-2 py-0.5 rounded text-xs font-mono text-slate-300 bg-brand-slate border border-white/10">
                {u}
              </span>
            ))}
          </div>
          <div className="mt-1 text-[11px] font-mono text-slate-500">
            target: {attacker.users[0]} · {attacker.attempts} attacks · status: {attacker.blocked ? t('security.attackers.blockedByFail2ban') : t('security.attackers.underObservation')}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Session summary side card ─────────────────────────────────────────────────

function SessionSummaryCard({ stats }: { stats: { attempts_1h: number; attempts_24h: number; unique_ips_24h: number; top_target: string | null } | undefined }) {
  const { t } = useTranslation()
  const Row = ({ k, v, mono = false, color }: { k: string; v: React.ReactNode; mono?: boolean; color?: string }) => (
    <div className="flex justify-between items-center text-xs">
      <span className="text-slate-400">{k}</span>
      <span className={`font-bold ${mono ? 'font-mono' : ''}`} style={{ color }}>{v}</span>
    </div>
  )
  return (
    <div className="glass-card p-5">
      <h3 className="text-sm font-bold flex items-center gap-2 mb-4">
        <ShieldCheck size={14} className="text-brand-purple" />
        {t('security.session.title')}
      </h3>
      <div className="flex flex-col gap-3">
        <Row k={t('security.session.attempts1h')}  v={stats?.attempts_1h  ?? '—'} color="#F87171" mono />
        <Row k={t('security.session.attempts24h')} v={stats?.attempts_24h?.toLocaleString() ?? '—'} color="var(--tw-text-opacity)" mono />
        <Row k={t('security.session.uniqueIps')}   v={stats?.unique_ips_24h ?? '—'} mono />
        <Row k={t('security.session.topTarget')}   v={stats?.top_target ?? '—'} color="#7C3AED" mono />
      </div>
    </div>
  )
}

function Fail2BanCard() {
  const { t } = useTranslation()
  return (
    <div className="glass-card p-5">
      <h3 className="text-sm font-bold flex items-center gap-2 mb-4">
        <Shield size={14} className="text-brand-purple" />
        {t('security.fail2ban.title')}
      </h3>
      <div className="flex items-center gap-2.5 p-2.5 rounded-lg bg-brand-neon/5 border border-brand-neon/20">
        <span className="w-2 h-2 rounded-full bg-brand-neon animate-pulse shadow-[0_0_8px_rgba(57,255,20,0.6)]" />
        <span className="font-mono text-xs text-brand-neon font-bold uppercase tracking-widest">active</span>
        <span className="flex-1" />
        <span className="text-[11px] text-slate-500 font-mono">v1.0.2</span>
      </div>
      <div className="text-xs text-slate-400 mt-2.5" style={{ lineHeight: 1.6 }}>
        {t('security.fail2ban.bansLast24h', { count: 4 })} Ban window: <span className="font-mono">10min</span>, max retries: <span className="font-mono">3</span>.
      </div>
    </div>
  )
}

// ── Audit log (kept from v1) ──────────────────────────────────────────────────

const resultStyle: Record<string, string> = {
  Blocked: 'bg-red-500/10 text-red-400 border-red-500/20',
  Dropped: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
  Success: 'bg-brand-neon/10 text-brand-neon border-brand-neon/20',
}

function EventRow({ ev }: { ev: SshEvent }) {
  const time = new Date(ev.timestamp).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
  return (
    <tr className="hover:bg-white/5 transition-colors">
      <td className="px-4 py-2.5 text-xs font-mono text-slate-500">{time}</td>
      <td className="px-4 py-2.5 text-sm text-slate-200">{ev.action}</td>
      <td className="px-4 py-2.5 font-mono text-xs text-slate-400">{ev.source_ip}</td>
      <td className="px-4 py-2.5 font-mono text-xs text-slate-300">{ev.username}</td>
      <td className="px-4 py-2.5">
        <span className={`text-[10px] px-2 py-0.5 rounded-full border ${resultStyle[ev.result] ?? 'bg-slate-500/10 text-slate-400 border-slate-500/20'}`}>
          {ev.result}
        </span>
      </td>
    </tr>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function Security({ setView }: SecurityProps) {
  const { t } = useTranslation()
  const { data: servers } = useServers()
  const selectedAgentId = useUIStore((s) => s.selectedAgentId)
  const serverId = selectedAgentId ?? servers?.find((s) => s.status === 'online')?.server_id ?? servers?.[0]?.server_id ?? ''

  const { data: sshData }      = useSshEvents(serverId)
  const { data: attackersData } = useAttackers(serverId)
  const { data: hourData }     = useAttackByHour(serverId)
  const { data: baselineData } = useSshBaseline(serverId)

  const stats    = sshData?.stats
  const today    = stats?.attempts_24h ?? 0
  const baseline = baselineData?.avg_daily ?? 0
  const ratio    = baseline > 0 ? today / baseline : 0
  const hourly   = hourData?.hours ?? Array.from({ length: 24 }, (_, i) => ({ hour: i, count: 0 }))
  const peakHour = [...hourly].sort((a, b) => b.count - a.count)[0] ?? { hour: 0, count: 0 }

  const severityState: HealthState = ratio > 2.5 ? 'critical' : ratio > 1.5 ? 'attention' : 'ok'
  const attackers = attackersData?.attackers ?? []
  const events    = sshData?.events ?? []

  return (
    <Layout currentView="security" setView={setView} title={t('security.title')}>
      <div className="flex flex-col gap-6">

        {/* Threat hero */}
        <ThreatHero
          today={today}
          baseline={baseline}
          ratio={ratio}
          state={severityState}
          hourly={hourly}
          peakHour={peakHour}
        />

        {/* Two-column: attackers + side */}
        <div className="grid gap-6" style={{ gridTemplateColumns: '2fr 1fr' }}>

          {/* Attackers grouped by IP */}
          <div className="glass-card overflow-hidden">
            <div className="px-4 py-3 border-b border-white/5 bg-white/5 flex items-center justify-between">
              <h3 className="text-sm font-bold flex items-center gap-2">
                <Users size={14} className="text-brand-purple" />
                {t('security.attackers.title')}
              </h3>
              <span className="text-[11px] font-mono text-slate-500">
                {t('security.attackers.ips', { count: attackers.length })} · {attackers.reduce((s, a) => s + a.attempts, 0).toLocaleString()} attempts
              </span>
            </div>
            {attackers.length === 0 ? (
              <p className="px-5 py-6 text-xs text-slate-500 text-center">No attackers detected in the last 24h.</p>
            ) : (
              attackers.map((a) => <AttackerRow key={a.ip} attacker={a} />)
            )}
          </div>

          {/* Side: session + fail2ban */}
          <div className="flex flex-col gap-4">
            <SessionSummaryCard stats={stats} />
            <Fail2BanCard />
          </div>
        </div>

        {/* Audit log (detail) */}
        {events.length > 0 && (
          <div className="glass-card overflow-hidden">
            <div className="px-4 py-3 border-b border-white/5 bg-white/5">
              <h3 className="text-sm font-bold">Audit Log — SSH / Auth</h3>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="text-[10px] text-slate-500 uppercase tracking-widest bg-brand-dark/20">
                  <tr>
                    <th className="px-4 py-2 font-medium">Time</th>
                    <th className="px-4 py-2 font-medium">Event</th>
                    <th className="px-4 py-2 font-medium">Source IP</th>
                    <th className="px-4 py-2 font-medium">User</th>
                    <th className="px-4 py-2 font-medium">Result</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {events.map((ev, i) => <EventRow key={`${ev.timestamp}-${i}`} ev={ev} />)}
                </tbody>
              </table>
            </div>
          </div>
        )}

      </div>
    </Layout>
  )
}
