import React from 'react'
import { useTranslation } from 'react-i18next'

export type HealthState = 'ok' | 'attention' | 'critical' | 'quiet'

interface HealthScoreProps {
  state: HealthState
  size?: 'sm' | 'md' | 'lg'
}

const STATE_CONF: Record<HealthState, { fg: string; bg: string; border: string; labelKey: string }> = {
  ok:        { fg: '#34D399', bg: 'rgba(52,211,153,0.10)',  border: 'rgba(52,211,153,0.30)',  labelKey: 'health.state.ok' },
  attention: { fg: '#F59E0B', bg: 'rgba(245,158,11,0.10)',  border: 'rgba(245,158,11,0.30)',  labelKey: 'health.state.attention' },
  critical:  { fg: '#F87171', bg: 'rgba(239,68,68,0.10)',   border: 'rgba(239,68,68,0.30)',   labelKey: 'health.state.critical' },
  quiet:     { fg: '#94A3B8', bg: 'rgba(148,163,184,0.10)', border: 'rgba(148,163,184,0.30)', labelKey: 'health.state.quiet' },
}

const HealthScore: React.FC<HealthScoreProps> = ({ state, size = 'md' }) => {
  const { t } = useTranslation()
  const conf = STATE_CONF[state] ?? STATE_CONF.quiet

  const padding = size === 'sm' ? '2px 8px' : size === 'lg' ? '6px 14px' : '4px 10px'
  const fontSize = size === 'sm' ? 10 : size === 'lg' ? 13 : 11
  const dotSize = size === 'sm' ? 6 : 8

  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding, borderRadius: 6,
      fontFamily: 'var(--font-mono)',
      fontSize, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em',
      background: conf.bg, color: conf.fg, border: `1px solid ${conf.border}`,
    }}>
      <span style={{
        width: dotSize, height: dotSize,
        borderRadius: '50%', background: conf.fg,
        boxShadow: state === 'ok' ? `0 0 6px ${conf.fg}99` : 'none',
        flexShrink: 0,
      }} />
      {t(conf.labelKey)}
    </span>
  )
}

export default HealthScore
