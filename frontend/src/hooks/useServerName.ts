import { useCallback } from 'react'
import type { ServerStatus } from '../types/server'
import { useServers } from './useServers'

export interface ServerName {
  /** What the screen shows first: the account's nickname, else the shared label, else the hostname. */
  display: string
  /** The hostname, shown small under `display` when they differ. */
  hostname: string
  /** True when `display` is not the hostname. */
  renamed: boolean
}

type Names = Pick<ServerStatus, 'server_id' | 'label' | 'nickname'>

export const serverName = (server: Names): ServerName => {
  const display = server.nickname ?? server.label ?? server.server_id
  return { display, hostname: server.server_id, renamed: display !== server.server_id }
}

const normalize = (text: string) => text.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()

/** A search finds a server by its nickname, its label or its hostname, accents and case aside. */
export const serverMatches = (server: Names, query: string): boolean => {
  const wanted = normalize(query.trim())
  if (!wanted) return true
  return [server.nickname, server.label, server.server_id].some((name) => name && normalize(name).includes(wanted))
}

/**
 * The one place screens get a server's name from, so the order (nickname, label, hostname)
 * is the same everywhere. Reads the cached server list; an unknown id shows as itself.
 */
export const useServerName = () => {
  const { data: servers } = useServers()
  return useCallback(
    (serverId: string): ServerName => {
      const server = servers?.find((s) => s.server_id === serverId)
      return server ? serverName(server) : { display: serverId, hostname: serverId, renamed: false }
    },
    [servers],
  )
}
