import React from 'react'
import { Box, Text } from 'ink'

interface SessionDetailsProps {
  details: {
    model: string
    provider: string
    tools: string[]
  }
}

export function SessionDetails({ details }: SessionDetailsProps) {
  return (
    <Box flexDirection="column" marginBottom={1} borderStyle="round" borderColor="cyan" paddingX={2} paddingY={1}>
      <Box marginBottom={1}>
        <Text bold color="cyan">
          Session Details
        </Text>
      </Box>

      <Box>
        <Box width={20}>
          <Text>Model</Text>
        </Box>
        <Text color="cyan">{details.model}</Text>
      </Box>

      <Box>
        <Box width={20}>
          <Text>Provider</Text>
        </Box>
        <Text color="cyan">{details.provider}</Text>
      </Box>

      <Box>
        <Box width={20}>
          <Text>Tools</Text>
        </Box>
        <Text color="cyan">{details.tools.join(', ')}</Text>
      </Box>
    </Box>
  )
}
