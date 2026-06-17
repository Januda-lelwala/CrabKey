import React, { useState } from 'react'
import { Box, Text } from 'ink'
import TextInput from 'ink-text-input'

interface ChatInputProps {
  onSubmit: (text: string) => void
}

export function ChatInput({ onSubmit }: ChatInputProps) {
  const [input, setInput] = useState('')

  const handleSubmit = (value: string) => {
    if (value.trim()) {
      onSubmit(value)
      setInput('')
    }
  }

  return (
    <Box flexDirection="column" width="100%">
      <Box borderStyle="round" borderColor="cyan" paddingX={1}>
        <TextInput
          value={input}
          onChange={setInput}
          onSubmit={handleSubmit}
          placeholder="You: "
        />
      </Box>
    </Box>
  )
}
