import React from 'react'
import { Box, Text } from 'ink'

interface ChatMessageProps {
  role: 'user' | 'assistant'
  content: string
}

export function ChatMessage({ role, content }: ChatMessageProps) {
  const isUser = role === 'user'

  return (
    <Box flexDirection="column" marginBottom={1}>
      {isUser ? (
        <>
          <Box borderStyle="round" borderColor="cyan" paddingX={1}>
            <Text color="cyan" bold>
              You:
            </Text>
          </Box>
          <Box marginLeft={2}>
            <Text>{content}</Text>
          </Box>
        </>
      ) : (
        <>
          <Box borderStyle="round" borderColor="green" paddingX={1}>
            <Text color="green" bold>
              Assistant:
            </Text>
          </Box>
          <Box marginLeft={2}>
            <Text>{content}</Text>
          </Box>
        </>
      )}
    </Box>
  )
}
