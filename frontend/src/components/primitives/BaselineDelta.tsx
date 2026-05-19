import React from 'react'

interface BaselineDeltaProps {
  value: number | null
  baseline: number | null
  unit?: string
  invertColors?: boolean
}

const BaselineDelta: React.FC<BaselineDeltaProps> = ({
  value,
  baseline,
  unit = '',
  invertColors = false,
}) => {
  if (baseline == null || value == null) return null

  const delta = value - baseline
  const sign = delta > 0 ? '+' : ''
  const isBad = invertColors ? delta < 0 : delta > 0
  const isNeutral = Math.abs(delta) < baseline * 0.05

  const color = isNeutral
    ? 'var(--color-fg-3, #64748B)'
    : isBad
    ? '#F87171'
    : '#34D399'

  return (
    <span style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 12, color }}>
      {sign}{delta.toFixed(unit === 'pp' ? 0 : 1)}{unit}
    </span>
  )
}

export default BaselineDelta
