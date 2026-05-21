import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Download, Filter, RefreshCw, Terminal, Wifi, WifiOff } from 'lucide-react'
import Layout from './Layout'
import type { ViewType } from '../App'
import { useServers } from '../hooks/useServers'
import { useLogFiles, useLogHistory, useLogStream, type StreamStatus } from '../hooks/useLogs'
import type { LogLine } from '../services/api'

interface LogsExplorerProps {
  setView: (view: ViewType) => void
}

interface LogLineWithSource extends LogLine {
  source: string
}

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

// Headless: fetches history + SSE for one file, reports upward via onUpdate.
// Renders nothing — parent owns the merged display.
function LogFileLoader({
  serverId,
  logFile,
  onUpdate,
}: {
  serverId: string
  logFile: string
  onUpdate: (file: string, lines: LogLineWithSource[], status: StreamStatus) => void
}) {
  const { data: historyData } = useLogHistory(serverId, logFile, 200)
  const { lines: streamLines, status } = useLogStream(serverId, logFile, true)

  const allLines = useMemo(
    () =>
      [...(historyData?.lines ?? []), ...streamLines]
        .slice(-2000)
        .map((l) => ({ ...l, source: logFile })),
    [historyData, streamLines, logFile],
  )

  // Ref avoids stale closure without adding onUpdate to dep array
  const onUpdateRef = useRef(onUpdate)
  onUpdateRef.current = onUpdate

  useEffect(() => {
    onUpdateRef.current(logFile, allLines, status)
  }, [logFile, allLines, status])

  return null
}

export default function LogsExplorer({ setView }: LogsExplorerProps) {
  const { t } = useTranslation()
  const [selectedServer, setSelectedServer] = useState('')
  const [selectedFiles, setSelectedFiles] = useState<string[]>([])
  const [filter, setFilter] = useState('')
  const [fileLines, setFileLines] = useState<Record<string, LogLineWithSource[]>>({})
  const [fileStatuses, setFileStatuses] = useState<Record<string, StreamStatus>>({})
  const bottomRef = useRef<HTMLDivElement>(null)
  const hasScrolledRef = useRef(false)

  const { data: servers } = useServers()
  const { data: logFilesData } = useLogFiles(selectedServer)

  useEffect(() => {
    if (servers && servers.length > 0 && !selectedServer) {
      setSelectedServer(servers[0].server_id)
    }
  }, [servers, selectedServer])

  useEffect(() => {
    setSelectedFiles([])
    setFileLines({})
    setFileStatuses({})
    hasScrolledRef.current = false
  }, [selectedServer])

  // Drop stale data for deselected files
  useEffect(() => {
    setFileLines((prev) => {
      const next: Record<string, LogLineWithSource[]> = {}
      for (const f of selectedFiles) if (prev[f]) next[f] = prev[f]
      return next
    })
    setFileStatuses((prev) => {
      const next: Record<string, StreamStatus> = {}
      for (const f of selectedFiles) if (prev[f]) next[f] = prev[f]
      return next
    })
  }, [selectedFiles])

  const handleFileUpdate = useCallback(
    (file: string, lines: LogLineWithSource[], status: StreamStatus) => {
      setFileLines((prev) => ({ ...prev, [file]: lines }))
      setFileStatuses((prev) => ({ ...prev, [file]: status }))
    },
    [],
  )

  const mergedLines = useMemo(() => {
    const all = Object.values(fileLines).flat()
    all.sort((a, b) => a.timestamp.localeCompare(b.timestamp))
    const filtered = filter
      ? all.filter((l) => l.line.toLowerCase().includes(filter.toLowerCase()))
      : all
    return filtered.slice(-4000)
  }, [fileLines, filter])

  // Scroll to bottom once when history first arrives
  useEffect(() => {
    if (mergedLines.length > 0 && !hasScrolledRef.current) {
      hasScrolledRef.current = true
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [mergedLines.length])

  const toggleFile = (file: string) => {
    setSelectedFiles((prev) =>
      prev.includes(file) ? prev.filter((f) => f !== file) : [...prev, file],
    )
  }

  const exportLogs = () => {
    const content = mergedLines
      .map((l) => `[${l.timestamp}] [${l.source}] ${l.line}`)
      .join('\n')
    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${selectedServer}-logs.log`
    a.click()
    URL.revokeObjectURL(url)
  }

  const availableFiles = logFilesData?.log_files ?? []
  const hasSelection = selectedFiles.length > 0

  return (
    <Layout currentView="logs" setView={setView} title={t('logs.title')}>
      {/* Headless loaders — one per selected file, each fetches its own history + SSE */}
      {selectedFiles.map((file) => (
        <LogFileLoader
          key={file}
          serverId={selectedServer}
          logFile={file}
          onUpdate={handleFileUpdate}
        />
      ))}

      <div className="flex gap-4 h-[calc(100vh-10rem)]">

        {/* Sidebar: server + file selector */}
        <div className="w-56 shrink-0 flex flex-col gap-3">
          <div className="glass-card p-3">
            <p className="text-xs text-slate-500 uppercase tracking-widest mb-2">{t('logs.server')}</p>
            <select
              value={selectedServer}
              onChange={(e) => setSelectedServer(e.target.value)}
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
                <label key={file} className="flex items-center gap-2 cursor-pointer group py-0.5">
                  <input
                    type="checkbox"
                    checked={selectedFiles.includes(file)}
                    onChange={() => toggleFile(file)}
                    className="accent-brand-purple"
                  />
                  <span
                    className={`text-xs font-mono truncate group-hover:text-white transition-colors ${
                      selectedFiles.includes(file) ? 'text-white' : 'text-slate-400'
                    }`}
                  >
                    {file}
                  </span>
                  {fileStatuses[file] && (
                    <span className="ml-auto shrink-0">
                      <StatusDot status={fileStatuses[file]} />
                    </span>
                  )}
                </label>
              ))}
            </div>
          </div>
        </div>

        {/* Terminal panel — single merged view */}
        <div className="flex-1 glass-card flex flex-col min-w-0">
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
            <button
              onClick={exportLogs}
              disabled={!hasSelection}
              className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <Download className="w-3.5 h-3.5" />
              {t('logs.export')}
            </button>
          </div>

          {/* Merged, chronological log output */}
          <div className="flex-1 overflow-y-auto bg-black/30 font-mono text-xs">
            {!hasSelection ? (
              <div className="h-full flex items-center justify-center text-slate-600">
                <div className="text-center">
                  <Terminal className="w-8 h-8 mx-auto mb-2 opacity-30" />
                  <p>{t('logs.selectFiles')}</p>
                </div>
              </div>
            ) : mergedLines.length === 0 ? (
              <div className="h-full flex items-center justify-center text-slate-600">
                <div className="text-center">
                  <RefreshCw className="w-6 h-6 mx-auto mb-2 opacity-30 animate-spin" />
                  <p>{t('common.loading')}</p>
                </div>
              </div>
            ) : (
              <div>
                {mergedLines.map((l, i) => (
                  <div
                    key={`${l.source}-${l.timestamp}-${i}`}
                    className="flex gap-3 px-3 py-0.5 hover:bg-white/3 transition-colors"
                  >
                    <span className="text-slate-600 shrink-0 pt-0.5">
                      {new Date(l.timestamp).toLocaleTimeString(undefined, { hour12: false })}
                    </span>
                    <span className="text-slate-500 shrink-0 pt-0.5 w-36 truncate">
                      [{l.source}]
                    </span>
                    <span className={`break-all ${lineColor(l.line)}`}>{l.line}</span>
                  </div>
                ))}
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Status bar */}
          <div className="px-3 py-1.5 border-t border-white/5 flex items-center gap-3 shrink-0">
            <Terminal className="w-3 h-3 text-brand-neon animate-pulse" />
            <span className="text-xs font-mono text-brand-neon tracking-widest uppercase">
              {hasSelection
                ? t('logs.watchingFiles', { count: selectedFiles.length, server: selectedServer })
                : t('logs.ready')}
            </span>
          </div>
        </div>
      </div>
    </Layout>
  )
}
