import React from 'react'
import { Activity, Shield, Server } from 'lucide-react'
import Layout from './Layout'
import type { ViewType } from '../App'
import { useServers } from '../hooks/useServers'
import { useUIStore } from '../store/uiStore'

interface DashboardProps {
  setView: (view: ViewType) => void
}

const Dashboard: React.FC<DashboardProps> = ({ setView }) => {
  const { data: servers, isLoading } = useServers()
  const setSelectedAgentId = useUIStore((s) => s.setSelectedAgentId)

  const online  = servers?.filter((s) => s.status === 'online').length  ?? 0
  const offline = servers?.filter((s) => s.status === 'offline').length ?? 0
  const total   = servers?.length ?? 0

  return (
    <Layout currentView="dashboard" setView={setView} title="Observabilidade Geral">
      <div className="space-y-8">
        {/* Stats */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="glass-card p-6 border-l-4 border-l-brand-purple/50">
            <div className="flex justify-between items-start mb-2">
              <span className="text-slate-400 text-xs font-semibold uppercase tracking-wider">Servidores Ativos</span>
              <Server className="w-5 h-5 text-brand-purple" />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-bold font-mono">{isLoading ? '…' : online}</span>
              {!isLoading && (
                <span className="text-[10px] font-semibold text-slate-400">de {total} ({offline} offline)</span>
              )}
            </div>
          </div>

          <div className="glass-card p-6 border-l-4 border-l-brand-neon/50">
            <div className="flex justify-between items-start mb-2">
              <span className="text-slate-400 text-xs font-semibold uppercase tracking-wider">Agentes Online</span>
              <Activity className="w-5 h-5 text-brand-neon" />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-bold font-mono">{isLoading ? '…' : online}</span>
              <span className="text-[10px] font-semibold text-brand-neon">coletando métricas</span>
            </div>
          </div>

          <div className="glass-card p-6 border-l-4 border-l-brand-neon/50">
            <div className="flex justify-between items-start mb-2">
              <span className="text-slate-400 text-xs font-semibold uppercase tracking-wider">Incidentes Críticos</span>
              <Shield className="w-5 h-5 text-brand-neon" />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-bold font-mono">0</span>
              <span className="text-[10px] font-semibold text-slate-400">last 24h</span>
            </div>
          </div>
        </div>

        {/* Server list preview */}
        <section className="glass-card p-6">
          <div className="flex justify-between items-center mb-5">
            <h3 className="font-semibold text-slate-200">Servidores</h3>
            <button
              onClick={() => setView('infrastructure')}
              className="text-[10px] text-slate-500 hover:text-brand-purple transition-colors uppercase tracking-widest font-mono"
            >
              Ver todos
            </button>
          </div>

          {isLoading && <p className="text-slate-500 text-sm">Carregando...</p>}

          <div className="space-y-2">
            {servers?.map((server) => (
              <button
                key={server.server_id}
                onClick={() => {
                  setSelectedAgentId(server.server_id)
                  setView('server')
                }}
                className="w-full flex items-center justify-between p-3 bg-white/5 hover:bg-white/10 border border-white/5 rounded-lg transition-all text-left"
              >
                <div className="flex items-center gap-3">
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                    server.status === 'online'  ? 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.8)]'
                    : server.status === 'offline' ? 'bg-red-500'
                    : 'bg-slate-500'
                  }`} />
                  <span className="text-sm font-mono">{server.server_id}</span>
                </div>
                <span className={`text-xs capitalize ${
                  server.status === 'online'  ? 'text-emerald-400'
                  : server.status === 'offline' ? 'text-red-400'
                  : 'text-slate-400'
                }`}>
                  {server.status}
                </span>
              </button>
            ))}
          </div>
        </section>
      </div>
    </Layout>
  )
}

export default Dashboard
