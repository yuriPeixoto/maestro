import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Layout from './Layout'
import type { ViewType } from '../App'
import {
  AlertTriangle, CheckCircle, Clock, Plus, Trash2, X, Loader2,
  Webhook, Save, Bell, BellOff, Activity, Minus,
} from 'lucide-react'
import { useUIStore } from '../store/uiStore'
import { useServers } from '../hooks/useServers'
import {
  useAlertEvents, useAlertRules, useCreateAlertRule,
  useDeleteAlertRule, useWebhookConfig, useSaveWebhook, useDeleteWebhook,
} from '../hooks/useAlerts'
import { useRulePatterns } from '../hooks/useMetrics'
import { TrendBar } from './primitives'
import type { AlertRule, AlertRuleIn, RulePattern } from '../services/api'

interface AlertsProps {
  setView: (view: ViewType) => void
}

const OPERATORS = ['>', '<', '>=', '<=', '==']
const METRICS_COMMON = ['cpu_usage_percent', 'memory_usage_percent', 'disk_usage_percent', 'load_1m']

type RuleState = 'dormant' | 'quiet' | 'active' | 'firing'

const STATE_CONF: Record<RuleState, { bg: string; text: string; border: string }> = {
  firing:  { bg: 'bg-red-500/15',    text: 'text-red-400',       border: 'border-red-500/30' },
  active:  { bg: 'bg-amber-500/15',  text: 'text-amber-400',     border: 'border-amber-500/30' },
  quiet:   { bg: 'bg-slate-500/15',  text: 'text-slate-400',     border: 'border-slate-500/30' },
  dormant: { bg: 'bg-slate-800/60',  text: 'text-slate-600',     border: 'border-slate-700/40' },
}

const SEV_CONF = {
  critical: 'bg-red-500/10 text-red-400 border-red-500/20',
  warning:  'bg-orange-500/10 text-orange-400 border-orange-500/20',
}

// ── Rule creation form ────────────────────────────────────────────────────────

function RuleForm({ serverId, onClose }: { serverId: string; onClose: () => void }) {
  const { t } = useTranslation()
  const create = useCreateAlertRule(serverId)
  const [form, setForm] = useState<AlertRuleIn>({
    metric_name: 'cpu_usage_percent',
    operator: '>',
    threshold: 80,
    severity: 'warning',
    cooldown_minutes: 5,
    alert_mode: 'static',
    ml_score_threshold: 0.7,
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
  const usesML = form.alert_mode === 'ml' || form.alert_mode === 'both'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <form onSubmit={handleSubmit} className="glass-card w-full max-w-md p-6 space-y-4 relative">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-base font-bold">{t('common.newRule')}</h3>
          <button type="button" onClick={onClose} className="text-slate-500 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>

        {field(t('health.metrics.cpu') + ' / Metric',
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

        {field(t('alerts.detection.label'),
          <select value={form.alert_mode} onChange={(e) => setForm({ ...form, alert_mode: e.target.value })} className={inputCls}>
            <option value="static">{t('alerts.detection.static')}</option>
            <option value="ml">{t('alerts.detection.ml')}</option>
            <option value="both">{t('alerts.detection.both')}</option>
          </select>
        )}

        <div className="grid grid-cols-2 gap-3">
          {field('Operator',
            <select value={form.operator} onChange={(e) => setForm({ ...form, operator: e.target.value })} className={inputCls}>
              {OPERATORS.map((o) => <option key={o}>{o}</option>)}
            </select>
          )}
          {field(t('health.metrics.threshold'),
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

        {usesML && field(t('alerts.detection.scoreThreshold'),
          <div className="flex items-center gap-3">
            <input
              type="range" min={0} max={1} step={0.05}
              value={form.ml_score_threshold}
              onChange={(e) => setForm({ ...form, ml_score_threshold: parseFloat(e.target.value) })}
              className="flex-1 accent-brand-purple"
            />
            <span className="font-mono text-sm text-slate-200 w-10 text-right">
              {form.ml_score_threshold?.toFixed(2)}
            </span>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          {field('Severity',
            <select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value as 'warning' | 'critical' })} className={inputCls}>
              <option value="warning">Warning</option>
              <option value="critical">Critical</option>
            </select>
          )}
          {field('Cooldown (min)',
            <input
              type="number" min={1} max={1440}
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
          {t('common.newRule')}
        </button>
        {create.isError && (
          <p className="text-xs text-red-400 text-center">Failed to create rule. Check the fields.</p>
        )}
      </form>
    </div>
  )
}

// ── Living rule card ──────────────────────────────────────────────────────────

function LivingRuleCard({
  rule,
  pattern,
  onDelete,
  deleting,
}: {
  rule: AlertRule
  pattern: RulePattern | null
  onDelete: () => void
  deleting: boolean
}) {
  const { t } = useTranslation()
  const state: RuleState = pattern?.state ?? 'quiet'
  const sc = STATE_CONF[state]
  const margin = pattern?.current_value != null
    ? Math.max(0, rule.threshold - pattern.current_value)
    : null

  return (
    <div className={`glass-card overflow-hidden border-l-2 ${
      state === 'firing'  ? 'border-l-red-500'
    : state === 'active'  ? 'border-l-amber-500'
    : state === 'dormant' ? 'border-l-slate-700'
    :                       'border-l-slate-600'
    }`}>
      {/* Header */}
      <div className="px-4 pt-4 pb-3 flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-sm font-bold text-slate-100">{rule.metric_name}</span>
            <span className="font-mono text-brand-purple text-sm">{rule.operator}</span>
            <span className="font-mono text-sm text-slate-100">{rule.threshold}</span>
            <span className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full border ${SEV_CONF[rule.severity]}`}>
              {rule.severity}
            </span>
            {rule.alert_mode && rule.alert_mode !== 'static' && (
              <span className="text-[10px] font-bold uppercase px-2 py-0.5 rounded-full border bg-brand-purple/10 text-brand-purple border-brand-purple/20">
                {rule.alert_mode === 'ml' ? 'ML' : 'ML+static'}
              </span>
            )}
          </div>
          <p className="text-[11px] text-slate-500 mt-1 font-mono">
            cooldown {rule.cooldown_minutes}min
            {rule.alert_mode !== 'static' && ` · score ≥ ${rule.ml_score_threshold?.toFixed(2)}`}
          </p>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <span className={`text-[10px] font-bold uppercase px-2 py-1 rounded-md border ${sc.bg} ${sc.text} ${sc.border}`}>
            {t(`alerts.rule.state.${state}`)}
          </span>
          <button
            onClick={onDelete}
            disabled={deleting}
            className="text-slate-600 hover:text-red-400 transition-colors"
            title="Remove rule"
          >
            {deleting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      {/* Current value meter */}
      {pattern?.current_value != null && (
        <div className="px-4 pb-3 space-y-1">
          <div className="grid items-center gap-x-2" style={{ gridTemplateColumns: '80px 1fr auto' }}>
            <span className="text-[10px] text-slate-500 uppercase tracking-widest">{t('alerts.rule.currentValue')}</span>
            <TrendBar
              value={pattern.current_value}
              threshold={rule.threshold}
              color={state === 'firing' ? '#F87171' : state === 'active' ? '#F59E0B' : '#39FF14'}
              height={4}
            />
            <span className="font-mono text-xs font-bold text-slate-200 text-right" style={{ minWidth: 40 }}>
              {pattern.current_value.toFixed(1)}%
            </span>
          </div>
          {margin != null && (
            <div className="text-[10px] text-slate-500 ml-20">
              {t('alerts.rule.margin')}: <span className="font-mono text-slate-400">{margin.toFixed(1)}pp</span>
            </div>
          )}
        </div>
      )}

      {/* Pattern footer */}
      <div className="px-4 py-2.5 bg-white/[0.02] border-t border-white/5 flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-1.5 text-[11px]">
          <Activity className="w-3 h-3 text-slate-500" />
          <span className="text-slate-400">
            {t('alerts.rule.firedCount', { count: pattern?.fires7d ?? 0 })}
          </span>
          {pattern && pattern.fires7d > 0 && pattern.peak_window !== '—' && (
            <span className="text-slate-500">· {t('alerts.rule.pattern')} {pattern.peak_window}</span>
          )}
        </div>

        <div className="flex items-center gap-1.5 text-[11px] ml-auto">
          <Clock className="w-3 h-3 text-slate-600" />
          <span className="text-slate-500 font-mono">
            {pattern?.last_fire
              ? `${t('alerts.rule.lastFire')}: ${new Date(pattern.last_fire).toLocaleDateString()}`
              : t('alerts.rule.neverFired')
            }
          </span>
        </div>

        {state === 'dormant' && (
          <span className="text-[10px] text-slate-600 italic">{t('alerts.rule.stateHint.dormant')}</span>
        )}
      </div>
    </div>
  )
}

// ── Webhook section ───────────────────────────────────────────────────────────

function WebhookSection({ serverId }: { serverId: string }) {
  const { t } = useTranslation()
  const { data } = useWebhookConfig(serverId)
  const save = useSaveWebhook(serverId)
  const remove = useDeleteWebhook(serverId)
  const [url, setUrl] = useState('')

  useEffect(() => { setUrl(data?.url ?? '') }, [data?.url])

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    if (url) save.mutate(url)
    else remove.mutate()
  }

  const hasWebhook = !!(data?.url)

  return (
    <section>
      <h2 className="text-base font-bold text-slate-200 mb-4 flex items-center gap-2">
        <Webhook className="w-4 h-4 text-brand-purple" />
        {t('alerts.webhook.title')}
        {hasWebhook
          ? <span className="ml-2 text-[10px] font-bold px-2 py-0.5 rounded-full bg-brand-neon/10 text-brand-neon border border-brand-neon/20 uppercase">active</span>
          : <span className="ml-2 text-[10px] font-bold px-2 py-0.5 rounded-full bg-slate-800 text-slate-500 border border-slate-700 uppercase">off</span>
        }
      </h2>
      <div className="glass-card p-5">
        <p className="text-xs text-slate-400 mb-4">{t('alerts.webhook.desc')}</p>
        <form onSubmit={handleSave} className="flex gap-3">
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder={t('alerts.webhook.placeholder')}
            className="flex-1 bg-brand-slate border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-brand-purple/50 transition-all font-mono"
          />
          <button
            type="submit"
            disabled={save.isPending || remove.isPending}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-purple hover:bg-brand-purple/80 text-white text-sm font-bold transition-all disabled:opacity-50 shrink-0"
          >
            {(save.isPending || remove.isPending)
              ? <Loader2 className="w-4 h-4 animate-spin" />
              : url ? <Save className="w-4 h-4" /> : <Minus className="w-4 h-4" />
            }
            {url ? t('common.save') : t('common.delete')}
          </button>
        </form>
        {save.isSuccess && <p className="text-xs text-brand-neon mt-2">Webhook saved.</p>}
        {remove.isSuccess && <p className="text-xs text-slate-400 mt-2">Webhook removed.</p>}
        {hasWebhook && !save.isSuccess && (
          <p className="text-[11px] text-slate-500 mt-2 font-mono truncate">Current: {data.url}</p>
        )}
      </div>
    </section>
  )
}

// ── Alerts hero strip ─────────────────────────────────────────────────────────

function AlertsHero({
  rules,
  patterns,
}: {
  rules: AlertRule[]
  patterns: RulePattern[]
}) {
  const { t } = useTranslation()
  const patMap = Object.fromEntries(patterns.map((p) => [p.rule_id, p]))
  const firingCount  = rules.filter((r) => patMap[r.rule_id]?.state === 'firing').length
  const dormantCount = rules.filter((r) => patMap[r.rule_id]?.state === 'dormant').length
  const activeCount  = rules.filter((r) => patMap[r.rule_id]?.state === 'active').length

  return (
    <div className="glass-card p-5 mb-8 flex items-center gap-8 flex-wrap">
      <div className="flex items-center gap-3">
        {firingCount > 0
          ? <Bell className="w-5 h-5 text-red-400 animate-pulse" />
          : <BellOff className="w-5 h-5 text-slate-500" />
        }
        <div>
          <p className="text-[10px] text-slate-500 uppercase tracking-widest">{t('alerts.title')}</p>
          {firingCount > 0
            ? <p className="text-base font-bold text-red-400">{t('alerts.firingNow', { count: firingCount })}</p>
            : <p className="text-base font-bold text-slate-300">{t('alerts.quiet')}</p>
          }
        </div>
      </div>

      <div className="h-8 w-px bg-white/10" />

      <div className="grid grid-cols-3 gap-6">
        <div className="text-center">
          <p className="font-mono text-xl font-bold text-slate-100">{rules.length}</p>
          <p className="text-[10px] text-slate-500 uppercase tracking-widest">{t('alerts.activeRules', { count: rules.length })}</p>
        </div>
        <div className="text-center">
          <p className={`font-mono text-xl font-bold ${activeCount > 0 ? 'text-amber-400' : 'text-slate-600'}`}>{activeCount}</p>
          <p className="text-[10px] text-slate-500 uppercase tracking-widest">{t('health.state.attention')}</p>
        </div>
        <div className="text-center">
          <p className={`font-mono text-xl font-bold ${dormantCount > 0 ? 'text-slate-500' : 'text-slate-600'}`}>{dormantCount}</p>
          <p className="text-[10px] text-slate-500 uppercase tracking-widest">{t('alerts.dormant', { count: dormantCount })}</p>
        </div>
      </div>
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function Alerts({ setView }: AlertsProps) {
  const { t } = useTranslation()
  const selectedAgentId = useUIStore((s) => s.selectedAgentId)
  const { data: servers } = useServers()
  const serverId = selectedAgentId
    ?? servers?.find((s) => s.status === 'online')?.server_id
    ?? servers?.[0]?.server_id
    ?? ''

  const [showForm, setShowForm] = useState(false)

  const { data: eventsData, isLoading: loadingEvents } = useAlertEvents(serverId)
  const { data: rulesData, isLoading: loadingRules }   = useAlertRules(serverId)
  const { data: patternsData }                         = useRulePatterns(serverId)
  const deleteRule = useDeleteAlertRule(serverId)

  const rules    = rulesData?.rules    ?? []
  const patterns = patternsData?.patterns ?? []
  const patMap   = Object.fromEntries(patterns.map((p) => [p.rule_id, p]))

  const fmtTs = (iso: string) =>
    new Date(iso).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })

  return (
    <Layout currentView="alerts" setView={setView} title={t('alerts.title')}>
      {showForm && serverId && <RuleForm serverId={serverId} onClose={() => setShowForm(false)} />}

      <div className="mb-8">
        <h1 className="text-2xl font-bold text-slate-100 mb-1.5">{t('alerts.title')}</h1>
      </div>

      {rules.length > 0 && (
        <AlertsHero rules={rules} patterns={patterns} />
      )}

      <div className="space-y-8">
        {/* Active rules */}
        <section>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-bold text-slate-400 uppercase tracking-widest">
              {t('alerts.activeRules', { count: rules.length })}
            </h2>
            {!!serverId && (
              <button
                onClick={() => setShowForm(true)}
                className="flex items-center gap-2 text-xs font-bold text-brand-purple bg-brand-purple/10 border border-brand-purple/20 px-3 py-1.5 rounded-lg hover:bg-brand-purple/20 transition-all"
              >
                <Plus className="w-3.5 h-3.5" />
                {t('common.newRule')}
              </button>
            )}
          </div>

          {loadingRules ? (
            <div className="flex items-center gap-2 text-slate-500 text-sm">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>{t('common.loading')}</span>
            </div>
          ) : rules.length === 0 ? (
            <p className="text-slate-500 text-sm">{t('alerts.quiet')}</p>
          ) : (
            <div className="space-y-3">
              {rules.map((rule) => (
                <LivingRuleCard
                  key={rule.rule_id}
                  rule={rule}
                  pattern={patMap[rule.rule_id] ?? null}
                  onDelete={() => deleteRule.mutate(rule.rule_id)}
                  deleting={deleteRule.isPending}
                />
              ))}
            </div>
          )}
        </section>

        {/* Webhook */}
        {serverId && <WebhookSection serverId={serverId} />}

        {/* Events history */}
        <section>
          <h2 className="text-sm font-bold text-slate-400 uppercase tracking-widest mb-4">
            {t('common.events')} — 24h
          </h2>

          {loadingEvents ? (
            <div className="flex items-center gap-2 text-slate-500 text-sm">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>{t('common.loading')}</span>
            </div>
          ) : !eventsData?.events.length ? (
            <div className="glass-card p-6 text-center">
              <CheckCircle className="w-8 h-8 text-brand-neon/30 mx-auto mb-2" />
              <p className="text-slate-500 text-sm">{t('dashboard.incidents.quiet')}</p>
            </div>
          ) : (
            <div className="glass-card overflow-hidden">
              <table className="w-full text-left">
                <thead className="text-[10px] text-slate-500 uppercase tracking-widest bg-brand-dark/20">
                  <tr>
                    <th className="px-4 py-2 font-medium">State</th>
                    <th className="px-4 py-2 font-medium">Metric</th>
                    <th className="px-4 py-2 font-medium">Value</th>
                    <th className="px-4 py-2 font-medium">Threshold</th>
                    <th className="px-4 py-2 font-medium">Time</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {eventsData.events.map((event) => (
                    <tr key={event.event_id} className="hover:bg-white/5 transition-colors">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          {event.state === 'FIRING'
                            ? <AlertTriangle className={`w-3.5 h-3.5 ${event.severity === 'critical' ? 'text-red-400' : 'text-orange-400'}`} />
                            : <CheckCircle className="w-3.5 h-3.5 text-brand-neon" />
                          }
                          <span className={`text-[10px] font-bold uppercase ${
                            event.state === 'FIRING'
                              ? event.severity === 'critical' ? 'text-red-400' : 'text-orange-400'
                              : 'text-brand-neon'
                          }`}>
                            {event.state}
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-300">{event.metric_name}</td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-200">{event.value.toFixed(2)}</td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-400">{event.threshold}</td>
                      <td className="px-4 py-3 font-mono text-[11px] text-slate-500 flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {fmtTs(event.triggered_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </Layout>
  )
}
