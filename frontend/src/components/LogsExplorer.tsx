import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Download, Filter, RefreshCw, Terminal, Wifi, WifiOff } from 'lucide-react'
import Layout from './Layout'
import type { ViewType } from '../App'
import { useServers } from '../hooks/useServers'
import { useLogFiles, useLogHistory, useLogStream, type StreamStatus } from '../hooks/useLogs'

interface LogsExplorerProps {
  setView: (view: ViewType) => void
}

const HISTORY_LINES = 200
const MAX_LINES = 2000

function lineColor(line: string): string {
  const u = line.toUpperCase()
  if (/\b(CRIT|CRITICAL|FATAL|EMERG|ALERT)\b/.test(u)) return 'text-red-400'
  if (/\b(ERROR|ERR)\b/.test(u)) return 'text-red-300'
  if (/\bWARN(ING)?\b/.test(u)) return 'text-orange-400'
  if (/\bINFO\b/.test(u)) return 'text-blue-400'
  if (/\bDEBUG\b/.test(u)) return 'text-slate-500'
  return 'text-slate-300'
}

function StatusDot({ status }: { status: StreamStatus }) {
  if (status === 'connected') return <Wifi className="w-3 h-3 text-brand-neon" />
  if (status === 'reconnecting') return <RefreshCw className="w-3 h-3 text-orange-400 animate-spin" />
  return <WifiOff className="w-3 h-3 text-slate-500" />
}

// Keyed by file in the parent, so a new file starts with a clean stream buffer.
function LogViewer({ serverId, logFile }: { serverId: string; logFile: string }) {
  const { t } = useTranslation()
  const [filter, setFilter] = useState('')
  const { data: historyData, isLoading } = useLogHistory(serverId, logFile, HISTORY_LINES)
  const { lines: streamLines, status } = useLogStream(serverId, logFile, true)

  const newestFirst = useMemo(() => {
    const all = [...(historyData?.lines ?? []), ...streamLines].slice(-MAX_LINES).reverse()
    const needle = filter.toLowerCase()
    return needle ? all.filter((l) => l.line.toLowerCase().includes(needle)) : all
  }, [historyData, streamLines, filter])

  const exportLogs = () => {
    const content = newestFirst.map((l) => `[${l.timestamp}] ${l.line}`).join('\n')
    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${serverId}-${logFile.replaceAll('/', '-')}`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <>
      {/* Toolbar */}
      <div className="p-3 border-b border-white/5 flex items-center gap-3 shrink-0">
        <div className="relative flex-1">
          <Filter className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            placeholder={t('logs.filterPlaceholder')}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="w-full bg-brand-dark border border-white/10 rounded pl-8 pr-3 py-1.5 text-xs font-mono focus:outline-none focus:border-brand-purple/50"
          />
        </div>
        <span className="text-[11px] text-slate-500 shrink-0">{t('logs.newestFirst')}</span>
        <button
          onClick={exportLogs}
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors"
        >
          <Download className="w-3.5 h-3.5" />
          {t('logs.export')}
        </button>
      </div>

      {/* Log output, newest line on top */}
      <div className="flex-1 overflow-y-auto bg-black/30 font-mono text-xs">
        {newestFirst.length === 0 ? (
          <div className="h-full flex items-center justify-center text-slate-600">
            {isLoading ? t('common.loading') : t('logs.emptyFile')}
          </div>
        ) : (
          newestFirst.map((l, i) => (
            <div
              key={`${l.timestamp}-${i}`}
              className="flex gap-3 px-3 py-0.5 hover:bg-white/3 transition-colors"
            >
              <span className="text-slate-600 shrink-0 pt-0.5">
                {new Date(l.timestamp).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'medium' })}
              </span>
              <span className={`break-all ${lineColor(l.line)}`}>{l.line}</span>
            </div>
          ))
        )}
      </div>

      {/* Status bar */}
      <div className="px-3 py-1.5 border-t border-white/5 flex items-center gap-3 shrink-0">
        <StatusDot status={status} />
        <span className="text-xs font-mono text-slate-400 truncate">
          {t('logs.watching', { file: logFile, server: serverId })}
        </span>
      </div>
    </>
  )
}

export default function LogsExplorer({ setView }: LogsExplorerProps) {
  const { t } = useTranslation()
  const [chosenServer, setSelectedServer] = useState('')
  const [selectedFile, setSelectedFile] = useState('')

  const { data: servers } = useServers()
  const selectedServer = chosenServer || servers?.[0]?.server_id || ''
  const { data: logFilesData } = useLogFiles(selectedServer)

  const changeServer = (serverId: string) => {
    setSelectedServer(serverId)
    setSelectedFile('')
  }

  const availableFiles = logFilesData?.log_files ?? []

  return (
    <Layout currentView="logs" setView={setView} title={t('logs.title')}>
      <div className="flex gap-4 h-[calc(100vh-10rem)]">

        {/* Sidebar: server + file selector */}
        <div className="w-56 shrink-0 flex flex-col gap-3">
          <div className="glass-card p-3">
            <p className="text-xs text-slate-500 uppercase tracking-widest mb-2">{t('logs.server')}</p>
            <select
              value={selectedServer}
              onChange={(e) => changeServer(e.target.value)}
              className="w-full bg-brand-dark border border-white/10 rounded px-2 py-1.5 text-sm focus:outline-none focus:border-brand-purple/50"
            >
              {(servers ?? []).map((s) => (
                <option key={s.server_id} value={s.server_id}>
                  {s.server_id}
                </option>
              ))}
            </select>
          </div>

          <div className="glass-card p-3 flex-1 overflow-y-auto">
            <p className="text-xs text-slate-500 uppercase tracking-widest mb-2">{t('logs.files')}</p>
            {availableFiles.length === 0 && (
              <p className="text-xs text-slate-600 italic">
                {selectedServer ? t('logs.noLogsAvailable') : t('logs.selectServer')}
              </p>
            )}
            <div className="space-y-1">
              {availableFiles.map((file) => (
                <button
                  key={file}
                  onClick={() => setSelectedFile(file)}
                  title={file}
                  className={`w-full text-left px-2 py-1 rounded text-xs font-mono truncate transition-colors ${
                    selectedFile === file
                      ? 'bg-brand-purple/20 text-white'
                      : 'text-slate-400 hover:text-white hover:bg-white/5'
                  }`}
                >
                  {file}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Terminal panel */}
        <div className="flex-1 glass-card flex flex-col min-w-0">
          {selectedFile ? (
            <LogViewer key={`${selectedServer}/${selectedFile}`} serverId={selectedServer} logFile={selectedFile} />
          ) : (
            <div className="flex-1 flex items-center justify-center bg-black/30 text-slate-600 text-xs font-mono">
              <div className="text-center">
                <Terminal className="w-8 h-8 mx-auto mb-2 opacity-30" />
                <p>{t('logs.selectFiles')}</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </Layout>
  )
}
