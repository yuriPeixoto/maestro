export interface ServerStatus {
  /** The hostname: the identity in notifications, the audit log and searches. */
  server_id: string
  status: 'online' | 'offline' | 'unknown'
  last_seen: string | null
  agent_version: string | null
  /** Shared name set by an admin, seen by everyone. */
  label: string | null
  group_id: number | null
  group_name: string | null
  /** The signed-in account's own name for the server; nobody else sees it. */
  nickname: string | null
}
