export const MODEL_TYPES = ['chat', 'embedding', 'rerank', 'image'] as const

export type ModelType = (typeof MODEL_TYPES)[number]

const PROVIDER_BRAND_COLORS: Record<string, string> = {
  openai: '#10a37f',
  anthropic: '#d97706',
  modelscope: '#624aff',
  dashscope: '#ff6a00',
  doubao: '#3370ff',
  deepseek: '#4d6bfe',
  google: '#4285f4',
  azure_openai: '#0078d4',
  ernie: '#e53935',
  zhipu: '#1677ff',
  siliconcloud: '#6366f1',
  ollama: '#64748b',
  lmstudio: '#64748b',
  custom_openai: '#94a3b8',
}

export function getProviderBrandColor(code: string) {
  const normalized = code.toLowerCase()
  if (PROVIDER_BRAND_COLORS[normalized]) {
    return PROVIDER_BRAND_COLORS[normalized]
  }
  let hash = 0
  for (let i = 0; i < normalized.length; i += 1) {
    hash = normalized.charCodeAt(i) + ((hash << 5) - hash)
  }
  const hue = Math.abs(hash) % 360
  return `hsl(${hue} 55% 45%)`
}

export function maskApiKey(key?: string) {
  if (!key) return '—'
  if (key.length <= 8) return '****'
  return `${key.slice(0, 4)}****${key.slice(-4)}`
}
