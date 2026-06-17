import React, { useEffect, useState } from 'react'
import { Box, Text } from 'ink'
import { AppLayout } from './components/AppLayout.tsx'
import { SessionDetails } from './components/SessionDetails.tsx'
import { ChatInput } from './components/ChatInput.tsx'
import { ChatMessage } from './components/ChatMessage.tsx'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

export function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [sessionDetails, setSessionDetails] = useState({
    model: 'nex-agi/nex-n2-pro:free',
    provider: 'openrouter',
    tools: ['file.read', 'file.write', 'file.edit', 'shell.run', 'web.fetch'],
  })

  const handleSendMessage = (text: string) => {
    if (!text.trim()) return

    // Add user message
    const userMessage: Message = { role: 'user', content: text }
    setMessages((prev) => [...prev, userMessage])

    // Simulate assistant response (will connect to Python backend)
    setTimeout(() => {
      const assistantMessage: Message = {
        role: 'assistant',
        content: `You said: "${text}". This is a simulated response.`,
      }
      setMessages((prev) => [...prev, assistantMessage])
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
