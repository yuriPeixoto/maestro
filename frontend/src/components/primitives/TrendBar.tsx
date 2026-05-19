import React from 'react'

interface TrendBarProps {
  value: number
  max?: number
  threshold?: number
  baseline?: number
  color?: string
  height?: number
  width?: string | number
}

const TrendBar: React.FC<TrendBarProps> = ({
  value,
  max = 100,
  threshold,
  baseline,
  color = '#39FF14',
  height = 6,
  width = '100%',
}) => {
  const pct    = Math.min(100, (value / max) * 100)
  const thrPct = threshold != null ? (threshold / max) * 100 : null
  const basePct = baseline != null ? (baseline / max) * 100 : null

  return (
    <div style={{
      position: 'relative', width, height,
      background: 'rgba(255,255,255,0.06)',
      borderRadius: 3, overflow: 'visible',
    }}>
      <div style={{
        position: 'absolute', inset: 0, width: `${pct}%`,
        background: color, borderRadius: 3,
        transition: 'width 0.3s ease',
      }} />
      {basePct != null && (
        <div
          title={`avg ${baseline}`}
          style={{
            position: 'absolute', left: `${basePct}%`,
            top: -2, bottom: -2, width: 1,
            background: 'rgba(255,255,255,0.40)',
          }}
        />
      )}
      {thrPct != null && (
        <div
          title={`threshold ${threshold}`}
          style={{
            position: 'absolute', left: `${thrPct}%`,
            top: -3, bottom: -3, width: 2,
            background: '#F87171',
          }}
        />
      )}
    </div>
  )
}

export default TrendBar
