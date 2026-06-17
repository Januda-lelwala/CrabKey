import React from 'react'
import { Box } from 'ink'

interface AppLayoutProps {
  children: React.ReactNode
}

export function AppLayout({ children }: AppLayoutProps) {
  return (
    <Box flexDirection="column" width={100} height={30}>
      {children}
    </Box>
  )
}
