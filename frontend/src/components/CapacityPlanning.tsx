import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown } from 'lucide-react'
import Layout from './Layout'
import CapacityProgress from './CapacityProgress'
import CapacityCard from './capacity/CapacityCard'
import ForecastChart from './capacity/ForecastChart'
import PeaksChart from './capacity/PeaksChart'
import {
  diskDetail, diskHeadline, diskSentence, peakDetail, peakHeadline, peakSentence,
} from './capacity/capacityText'
import type { ViewType } from '../App'
import { useServers } from '../hooks/useServers'
import { usePeaks, useRunway } from '../hooks/useForecasts'
import { useUIStore } from '../store/uiStore'
import { metricLabel } from '../utils/format'
import { serverName } from '../hooks/useServerName'
import { ServerName } from './primitives'

interface CapacityPlanningProps {
  setView: (view: ViewType) => void
}

const DISK = 'disk_usage_percent'
const CPU = 'cpu_usage_percent'
const MEMORY = 'memory_usage_percent'
const TABS = [DISK, CPU, MEMORY] as const
type Tab = typeof TABS[number]

const PEAK_DAYS = 30
const MAIN_CHART_HEIGHT = 300
const SMALL_CHART_HEIGHT = 220

export default function CapacityPlanning({ setView }: CapacityPlanningProps) {
  const { t } = useTranslation()
  const { data: servers } = useServers()
  const selectedAgentId = useUIStore((s) => s.selectedAgentId)
  const [chosenServerId, setServerId] = useState('')
  const serverId = chosenServerId
    || selectedAgentId
    || (servers?.find((s) => s.status === 'online')?.server_id ?? servers?.[0]?.server_id ?? '')
  const [activeTab, setActiveTab] = useState<Tab>(DISK)
  const [serverOpen, setServerOpen] = useState(false)

  const { data: runway, isLoading: runwayLoading } = useRunway(serverId)
  const { data: peaks, isLoading: peaksLoading } = usePeaks(serverId, PEAK_DAYS)

  const selectedServer = servers?.find((s) => s.server_id === serverId)
  const disk = runway?.metrics.find((m) => m.metric_name === DISK)
  const peakOf = (metric: string) => peaks?.metrics.find((m) => m.metric_name === metric)
  const cpu = peakOf(CPU)
  const memory = peakOf(MEMORY)
  const activePeak = activeTab === DISK ? undefined : peakOf(activeTab)

  const sentence = activeTab === DISK
    ? (disk && runway ? diskSentence(disk, runway.threshold_pct, t) : '')
    : (activePeak ? peakSentence(activePeak, PEAK_DAYS, t) : '')

  const loadingCard = (key: string) => (
    <div key={key} className="h-28 rounded-xl border border-white/10 bg-white/[0.03] animate-pulse" />
  )

  return (
    <Layout currentView="capacity" setView={setView} title={t('capacity.title')}>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t('capacity.title')}</h1>
          <p className="text-sm text-slate-500 mt-1">{t('capacity.subtitle')}</p>
        </div>

        <div className="relative w-72 max-w-full">
          <button
            onClick={() => setServerOpen((o) => !o)}
            className="w-full flex items-center justify-between px-4 py-2.5 rounded-xl border border-white/10 bg-brand-slate text-sm text-slate-200 hover:border-brand-purple/40 transition-all"
          >
            <span>{selectedServer ? serverName(selectedServer).display : t('capacity.selectServer')}</span>
            <ChevronDown className="w-4 h-4 text-slate-500" />
          </button>
          {serverOpen && servers && (
            <div className="absolute z-20 mt-1 w-full rounded-xl border border-white/10 bg-brand-dark shadow-xl overflow-hidden">
              {servers.map((s) => (
                <button
                  key={s.server_id}
                  onClick={() => { setServerId(s.server_id); setServerOpen(false) }}
                  className="w-full text-left px-4 py-2.5 text-sm text-slate-300 hover:bg-white/5 hover:text-white transition-colors"
                >
                  <ServerName name={serverName(s)} nameClass="text-sm text-slate-200" />
                </button>
              ))}
            </div>
          )}
        </div>

        {serverId && (
          <>
            {runway && <CapacityProgress collection={runway.collection} />}

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {runwayLoading || !disk || !runway
                ? loadingCard('disk')
                : (
                  <CapacityCard
                    label={metricLabel(DISK, t)}
                    status={disk.status}
                    headline={diskHeadline(disk, runway.threshold_pct, t)}
                    detail={disk.status === 'no_data'
                      ? t('capacity.sentence.noForecast')
                      : `${t('capacity.disk.toThreshold', { threshold: runway.threshold_pct })} ${diskDetail(disk, t)}`}
                  />
                )}
              {[cpu, memory].map((peak, i) => (peaksLoading || !peak
                ? loadingCard(`peak-${i}`)
                : (
                  <CapacityCard
                    key={peak.metric_name}
                    label={metricLabel(peak.metric_name, t)}
                    status={peak.status}
                    headline={peakHeadline(peak, t)}
                    detail={`${peakDetail(peak, PEAK_DAYS, t)} ${t(`capacity.peaks.trend.${peak.trend}`)}`}
                  />
                )))}
            </div>

            <div className="rounded-2xl border border-white/10 bg-brand-slate p-6 space-y-4">
              <div className="flex flex-wrap gap-1 border-b border-white/5 pb-3">
                {TABS.map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    className={`px-4 py-1.5 rounded-lg text-xs font-mono font-semibold transition-all ${
                      activeTab === tab
                        ? 'bg-brand-purple/20 text-brand-purple border border-brand-purple/30'
                        : 'text-slate-500 hover:text-slate-300 hover:bg-white/5'
                    }`}
                  >
                    {metricLabel(tab, t)}
                  </button>
                ))}
              </div>

              {sentence && <p className="text-sm text-slate-200">{sentence}</p>}

              {activeTab === DISK
                ? <ForecastChart serverId={serverId} metric={DISK} collection={runway?.collection} />
                : activePeak && <PeaksChart peak={activePeak} height={MAIN_CHART_HEIGHT} />}

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 pt-2">
                {[cpu, memory].map((peak) => peak && (
                  <div key={peak.metric_name} className="space-y-2 min-w-0">
                    <h3 className="text-xs font-bold text-slate-300">
                      {t('capacity.peaks.chartTitle', { metric: metricLabel(peak.metric_name, t), minutes: peaks?.window_minutes ?? 5 })}
                    </h3>
                    <PeaksChart peak={peak} height={SMALL_CHART_HEIGHT} />
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </Layout>
  )
}
