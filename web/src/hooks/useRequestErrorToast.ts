import { App } from 'antd'
import { useEffect, useRef } from 'react'

/** API 请求失败时用 message 提示，不阻断页面渲染 */
export function useRequestErrorToast(error: string | null, label?: string) {
  const { message } = App.useApp()
  const shownRef = useRef<string | null>(null)

  useEffect(() => {
    if (!error) {
      shownRef.current = null
      return
    }
    if (error === shownRef.current) {
      return
    }
    shownRef.current = error
    message.error(label ? `${label}: ${error}` : error)
  }, [error, label, message])
}
