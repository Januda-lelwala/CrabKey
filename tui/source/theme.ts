/**
 * CrabKey color palette — warm crab orange/red primary with a cool cyan accent,
 * tuned to look good on both dark and light terminals.
 */
export const theme = {
  primary: '#FF7A59', // crab orange
  primaryDeep: '#FF5C5C', // crab red
  accent: '#22D3EE', // cyan
  user: '#7AA2F7', // soft blue
  assistant: '#E6E6E6',
  dim: 'gray',
  muted: '#6B7280',
  success: '#9ECE6A',
  error: '#F7768E',
  warn: '#E0AF68',
  tool: '#BB9AF7', // violet
  toolResult: '#73DACA', // teal
  code: '#A9B1D6',
  border: '#3B4261',
} as const;

/** Gradient used for the banner and primary flourishes. */
export const brandGradient: [string, string] = [theme.primary, theme.primaryDeep];
