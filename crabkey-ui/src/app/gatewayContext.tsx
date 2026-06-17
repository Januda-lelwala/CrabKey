import React, { createContext, useContext } from 'react'
import type { GatewayClient } from '../lib/gatewayClient.ts'

interface GatewayContextType {
  gateway: GatewayClient
}

const GatewayContext = createContext<GatewayContextType | null>(null)

export function GatewayProvider({
  children,
  gateway,
}: {
  children: React.ReactNode
  gateway: GatewayClient
}) {
  return <GatewayContext.Provider value={{ gateway }}>{children}</GatewayContext.Provider>
}

export function useGateway(): GatewayClient {
  const context = useContext(GatewayContext)
  if (!context) {
    throw new Error('useGateway must be used within GatewayProvider')
  }
  return context.gateway
}
