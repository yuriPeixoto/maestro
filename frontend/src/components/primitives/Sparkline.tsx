import React from 'react'

interface SparklineProps {
  data: number[]
  color?: string
  width?: number
  height?: number
  area?: boolean
  strokeWidth?: number
  baseline?: number
}

const Sparkline: React.FC<SparklineProps> = ({
  data,
  color = '#39FF14',
  width = 80,
  height = 24,
  area = true,
  strokeWidth = 1.5,
  baseline,
}) => {
  if (!data || data.length < 2) return <svg width={width} height={height} />

  const min = Math.min(...data, baseline ?? Infinity)
  const max = Math.max(...data, baseline ?? -Infinity)
  const range = max - min || 1

  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width
    const y = height - 2 - ((v - min) / range) * (height - 4)
    return [x, y] as [number, number]
  })

  const linePath = pts.map((p, i) => (i === 0 ? `M ${p[0]} ${p[1]}` : `L ${p[0]} ${p[1]}`)).join(' ')
  const areaPath = `${linePath} L ${width} ${height} L 0 ${height} Z`
  const gid = `spark-${color.replace('#', '')}-${Math.round(Math.random() * 999999)}`
  const baseY = baseline != null ? height - 2 - ((baseline - min) / range) * (height - 4) : null

  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      {area && (
        <>
          <defs>
            <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.35" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={areaPath} fill={`url(#${gid})`} />
        </>
      )}
      {baseY != null && (
        <line
          x1="0" x2={width} y1={baseY} y2={baseY}
          stroke="rgba(255,255,255,0.12)" strokeWidth="1" strokeDasharray="2 2"
        />
      )}
      <path
        d={linePath} fill="none"
        stroke={color} strokeWidth={strokeWidth}
        strokeLinecap="round" strokeLinejoin="round"
      />
    </svg>
  )
}

export default Sparkline
