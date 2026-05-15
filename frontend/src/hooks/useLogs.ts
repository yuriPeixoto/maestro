import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { logsApi, type LogLine } from '../services/api'

export const useLogFiles = (serverId: string) =>
  useQuery({
    queryKey: ['log-files', serverId],
    queryFn: () => logsApi.files(serverId),
    enabled: !!serverId,
    staleTime: 30_000,
  })

export const useLogHistory = (serverId: string, logFile: string, lines = 200) =>
  useQuery({
    queryKey: ['log-history', serverId, logFile, lines],
    queryFn: () => logsApi.history(serverId, logFile, lines),
    enabled: !!serverId && !!logFile,
  })

export type StreamStatus = 'connecting' | 'connected' | 'reconnecting' | 'error'

export const useLogStream = (serverId: string, logFile: string, enabled: boolean) => {
  const [lines, setLines] = useState<LogLine[]>([])
  const [status, setStatus] = useState<StreamStatus>('connecting')
  const esRef = useRef<EventSource | null>(null)
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!enabled || !serverId || !logFile) return

    let cancelled = false

    const connect = () => {
      if (cancelled) return
      setStatus('connecting')
      const url = `/api/logs/${serverId}/${logFile}/stream`
      const es = new EventSource(url)
      esRef.current = es

      es.onopen = () => {
        if (!cancelled) setStatus('connected')
      }

      es.onmessage = (event) => {
        if (cancelled) return
        try {
          const parsed: LogLine = JSON.parse(event.data)
          setLines((prev) => [...prev.slice(-1999), parsed])
        } catch {
          // malformed event — skip
        }
      }

      es.onerror = () => {
        es.close()
        if (cancelled) return
        setStatus('reconnecting')
        retryRef.current = setTimeout(connect, 3000)
      }
    }

    connect()

    return () => {
      cancelled = true
      esRef.current?.close()
      if (retryRef.current) clearTimeout(retryRef.current)
    }
  }, [serverId, logFile, enabled])

  return { lines, status }
}
