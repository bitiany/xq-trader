import { Component, type ErrorInfo, type ReactNode } from 'react'
import { ServerErrorPage } from '@/pages/errors/ServerErrorPage'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
}

export class RouteErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError(): State {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[RouteErrorBoundary]', error, info.componentStack)
  }

  render() {
    if (this.state.hasError) {
      return <ServerErrorPage embedded />
    }
    return this.props.children
  }
}
