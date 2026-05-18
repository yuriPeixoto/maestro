import React, { useState } from 'react'
import Layout from './Layout'
import type { ViewType } from '../App'
import { AlertTriangle, CheckCircle, Clock, Plus, Trash2, X, Loader2 } from 'lucide-react'
import { useUIStore } from '../store/uiStore'
import { useServers } from '../hooks/useServers'
import { useAlertEvents, useAlertRules, useCreateAlertRule, useDeleteAlertRule } from '../hooks/useAlerts'
import type { AlertRuleIn } from '../services/api'

interface AlertsProps {
  setView: (view: ViewType) => void
}

const OPERATORS = ['>', '<', '>=', '<=', '==']
const METRICS_COMMON = ['cpu_percent', 'memory_percent', 'disk_percent', 'load_1m']

const severityBadge = (s: 'warning' | 'critical') =>
  s === 'critical'
    ? 'bg-red-500/10 text-red-400 border-red-500/20'
    : 'bg-orange-500/10 text-orange-400 border-orange-500/20'

function RuleForm({ serverId, onClose }: { serverId: string; onClose: () => void }) {
  const create = useCreateAlertRule(serverId)
  const [form, setForm] = useState<AlertRuleIn>({
    metric_name: 'cpu_percent',
    operator: '>',
    threshold: 80,
    severity: 'warning',
    cooldown_minutes: 5,
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    create.mutate(form, { onSuccess: onClose })
  }

  const field = (label: string, node: React.ReactNode) => (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] text-slate-400 uppercase tracking-widest font-bold">{label}</span>
      {node}
    </label>
  )

  const inputCls = 'bg-brand-slate border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-brand-purple/50 transition-all'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <form
        onSubmit={handleSubmit}
        className="glass-card w-full max-w-md p-6 space-y-4 relative"
      >
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-base font-bold">Nova Regra de Alerta</h3>
          <button type="button" onClick={onClose} className="text-slate-500 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>

        {field('Métrica',
          <input
            list="metric-suggestions"
            value={form.metric_name}
            onChange={(e) => setForm({ ...form, metric_name: e.target.value })}
            className={inputCls}
            required
          />
        )}
        <datalist id="metric-suggestions">
          {METRICS_COMMON.map((m) => <option key={m} value={m} />)}
        </datalist>

        <div className="grid grid-cols-2 gap-3">
          {field('Operador',
            <select value={form.operator} onChange={(e) => setForm({ ...form, operator: e.target.value })} className={inputCls}>
              {OPERATORS.map((o) => <option key={o}>{o}</option>)}
            </select>
          )}
          {field('Threshold',
            <input
              type="number"
              step="any"
              value={form.threshold}
              onChange={(e) => setForm({ ...form, threshold: parseFloat(e.target.value) })}
              className={inputCls}
              required
            />
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          {field('Severidade',
            <select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value as 'warning' | 'critical' })} className={inputCls}>
              <option value="warning">Warning</option>
              <option value="critical">Critical</option>
            </select>
          )}
          {field('Cooldown (min)',
            <input
              type="number"
              min={1}
              max={1440}
              value={form.cooldown_minutes}
              onChange={(e) => setForm({ ...form, cooldown_minutes: parseInt(e.target.value) })}
              className={inputCls}
              required
            />
          )}
        </div>

        <button
          type="submit"
          disabled={create.isPending}
          className="w-full mt-2 py-2 rounded-lg bg-brand-purple hover:bg-brand-purple/80 text-white text-sm font-bold transition-all disabled:opacity-50 flex items-center justify-center gap-2"
        >
          {create.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
          Criar Regra
        </button>
        {create.isError && (
          <p className="text-xs text-red-400 text-center">Erro ao criar regra. Verifique os campos.</p>
        )}
      </form>
    </div>
  )
}

const Alerts: React.FC<AlertsProps> = ({ setView }) => {
  const selectedAgentId = useUIStore((s) => s.selectedAgentId)
  const { data: servers } = useServers()
  const serverId = selectedAgentId
    ?? servers?.find((s) => s.status === 'online')?.server_id
    ?? servers?.[0]?.server_id
    ?? ''
  const [showForm, setShowForm] = useState(false)

  const { data: eventsData, isLoading: loadingEvents } = useAlertEvents(serverId)
  const { data: rulesData, isLoading: loadingRules } = useAlertRules(serverId)
  const deleteRule = useDeleteAlertRule(serverId)

  const fmt = (iso: string) => {
    const d = new Date(iso)
    return d.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
  }

  return (
    <Layout currentView="alerts" setView={setView} title="Central de Alertas">
      {showForm && serverId && <RuleForm serverId={serverId} onClose={() => setShowForm(false)} />}

      <div className="space-y-8">
        {/* Rules */}
        <section>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-bold text-slate-200">Regras Ativas</h2>
            {!!serverId && (
              <button
                onClick={() => setShowForm(true)}
                className="flex items-center gap-2 text-xs font-bold text-brand-purple bg-brand-purple/10 border border-brand-purple/20 px-3 py-1.5 rounded-lg hover:bg-brand-purple/20 transition-all"
              >
                <Plus className="w-3.5 h-3.5" />
                Nova Regra
              </button>
            )}
          </div>

          {loadingRules ? (
            <div className="flex items-center gap-2 text-slate-500 text-sm"><Loader2 className="w-4 h-4 animate-spin" /> Carregando regras...</div>
          ) : rulesData?.rules.length === 0 ? (
            <p className="text-slate-500 text-sm">Nenhuma regra configurada.</p>
          ) : (
            <div className="space-y-2">
              {rulesData?.rules.map((rule) => (
                <div key={rule.rule_id} className="glass-card p-4 flex items-center gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono text-sm text-slate-200">{rule.metric_name}</span>
                      <span className="font-mono text-brand-purple">{rule.operator}</span>
                      <span className="font-mono text-slate-200">{rule.threshold}</span>
                      <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full border ${severityBadge(rule.severity)}`}>
                        {rule.severity}
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-500 mt-1">
                      Cooldown {rule.cooldown_minutes}min &bull; Criado {fmt(rule.created_at)}
                    </p>
                  </div>
                  <button
                    onClick={() => deleteRule.mutate(rule.rule_id)}
                    disabled={deleteRule.isPending}
                    className="text-slate-600 hover:text-red-400 transition-colors shrink-0"
                    title="Remover regra"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Events */}
        <section>
          <h2 className="text-base font-bold text-slate-200 mb-4">Histórico de Eventos</h2>

          {loadingEvents ? (
            <div className="flex items-center gap-2 text-slate-500 text-sm"><Loader2 className="w-4 h-4 animate-spin" /> Carregando eventos...</div>
          ) : eventsData?.events.length === 0 ? (
            <p className="text-slate-500 text-sm">Nenhum evento registrado.</p>
          ) : (
            <div className="space-y-2">
              {eventsData?.events.map((event) => (
                <div key={event.event_id} className="glass-card p-4 flex gap-4">
                  <div className="shrink-0 mt-0.5">
                    {event.state === 'FIRING'
                      ? <AlertTriangle className={`w-4 h-4 ${event.severity === 'critical' ? 'text-red-400' : 'text-orange-400'}`} />
                      : <CheckCircle className="w-4 h-4 text-brand-neon" />
                    }
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-bold text-sm text-slate-200">{event.metric_name}</span>
                      <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full border ${event.state === 'FIRING' ? severityBadge(event.severity) : 'bg-brand-neon/10 text-brand-neon border-brand-neon/20'}`}>
                        {event.state}
                      </span>
                    </div>
                    <p className="text-xs text-slate-400 mt-0.5">
                      Valor: <span className="font-mono text-slate-200">{event.value.toFixed(2)}</span>
                      {' '}&bull; Threshold: <span className="font-mono text-slate-200">{event.threshold}</span>
                    </p>
                  </div>
                  <div className="flex items-center gap-1 text-[10px] text-slate-500 font-mono shrink-0">
                    <Clock className="w-3 h-3" />
                    <span>{fmt(event.triggered_at)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </Layout>
  )
}

export default Alerts
