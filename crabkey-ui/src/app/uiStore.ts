import { atom } from 'nanostores'
import type { Message } from '../lib/gatewayClient.ts'

export interface UIState {
  messages: Message[]
  isLoading: boolean
  input: string
  sessionName: string
  selectedThread: string | null
}

export const $messages = atom<Message[]>([])
export const $isLoading = atom<boolean>(false)
export const $input = atom<string>('')
export const $sessionName = atom<string>('default')
export const $selectedThread = atom<string | null>(null)

export const addMessage = (message: Message) => {
  const current = $messages.get()
  $messages.set([...current, message])
}

export const clearMessages = () => {
  $messages.set([])
}

export const setInput = (text: string) => {
  $input.set(text)
}

export const setLoading = (loading: boolean) => {
  $isLoading.set(loading)
}
