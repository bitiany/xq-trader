import axios, { type AxiosInstance, type AxiosRequestConfig, type AxiosResponse } from 'axios'
import { API_BASE_URL, API_SUCCESS_CODE } from '@/api/config'
import { ApiError, type ApiResponse } from '@/api/types'

export interface RequestOptions extends AxiosRequestConfig {
  /** 跳过 { code, message, data } 统一解包（如 AI 流式对话） */
  rawResponse?: boolean
  /** 预留：跳过鉴权头注入 */
  skipAuth?: boolean
}

function createHttpClient(): AxiosInstance {
  const instance = axios.create({
    baseURL: API_BASE_URL,
    timeout: 120_000,
    headers: {
      'Content-Type': 'application/json',
    },
  })

  instance.interceptors.request.use((config) => {
    const options = config as RequestOptions

    // TODO: 认证鉴权 — 从 store 读取 token 并注入 Authorization
    if (!options.skipAuth) {
      const token = localStorage.getItem('xqtrader-token')
      if (token) {
        config.headers.Authorization = `Bearer ${token}`
      }
    }

    return config
  })

  instance.interceptors.response.use(
    (response: AxiosResponse) => {
      const options = response.config as RequestOptions

      if (options.rawResponse) {
        return response
      }

      const body = response.data as ApiResponse | undefined
      if (!body || typeof body !== 'object' || !('code' in body)) {
        throw new ApiError('响应格式不符合约定', -1, response.status)
      }

      if (body.code !== API_SUCCESS_CODE) {
        throw new ApiError(body.message || '请求失败', body.code, response.status)
      }

      return { ...response, data: body.data }
    },
    (error) => {
      if (axios.isAxiosError(error)) {
        const status = error.response?.status
        const body = error.response?.data as ApiResponse | undefined
        const message =
          body?.message ||
          error.message ||
          (status ? `HTTP ${status}` : '网络请求失败')

        throw new ApiError(message, body?.code ?? -1, status)
      }
      throw error
    },
  )

  return instance
}

const http = createHttpClient()

async function requestData<T>(promise: Promise<AxiosResponse<T>>): Promise<T> {
  const response = await promise
  return response.data
}

export const request = {
  get<T>(url: string, config?: RequestOptions) {
    return requestData(http.get<T>(url, config))
  },

  post<T>(url: string, data?: unknown, config?: RequestOptions) {
    return requestData(http.post<T>(url, data, config))
  },

  put<T>(url: string, data?: unknown, config?: RequestOptions) {
    return requestData(http.put<T>(url, data, config))
  },

  patch<T>(url: string, data?: unknown, config?: RequestOptions) {
    return requestData(http.patch<T>(url, data, config))
  },

  delete<T>(url: string, config?: RequestOptions) {
    return requestData(http.delete<T>(url, config))
  },
}

export { http }
