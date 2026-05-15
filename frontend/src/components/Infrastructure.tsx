import React from 'react'
import { Server, Network, Clock } from 'lucide-react'
import Layout from './Layout'
import type { ViewType } from '../App'
import { useServers } from '../hooks/useServers'
import { useUIStore } from '../store/uiStore'
import type { ServerStatus } from '../types/server'

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

const Infrastructure: React.FC<InfrastructureProps> = ({ setView }) => {
  const { data: servers, isLoading, isError } = useServers()
  const setSelectedAgentId = useUIStore((s) => s.setSelectedAgentId)

  const handleSelect = (serverId: string) => {
    setSelectedAgentId(serverId)
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

      {isLoading && (
        <p className="text-slate-400 text-sm">Carregando servidores...</p>
      )}
      {isError && (
        <p className="text-red-400 text-sm">Erro ao carregar servidores.</p>
      )}

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
    </Layout>
  )
}

export default Infrastructure
