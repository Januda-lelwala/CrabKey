import { WebSocket } from 'ws'

export interface Message {
  role: 'user' | 'assistant'
  content: string
}

export interface GatewayRequest {
  jsonrpc: '2.0'
  method: string
  params?: Record<string, unknown>
  id?: string | number
}

export interface GatewayResponse<T = unknown> {
  jsonrpc: '2.0'
  result?: T
  error?: {
    code: number
    message: string
  }
  id?: string | number
}

export class GatewayClient {
  private ws: WebSocket | null = null
  private url: string
  private messageHandlers: Map<string, (data: unknown) => void> = new Map()
  private requestId: number = 0

  constructor(url: string = 'ws://localhost:8765') {
    this.url = url
  }

  async connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        // Note: In browser context, use native WebSocket
        // In Node.js context, this would use 'ws' library
        const ws = new (typeof window !== 'undefined' ? window.WebSocket : WebSocket)(this.url)

        ws.onopen = () => {
          this.ws = ws as any
          resolve()
        }

        ws.onerror = (error) => {
          reject(error)
        }

        ws.onmessage = (event) => {
          this.handleMessage(event.data)
        }
      } catch (error) {
        reject(error)
      }
    })
  }

  private handleMessage(data: string): void {
    try {
      const response = JSON.parse(data) as GatewayResponse
      if (response.id && this.messageHandlers.has(String(response.id))) {
        const handler = this.messageHandlers.get(String(response.id))
        this.messageHandlers.delete(String(response.id))
        handler?.(response.result || response.error)
      }
    } catch (error) {
      console.error('Failed to parse gateway message:', error)
    }
  }

  async request<T = unknown>(method: string, params?: Record<string, unknown>): Promise<T> {
    if (!this.ws) {
      throw new Error('Gateway client not connected')
    }

    const id = ++this.requestId
    const request: GatewayRequest = {
      jsonrpc: '2.0',
      method,
      params,
      id,
    }

    return new Promise((resolve, reject) => {
      this.messageHandlers.set(String(id), (data) => {
        if (typeof data === 'object' && data !== null && 'message' in data) {
          reject(new Error((data as any).message))
        } else {
          resolve(data as T)
        }
      })

      this.ws?.send(JSON.stringify(request))

      // Timeout after 30 seconds
      setTimeout(() => {
        if (this.messageHandlers.has(String(id))) {
          this.messageHandlers.delete(String(id))
          reject(new Error('Request timeout'))
        }
      }, 30000)
    })
  }

  async sendMessage(message: string): Promise<Message> {
    return this.request('send_message', { message })
  }

  async getSessionDetails(): Promise<{
    model: string
    provider: string
    tools: string[]
  }> {
    return this.request('get_session_details')
  }

  disconnect(): void {
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
  }
}
