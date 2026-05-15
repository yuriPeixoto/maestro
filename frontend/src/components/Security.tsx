import { ShieldAlert, ShieldCheck, Eye, Lock, RefreshCw } from 'lucide-react'
import Layout from './Layout'
import type { ViewType } from '../App'
import { useServers } from '../hooks/useServers'
import { useSshEvents } from '../hooks/useSecurity'
import type { SshEvent } from '../services/api'

interface SecurityProps {
  setView: (view: ViewType) => void
}

const resultStyle: Record<string, string> = {
  Blocked: 'bg-red-500/10 text-red-400 border-red-500/20',
  Dropped: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
  Success: 'bg-brand-neon/10 text-brand-neon border-brand-neon/20',
}

function EventRow({ ev }: { ev: SshEvent }) {
  const time = new Date(ev.timestamp).toLocaleTimeString('pt-BR', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  })
  return (
    <tr className="hover:bg-white/5 transition-colors">
      <td className="px-4 py-3 text-xs font-mono text-slate-500 shrink-0">{time}</td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <Lock className="w-3 h-3 text-brand-purple opacity-50 shrink-0" />
          <span className="text-sm font-medium">{ev.action}</span>
        </div>
      </td>
      <td className="px-4 py-3 font-mono text-xs text-slate-400">{ev.source_ip}</td>
      <td className="px-4 py-3 font-mono text-xs text-slate-300">{ev.username}</td>
      <td className="px-4 py-3">
        <span className={`text-[10px] px-2 py-0.5 rounded-full border ${resultStyle[ev.result] ?? 'bg-slate-500/10 text-slate-400 border-slate-500/20'}`}>
          {ev.result}
        </span>
      </td>
    </tr>
  )
}

export default function Security({ setView }: SecurityProps) {
  const { data: servers } = useServers()
  const serverId = servers?.[0]?.server_id ?? ''
  const { data, isFetching, isError } = useSshEvents(serverId)

  const stats = data?.stats
  const events = data?.events ?? []
  const blockedEvents = events.filter((e) => e.result === 'Blocked' || e.result === 'Dropped')
  const successEvents = events.filter((e) => e.result === 'Success')

  return (
    <Layout currentView="security" setView={setView} title="Segurança da Infraestrutura">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* Main column */}
        <div className="lg:col-span-2 space-y-6">

          {/* Stats bar */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="glass-card p-4">
              <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">Tentativas / 1h</p>
              <p className="text-2xl font-bold font-mono text-red-400">
                {stats ? stats.attempts_1h.toLocaleString() : '—'}
              </p>
            </div>
            <div className="glass-card p-4">
              <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">Tentativas / 24h</p>
              <p className="text-2xl font-bold font-mono text-orange-400">
                {stats ? stats.attempts_24h.toLocaleString() : '—'}
              </p>
            </div>
            <div className="glass-card p-4">
              <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">IPs únicos / 24h</p>
              <p className="text-2xl font-bold font-mono text-slate-200">
                {stats ? stats.unique_ips_24h.toLocaleString() : '—'}
              </p>
            </div>
            <div className="glass-card p-4">
              <p className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">Usuário mais visado</p>
              <p className="text-lg font-bold font-mono text-brand-purple truncate">
                {stats?.top_target ?? '—'}
              </p>
            </div>
          </div>

          {/* Audit log */}
          <div className="glass-card overflow-hidden">
            <div className="p-4 border-b border-white/5 bg-white/5 flex items-center justify-between">
              <h3 className="text-sm font-bold flex items-center gap-2">
                <Eye className="w-4 h-4 text-brand-purple" />
                Audit Log — SSH / Auth
              </h3>
              <div className="flex items-center gap-2 text-xs text-slate-500">
                {isFetching && <RefreshCw className="w-3 h-3 animate-spin" />}
                <span>{events.length} eventos recentes</span>
              </div>
            </div>

            {isError && (
              <p className="px-6 py-4 text-xs text-red-400">Erro ao carregar eventos de segurança.</p>
            )}

            {!isError && events.length === 0 && !isFetching && (
              <p className="px-6 py-6 text-xs text-slate-500 text-center">Nenhum evento encontrado no auth.log.</p>
            )}

            {events.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead className="text-[10px] text-slate-500 uppercase tracking-widest bg-brand-dark/20">
                    <tr>
                      <th className="px-4 py-3 font-medium">Hora</th>
                      <th className="px-4 py-3 font-medium">Evento</th>
                      <th className="px-4 py-3 font-medium">IP Origem</th>
                      <th className="px-4 py-3 font-medium">Usuário</th>
                      <th className="px-4 py-3 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {events.map((ev, i) => <EventRow key={`${ev.timestamp}-${i}`} ev={ev} />)}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        {/* Sidebar */}
        <div className="space-y-6">

          {/* Intrusion alert */}
          <div className={`glass-card p-6 ${(stats?.attempts_1h ?? 0) > 0 ? 'border-red-500/20 bg-red-500/5' : 'border-brand-neon/20 bg-brand-neon/5'}`}>
            <div className="flex items-center gap-3 mb-4">
              {(stats?.attempts_1h ?? 0) > 0
                ? <ShieldAlert className="w-6 h-6 text-red-500" />
                : <ShieldCheck className="w-6 h-6 text-brand-neon" />
              }
              <h3 className={`font-bold ${(stats?.attempts_1h ?? 0) > 0 ? 'text-red-400' : 'text-brand-neon'}`}>
                Alertas de Intrusão
              </h3>
            </div>
            {stats ? (
              <div className="space-y-2 text-xs text-slate-300">
                {stats.attempts_1h > 0
                  ? <p><span className="text-red-400 font-bold">{stats.attempts_1h}</span> tentativas na última hora</p>
                  : <p className="text-brand-neon">Nenhuma tentativa na última hora.</p>
                }
                <p><span className="font-bold">{stats.attempts_24h}</span> tentativas nas últimas 24h</p>
                <p><span className="font-bold">{stats.unique_ips_24h}</span> IPs distintos</p>
                {stats.top_target && (
                  <p>Alvo principal: <span className="font-mono text-brand-purple">{stats.top_target}</span></p>
                )}
              </div>
            ) : (
              <p className="text-xs text-slate-500">Carregando...</p>
            )}
          </div>

          {/* Session summary */}
          <div className="glass-card p-6">
            <h3 className="font-bold text-sm mb-4 flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-brand-purple" />
              Resumo da Sessão
            </h3>
            <div className="space-y-3">
              <div className="flex justify-between items-center text-xs">
                <span className="text-slate-400">Bloqueios detectados</span>
                <span className="font-mono font-bold text-red-400">{blockedEvents.length}</span>
              </div>
              <div className="flex justify-between items-center text-xs">
                <span className="text-slate-400">Logins bem-sucedidos</span>
                <span className="font-mono font-bold text-brand-neon">{successEvents.length}</span>
              </div>
              <div className="flex justify-between items-center text-xs">
                <span className="text-slate-400">Servidor monitorado</span>
                <span className="font-mono text-slate-300">{serverId || '—'}</span>
              </div>
              <div className="flex justify-between items-center text-xs">
                <span className="text-slate-400">fail2ban</span>
                <span className="text-[10px] text-brand-neon font-bold">● ACTIVE</span>
              </div>
            </div>
          </div>
        </div>

      </div>
    </Layout>
  )
}
