import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'
import Dialog from '../users/Dialog'
import Segmented from './Segmented'
import { useCreateRule, useUpdateRule } from '../../hooks/useAlerting'
import type { Scope, ScopedRule, ServerGroup } from '../../services/alertingApi'
import type { ServerStatus } from '../../types/server'
import { serverName } from '../../hooks/useServerName'
import { HEARTBEAT_AGE_METRIC, metricLabel } from '../../utils/format'
import {
  OPERATOR_SYMBOL, alertingError, buttonGhost, buttonPrimary, fieldClass, hintClass, labelClass, limitText, placeLabel,
  ruleName,
} from './ui'

const METRICS = ['disk_usage_percent', 'memory_usage_percent', 'cpu_usage_percent', 'load_1m', HEARTBEAT_AGE_METRIC]
const OPERATORS = ['>=', '>', '<=', '<', '==']
const DEFAULT_COOLDOWN_MINUTES = 15
const MAX_COOLDOWN_MINUTES = 1440

interface Values {
  metric_name: string
  severity: 'warning' | 'critical'
  operator: string
  threshold: string
  cooldown_minutes: string
  alert_mode: string
  ml_score_threshold: number
}

function valuesOf(rule?: ScopedRule): Values {
  return {
    metric_name: rule?.metric_name ?? METRICS[0],
    severity: rule?.severity ?? 'critical',
    operator: rule?.operator ?? '>=',
    threshold: rule ? String(rule.threshold) : '',
    cooldown_minutes: String(rule?.cooldown_minutes ?? DEFAULT_COOLDOWN_MINUTES),
    alert_mode: rule?.alert_mode ?? 'static',
    ml_score_threshold: rule?.ml_score_threshold ?? 0.7,
  }
}

/** Limit, repeat interval and detection: what every rule form asks. */
function LimitFields({ values, set, idPrefix }: {
  values: Values
  set: (changes: Partial<Values>) => void
  idPrefix: string
}) {
  const { t } = useTranslation()
  const usesMl = values.alert_mode !== 'static'
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor={`${idPrefix}-threshold`}>{t('alerts.screen.rule.limit')}</label>
          <div className="flex gap-2">
            <select
              aria-label={t('alerts.form.operator')}
              className={`${fieldClass} w-20 font-mono`}
              value={values.operator}
              onChange={(e) => set({ operator: e.target.value })}
            >
              {OPERATORS.map((op) => <option key={op} value={op}>{OPERATOR_SYMBOL[op]}</option>)}
            </select>
            <input
              id={`${idPrefix}-threshold`}
              type="number"
              step="any"
              required
              className={`${fieldClass} font-mono`}
              value={values.threshold}
              onChange={(e) => set({ threshold: e.target.value })}
            />
          </div>
        </div>
        <div>
          <label className={labelClass} htmlFor={`${idPrefix}-cooldown`}>{t('alerts.screen.rule.repeatAfter')}</label>
          <input
            id={`${idPrefix}-cooldown`}
            type="number"
            min={1}
            max={MAX_COOLDOWN_MINUTES}
            required
            className={`${fieldClass} font-mono`}
            value={values.cooldown_minutes}
            onChange={(e) => set({ cooldown_minutes: e.target.value })}
          />
        </div>
      </div>
      <div className="mt-3">
        <label className={labelClass} htmlFor={`${idPrefix}-mode`}>{t('alerts.detection.label')}</label>
        <select id={`${idPrefix}-mode`} className={fieldClass} value={values.alert_mode} onChange={(e) => set({ alert_mode: e.target.value })}>
          <option value="static">{t('alerts.detection.static')}</option>
          <option value="ml">{t('alerts.detection.ml')}</option>
          <option value="both">{t('alerts.detection.both')}</option>
        </select>
        {usesMl && (
          <div className="mt-2 flex items-center gap-3">
            <label className="text-xs text-slate-400" htmlFor={`${idPrefix}-score`}>{t('alerts.detection.scoreThreshold')}</label>
            <input
              id={`${idPrefix}-score`}
              type="range" min={0} max={1} step={0.05}
              className="flex-1 accent-brand-purple"
              value={values.ml_score_threshold}
              onChange={(e) => set({ ml_score_threshold: Number(e.target.value) })}
            />
            <span className="font-mono text-sm w-10 text-right">{values.ml_score_threshold.toFixed(2)}</span>
          </div>
        )}
        {usesMl && <p className={hintClass}>{t('alerts.screen.rule.mlHint')}</p>}
      </div>
    </>
  )
}

const changesOf = (values: Values) => ({
  operator: values.operator,
  threshold: Number(values.threshold),
  cooldown_minutes: Number(values.cooldown_minutes),
  alert_mode: values.alert_mode,
  ml_score_threshold: values.ml_score_threshold,
})

/** A new rule at any place, or the values of an existing one (its place, metric and severity stay). */
export function RuleDialog({ rule, initialScope, initialServer, initialGroup, servers, groups, onClose }: {
  rule?: ScopedRule
  initialScope: Scope
  initialServer?: string
  initialGroup?: number | null
  servers: ServerStatus[]
  groups: ServerGroup[]
  onClose: () => void
}) {
  const { t } = useTranslation()
  const create = useCreateRule()
  const update = useUpdateRule()
  const saving = create.isPending || update.isPending
  const [values, setValues] = useState(valuesOf(rule))
  const [scope, setScope] = useState<Scope>(rule?.scope ?? initialScope)
  const [serverId, setServerId] = useState(rule?.server_id ?? initialServer ?? servers[0]?.server_id ?? '')
  const [groupId, setGroupId] = useState<number | null>(rule?.group_id ?? initialGroup ?? groups[0]?.group_id ?? null)
  const [customMetric, setCustomMetric] = useState(!!rule && !METRICS.includes(rule.metric_name))
  const set = (changes: Partial<Values>) => setValues((v) => ({ ...v, ...changes }))
  const error = create.error ?? update.error

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    if (rule) {
      update.mutate({ ruleId: rule.rule_id, changes: changesOf(values) }, { onSuccess: onClose })
      return
    }
    create.mutate({
      scope, server_id: scope === 'server' ? serverId : null, group_id: scope === 'group' ? groupId : null,
      metric_name: values.metric_name, severity: values.severity, ...changesOf(values),
    }, { onSuccess: onClose })
  }

  const scopeOptions = [
    { value: 'global' as const, label: t('alerts.screen.place.global') },
    ...(groups.length ? [{ value: 'group' as const, label: t('alerts.screen.place.aGroup') }] : []),
    { value: 'server' as const, label: t('alerts.screen.place.aServer') },
  ]

  return (
    <Dialog
      title={rule ? t('alerts.screen.rule.editTitle') : t('alerts.screen.rule.newTitle')}
      subtitle={rule ? `${ruleName(rule, t)} · ${placeLabel(rule, t, groups, (id) => id)}` : undefined}
      onClose={onClose}
      dismissible={!saving}
      footer={(
        <>
          <button type="button" className={buttonGhost} onClick={onClose} disabled={saving}>{t('common.cancel')}</button>
          <button type="submit" form="rule-form" className={buttonPrimary} disabled={saving}>
            {saving && <Loader2 className="w-4 h-4 animate-spin" aria-hidden />}{t('common.save')}
          </button>
        </>
      )}
    >
      <form id="rule-form" onSubmit={submit}>
        {!rule && (
          <>
            <span className={labelClass}>{t('alerts.screen.rule.appliesTo')}</span>
            <Segmented label={t('alerts.screen.rule.appliesTo')} options={scopeOptions} value={scope} onChange={setScope} />
            {scope === 'server' && (
              <select aria-label={t('alerts.screen.col.server')} className={`${fieldClass} mt-2`} value={serverId} onChange={(e) => setServerId(e.target.value)}>
                {servers.map((s) => <option key={s.server_id} value={s.server_id}>{serverName(s).display} ({s.server_id})</option>)}
              </select>
            )}
            {scope === 'group' && (
              <select aria-label={t('alerts.screen.servers.group')} className={`${fieldClass} mt-2`} value={groupId ?? ''} onChange={(e) => setGroupId(Number(e.target.value))}>
                {groups.map((g) => <option key={g.group_id} value={g.group_id}>{g.name}</option>)}
              </select>
            )}
            <div className="grid gap-3 sm:grid-cols-2 mt-4 mb-3">
              <div>
                <label className={labelClass} htmlFor="rule-metric">{t('alerts.form.metric')}</label>
                {customMetric ? (
                  <input id="rule-metric" required className={`${fieldClass} font-mono`} placeholder="cpu_usage_percent"
                    value={values.metric_name} onChange={(e) => set({ metric_name: e.target.value })} />
                ) : (
                  <select id="rule-metric" className={fieldClass} value={values.metric_name}
                    onChange={(e) => {
                      if (e.target.value === '__custom__') { setCustomMetric(true); set({ metric_name: '' }) } else set({ metric_name: e.target.value })
                    }}>
                    {METRICS.map((m) => <option key={m} value={m}>{metricLabel(m, t)}</option>)}
                    <option value="__custom__">{t('alerts.form.customMetric')}</option>
                  </select>
                )}
              </div>
              <div>
                <label className={labelClass} htmlFor="rule-severity">{t('alerts.form.severity')}</label>
                <select id="rule-severity" className={fieldClass} value={values.severity}
                  onChange={(e) => set({ severity: e.target.value as Values['severity'] })}>
                  <option value="critical">{t('alerts.severity.critical')}</option>
                  <option value="warning">{t('alerts.severity.warning')}</option>
                </select>
              </div>
            </div>
          </>
        )}
        <LimitFields values={values} set={set} idPrefix="rule" />
        <p className={hintClass}>{t('alerts.screen.rule.identityHint')}</p>
        {error && <p role="alert" className="mt-2 text-xs text-red-300">{alertingError(error, t)}</p>}
      </form>
    </Dialog>
  )
}

/** On one server: another limit for an inherited rule, or switching it off there. */
export function OverrideDialog({ inherited, serverId, serverLabel, groups, onClose }: {
  inherited: ScopedRule
  serverId: string
  serverLabel: string
  groups: ServerGroup[]
  onClose: () => void
}) {
  const { t } = useTranslation()
  const create = useCreateRule()
  const [mode, setMode] = useState<'limit' | 'off'>('limit')
  const [values, setValues] = useState(valuesOf(inherited))
  const set = (changes: Partial<Values>) => setValues((v) => ({ ...v, ...changes }))

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    create.mutate({
      scope: 'server', server_id: serverId, group_id: null,
      metric_name: inherited.metric_name, severity: inherited.severity,
      ...changesOf(values), enabled: mode === 'limit',
    }, { onSuccess: onClose })
  }

  return (
    <Dialog
      title={t('alerts.screen.override.title', { server: serverLabel })}
      onClose={onClose}
      dismissible={!create.isPending}
      footer={(
        <>
          <button type="button" className={buttonGhost} onClick={onClose} disabled={create.isPending}>{t('common.cancel')}</button>
          <button type="submit" form="override-form" className={buttonPrimary} disabled={create.isPending}>
            {create.isPending && <Loader2 className="w-4 h-4 animate-spin" aria-hidden />}{t('common.save')}
          </button>
        </>
      )}
    >
      <form id="override-form" onSubmit={submit}>
        <p className="text-xs text-slate-400 leading-relaxed mb-3">
          {t('alerts.screen.override.desc', {
            rule: ruleName(inherited, t), place: placeLabel(inherited, t, groups), limit: limitText(inherited),
          })}
        </p>
        <Segmented
          label={t('alerts.screen.override.what')}
          options={[
            { value: 'limit', label: t('alerts.screen.override.otherLimit') },
            { value: 'off', label: t('alerts.screen.override.switchOff') },
          ]}
          value={mode}
          onChange={setMode}
        />
        <div className="mt-4">
          {mode === 'limit'
            ? <LimitFields values={values} set={set} idPrefix="override" />
            : <p className={hintClass}>{t('alerts.screen.override.offHint')}</p>}
        </div>
        {create.isError && <p role="alert" className="mt-2 text-xs text-red-300">{alertingError(create.error, t)}</p>}
      </form>
    </Dialog>
  )
}
