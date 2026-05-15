import React from 'react'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import type { DataPoint } from '../services/api'

interface MetricCardProps {
  label: string
  unit: string
  data: DataPoint[]
  thresholds?: { amber: number; red: number }
}

function getTrend(data: DataPoint[]): 'up' | 'down' | 'stable' {
  if (data.length < 2) return 'stable'
  const half = Math.floor(data.length / 2)
  const prev = data.slice(0, half).reduce((s, d) => s + d.value, 0) / half
  const curr = data.slice(half).reduce((s, d) => s + d.value, 0) / (data.length - half)
  const diff = curr - prev
  if (Math.abs(diff) < prev * 0.02) return 'stable'
  return diff > 0 ? 'up' : 'down'
}

function getSeverity(value: number, thresholds?: { amber: number; red: number }) {
  if (!thresholds) return 'green'
  if (value >= thresholds.red) return 'red'
  if (value >= thresholds.amber) return 'amber'
  return 'green'
}

const severityStyles = {
  green: 'border-l-emerald-500 text-emerald-400',
  amber: 'border-l-amber-400 text-amber-400',
  red: 'border-l-red-500 text-red-400',
}

const MetricCard: React.FC<MetricCardProps> = ({ label, unit, data, thresholds }) => {
  const current = data.at(-1)?.value ?? null
  const trend = getTrend(data)
  const severity = current !== null ? getSeverity(current, thresholds) : 'green'

  const TrendIcon = trend === 'up' ? TrendingUp : trend === 'down' ? TrendingDown : Minus
  const trendColor = trend === 'up' ? 'text-red-400' : trend === 'down' ? 'text-emerald-400' : 'text-slate-400'

  return (
    <div className={`glass-card p-5 border-l-4 ${severityStyles[severity]}`}>
      <div className="flex justify-between items-start mb-3">
        <span className="text-slate-400 text-xs font-semibold uppercase tracking-wider">{label}</span>
        <TrendIcon className={`w-4 h-4 ${trendColor}`} />
      </div>
      <div className="flex items-baseline gap-1">
        {current !== null ? (
          <>
            <span className="text-2xl font-bold font-mono">
              {current.toFixed(1)}
            </span>
            <span className="text-xs text-slate-400">{unit}</span>
          </>
        ) : (
          <span className="text-sm text-slate-500">—</span>
        )}
      </div>
    </div>
  )
}

export default MetricCard
