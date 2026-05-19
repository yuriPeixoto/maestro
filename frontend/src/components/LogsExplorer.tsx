import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Download, Filter, Terminal, Wifi, WifiOff, RefreshCw } from 'lucide-react'
import Layout from './Layout'
import type { ViewType } from '../App'
import { useServers } from '../hooks/useServers'
import { useLogFiles, useLogHistory, useLogStream, type StreamStatus } from '../hooks/useLogs'
import type { LogLine } from '../services/api'

interface LogsExplorerProps {
  setView: (view: ViewType) => void
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
  if (status === 'connected')
    return <Wifi className="w-3 h-3 text-brand-neon" />
  if (status === 'reconnecting')
    return <RefreshCw className="w-3 h-3 text-orange-400 animate-spin" />
  return <WifiOff className="w-3 h-3 text-slate-500" />
}

interface LogStreamProps {
  serverId: string
  logFile: string
  initialLines: LogLine[]
  filter: string
}

function LogStream({ serverId, logFile, initialLines, filter }: LogStreamProps) {
  const { lines: streamLines, status } = useLogStream(serverId, logFile, true)
  const allLines = useMemo(
    () => [...initialLines, ...streamLines].slice(-2000),
    [initialLines, streamLines],
  )
  const filtered = filter
    ? allLines.filter((l) => l.line.toLowerCase().includes(filter.toLowerCase()))
    : allLines

  return (
    <div>
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-white/5 bg-white/3 text-xs font-mono">
        <StatusDot status={status} />
        <span className="text-slate-400">{logFile}</span>
        <span className="ml-auto text-slate-600">{filtered.length} lines</span>
      </div>
      <div className="space-y-0">
        {filtered.map((l, i) => (
          <div
            key={`${l.timestamp}-${i}`}
            className="flex gap-3 px-3 py-0.5 hover:bg-white/3 transition-colors group"
          >
            <span className="text-slate-600 shrink-0 text-xs pt-0.5">
              {new Date(l.timestamp).toLocaleTimeString(undefined, { hour12: false })}
            </span>
            <span className={`text-xs font-mono break-all ${lineColor(l.line)}`}>{l.line}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function LogsExplorer({ setView }: LogsExplorerProps) {
  const { t } = useTranslation()
  const [selectedServer, setSelectedServer] = useState('')
  const [selectedFiles, setSelectedFiles] = useState<string[]>([])
  const [filter, setFilter] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  const { data: servers } = useServers()
  const { data: logFilesData } = useLogFiles(selectedServer)
  const { data: historyData } = useLogHistory(
    selectedServer,
    selectedFiles[0] ?? '',
    200,
  )

  useEffect(() => {
    if (servers && servers.length > 0 && !selectedServer) {
      setSelectedServer(servers[0].server_id)
    }
  }, [servers, selectedServer])

  useEffect(() => {
    setSelectedFiles([])
  }, [selectedServer])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [historyData])

  const toggleFile = (file: string) => {
    setSelectedFiles((prev) =>
      prev.includes(file) ? prev.filter((f) => f !== file) : [...prev, file],
    )
  }

  const exportLogs = () => {
    const content = (historyData?.lines ?? [])
      .map((l) => `[${l.timestamp}] [${l.log_file}] ${l.line}`)
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
                <label
                  key={file}
                  className="flex items-center gap-2 cursor-pointer group py-0.5"
                >
                  <input
                    type="checkbox"
                    checked={selectedFiles.includes(file)}
                    onChange={() => toggleFile(file)}
                    className="accent-brand-purple"
                  />
                  <span className={`text-xs font-mono truncate group-hover:text-white transition-colors ${selectedFiles.includes(file) ? 'text-white' : 'text-slate-400'}`}>
                    {file}
                  </span>
                </label>
              ))}
            </div>
          </div>
        </div>

        {/* Terminal panel */}
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

          {/* Log output */}
          <div className="flex-1 overflow-y-auto bg-black/30 font-mono text-xs">
            {!hasSelection ? (
              <div className="h-full flex items-center justify-center text-slate-600">
                <div className="text-center">
                  <Terminal className="w-8 h-8 mx-auto mb-2 opacity-30" />
                  <p>{t('logs.selectFiles')}</p>
                </div>
              </div>
            ) : (
              <div className="divide-y divide-white/3">
                {selectedFiles.map((file) => (
                  <LogStream
                    key={file}
                    serverId={selectedServer}
                    logFile={file}
                    initialLines={
                      selectedFiles[0] === file ? (historyData?.lines ?? []) : []
                    }
                    filter={filter}
                  />
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
