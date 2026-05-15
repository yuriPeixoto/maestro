export interface ServerStatus {
  server_id: string
  status: 'online' | 'offline' | 'unknown'
  last_seen: string | null
  agent_version: string | null
}
