export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

/** Vite 开发代理目标（展示用） */
export const XQTRADER_PROXY_TARGET =
  import.meta.env.VITE_XQTRADER_PROXY_TARGET ?? 'http://localhost:8086'
export const AI_GATEWAY_PROXY_TARGET =
  import.meta.env.VITE_AI_GATEWAY_PROXY_TARGET ?? 'http://localhost:8000'

/** 成功业务码 */
export const API_SUCCESS_CODE = 0
