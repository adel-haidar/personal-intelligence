export interface Connector {
  id: string
  display_name: string
  coming_soon: boolean
  configured: boolean
  connected: boolean
  status: string | null
  last_sync_at: string | null
  imported_count: number
}

export interface ConnectorStatus {
  connected: boolean
  running: boolean
  status: string | null
  imported_count: number
  last_sync_at: string | null
}

export interface ConnectorAuthorizeResponse {
  authorize_url: string
}

export interface ConnectorSyncResponse {
  started: boolean
}

export interface ConnectorDisconnectResponse {
  disconnected: boolean
}
