import { useEffect } from 'react'
import { useStore } from '@nanostores/react'
import { $messages, $isLoading, setLoading, addMessage } from './uiStore.ts'
import type { GatewayClient } from '../lib/gatewayClient.ts'

export function useMainApp(gateway: GatewayClient) {
  const messages = useStore($messages)
  const isLoading = useStore($isLoading)

  useEffect(() => {
    // Initialize gateway connection if needed
    if (!gateway) {
      console.error('Gateway not available')
    }
  }, [gateway])

  const handleSendMessage = async (text: string) => {
    if (!text.trim()) return

    // Add user message
    addMessage({
      role: 'user',
      content: text,
    })

    setLoading(true)

    try {
      // Send to gateway/backend
      const response = await gateway.sendMessage(text)
      addMessage(response)
    } catch (error) {
      console.error('Failed to send message:', error)
      addMessage({
        role: 'assistant',
        content: `Error: ${error instanceof Error ? error.message : 'Unknown error'}`,
      })
    } finally {
      setLoading(false)
    }
  }

  return {
    messages,
    isLoading,
    onSendMessage: handleSendMessage,
  }
}
