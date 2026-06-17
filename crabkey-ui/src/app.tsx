import React, { useEffect, useState } from 'react'
import { Box, Text } from 'ink'
import { useStore } from '@nanostores/react'
import { GatewayProvider } from './app/gatewayContext.tsx'
import { $messages, addMessage, setLoading } from './app/uiStore.ts'
import { GatewayClient } from './lib/gatewayClient.ts'
import { SessionDetails } from './components/SessionDetails.tsx'
import { ChatInput } from './components/ChatInput.tsx'
import { ChatMessage } from './components/ChatMessage.tsx'

function AppContent() {
  const messages = useStore($messages)
  const [sessionDetails, setSessionDetails] = useState({
    model: 'nex-agi/nex-n2-pro:free',
    provider: 'openrouter',
    tools: ['file.read', 'file.write', 'file.edit', 'shell.run', 'web.fetch'],
  })

  const handleSendMessage = (text: string) => {
    if (!text.trim()) return

    // Add user message
    addMessage({
      role: 'user',
      content: text,
    })

    // Simulate assistant response (will connect to Python backend)
    setLoading(true)
    setTimeout(() => {
      addMessage({
        role: 'assistant',
        content: `You said: "${text}". This is a simulated response.`,
      })
      setLoading(false)
    }, 500)
  }

  return (
    <Box flexDirection="column" width={100} height={30}>
      <Box marginBottom={1}>
        <Text bold color="cyan">
          🦀 CrabKey
        </Text>
      </Box>

      <Box marginBottom={1}>
        <Text dimColor>AI-Powered Coding Assistant</Text>
      </Box>

      <SessionDetails details={sessionDetails} />

      <Box flexDirection="column" flexGrow={1} marginBottom={1} overflowY="hidden">
        {messages.map((msg, idx) => (
          <ChatMessage key={idx} role={msg.role} content={msg.content} />
        ))}
      </Box>

      <ChatInput onSubmit={handleSendMessage} />
    </Box>
  )
}

export function App() {
  const gateway = new GatewayClient('ws://localhost:8765')

  useEffect(() => {
    gateway.connect().catch((error) => {
      console.error('Failed to connect to gateway:', error)
    })

    return () => {
      gateway.disconnect()
    }
  }, [])

  return (
    <GatewayProvider gateway={gateway}>
      <AppContent />
    </GatewayProvider>
  )
}
