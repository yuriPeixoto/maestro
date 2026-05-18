import { Server, Network, Clock, Package, CheckCircle, XCircle, HelpCircle, RefreshCw } from 'lucide-react'
import Layout from './Layout'
import type { ViewType } from '../App'
import { useServers } from '../hooks/useServers'
import { useUIStore } from '../store/uiStore'
import { useInventory } from '../hooks/useInventory'
import type { ServerStatus } from '../types/server'
import type { RuntimeEntry } from '../services/api'

interface InfrastructureProps {
  setView: (view: ViewType) => void
}

const statusDot: Record<ServerStatus['status'], string> = {
  online:  'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]',
  offline: 'bg-red-500',
  unknown: 'bg-slate-500',
}

const statusBar: Record<ServerStatus['status'], string> = {
  online:  'bg-emerald-400',
  offline: 'bg-red-500',
  unknown: 'bg-slate-600',
}

function timeAgo(iso: string | null): string {
  if (!iso) return '—'
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60) return `${diff}s atrás`
  if (diff < 3600) return `${Math.floor(diff / 60)}m atrás`
  return `${Math.floor(diff / 3600)}h atrás`
}

function uptimeSince(iso: string | null): string {
  if (!iso) return '—'
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 3600) return `${Math.floor(diff / 60)}m`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`
  return `${Math.floor(diff / 86400)}d`
}

function ServiceStatus({ status }: { status: string }) {
  if (status === 'active')
    return <CheckCircle className="w-3.5 h-3.5 text-brand-neon" />
  if (status === 'inactive' || status === 'failed')
    return <XCircle className="w-3.5 h-3.5 text-red-400" />
  return <HelpCircle className="w-3.5 h-3.5 text-slate-500" />
}

function InventoryTable({ serverId }: { serverId: string }) {
  const { data, isFetching, isError } = useInventory(serverId)

  if (isError) return <p className="text-xs text-red-400 mt-4">Erro ao carregar inventário.</p>
  if (!data) return <p className="text-xs text-slate-500 mt-4">Carregando inventário...</p>

  const daemons = data.inventory.filter((e) => e.status !== 'n/a' && e.status !== 'unknown')
  const runtimes = data.inventory.filter((e) => e.status === 'n/a' || e.status === 'unknown')

  return (
    <div className="mt-6 space-y-6">
      {daemons.length > 0 && (
        <div className="glass-card overflow-hidden">
          <div className="px-4 py-3 border-b border-white/5 bg-white/5 flex items-center justify-between">
            <h3 className="text-xs font-bold uppercase tracking-widest text-slate-400 flex items-center gap-2">
              <Server className="w-3.5 h-3.5 text-brand-purple" />
              Serviços
            </h3>
            {isFetching && <RefreshCw className="w-3 h-3 animate-spin text-slate-500" />}
          </div>
          <table className="w-full text-left">
            <thead className="text-[10px] text-slate-500 uppercase tracking-widest bg-brand-dark/20">
              <tr>
                <th className="px-4 py-2 font-medium">Serviço</th>
                <th className="px-4 py-2 font-medium">Versão</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Uptime</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {daemons.map((e) => (
                <ServiceRow key={e.name} entry={e} />
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
                <th className="px-4 py-2 font-medium">Versão</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {runtimes.map((e) => (
                <tr key={e.name} className="hover:bg-white/5 transition-colors">
                  <td className="px-4 py-2.5 text-sm font-medium text-slate-200">{e.name}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-slate-400">
                    {e.version === 'not found'
                      ? <span className="text-slate-600">não instalado</span>
                      : e.version}
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

function ServiceRow({ entry: e }: { entry: RuntimeEntry }) {
  return (
    <tr className="hover:bg-white/5 transition-colors">
      <td className="px-4 py-2.5 text-sm font-medium text-slate-200">{e.name}</td>
      <td className="px-4 py-2.5 font-mono text-xs text-slate-400">
        {e.version === 'not found'
          ? <span className="text-slate-600">não instalado</span>
          : e.version}
      </td>
      <td className="px-4 py-2.5">
        <div className="flex items-center gap-1.5">
          <ServiceStatus status={e.status} />
          <span className={`text-xs ${
            e.status === 'active' ? 'text-brand-neon'
            : e.status === 'failed' ? 'text-red-400'
            : 'text-slate-500'
          }`}>
            {e.status}
          </span>
        </div>
      </td>
      <td className="px-4 py-2.5 font-mono text-xs text-slate-500">
        {uptimeSince(e.uptime_since)}
      </td>
    </tr>
  )
}

export default function Infrastructure({ setView }: InfrastructureProps) {
  const { data: servers, isLoading, isError } = useServers()
  const selectedAgentId = useUIStore((s) => s.selectedAgentId)
  const setSelectedAgentId = useUIStore((s) => s.setSelectedAgentId)

  const serverId = selectedAgentId
    ?? servers?.find((s) => s.status === 'online')?.server_id
    ?? servers?.[0]?.server_id
    ?? ''

  const handleSelect = (id: string) => {
    setSelectedAgentId(id)
    setView('server')
  }

  return (
    <Layout currentView="infrastructure" setView={setView} title="Mapa de Servidores">
      <div className="space-y-4 mb-8">
        <h2 className="text-xl font-bold flex items-center gap-2">
          <Network className="w-5 h-5 text-brand-purple" />
          Servidores Monitorados
        </h2>
        <p className="text-slate-400 text-sm">
          Status em tempo real de todos os agentes Maestro registrados.
        </p>
      </div>

      {isLoading && <p className="text-slate-400 text-sm">Carregando servidores...</p>}
      {isError && <p className="text-red-400 text-sm">Erro ao carregar servidores.</p>}

      {servers && servers.length === 0 && (
        <div className="glass-card p-10 text-center">
          <Server className="w-10 h-10 text-slate-600 mx-auto mb-3" />
          <p className="text-slate-500 text-sm">Nenhum servidor registrado ainda.</p>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
        {servers?.map((server) => (
          <button
            key={server.server_id}
            onClick={() => handleSelect(server.server_id)}
            className="glass-card p-5 relative overflow-hidden text-left group hover:border-brand-purple/40 transition-all"
          >
            <div className={`absolute top-0 right-0 w-1 h-full ${statusBar[server.status]}`} />

            <div className="flex items-center gap-3 mb-4">
              <div className="p-2 bg-brand-slate rounded-lg">
                <Server className="w-4 h-4 text-brand-purple" />
              </div>
              <div className="min-w-0">
                <h3 className="text-sm font-bold font-mono tracking-tight truncate">{server.server_id}</h3>
                <span className="text-[10px] text-slate-500 uppercase">
                  {server.agent_version ?? 'versão desconhecida'}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-2 mt-4">
              <span className={`w-2 h-2 rounded-full flex-shrink-0 ${statusDot[server.status]}`} />
              <span className={`text-xs font-semibold capitalize ${
                server.status === 'online' ? 'text-emerald-400'
                : server.status === 'offline' ? 'text-red-400'
                : 'text-slate-400'
              }`}>
                {server.status}
              </span>
            </div>

            <div className="mt-3 pt-3 border-t border-white/5 flex items-center gap-1.5 font-mono text-[9px] text-slate-500 opacity-70 group-hover:opacity-100 transition-opacity">
              <Clock className="w-3 h-3" />
              <span>{timeAgo(server.last_seen)}</span>
            </div>
          </button>
        ))}
      </div>

      {serverId && <InventoryTable serverId={serverId} />}
    </Layout>
  )
}
