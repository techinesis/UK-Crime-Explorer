import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

interface ErrorBoundaryProps {
  children: ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
}

// Top-level (and per-route) React error boundary. A single uncaught render
// error used to blank the whole page; this catches it, logs the full stack for
// the team, and shows a friendly fallback with a one-click refresh. Class
// component because componentDidCatch / getDerivedStateFromError have no hooks
// equivalent.
export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false }

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Always surface the full error + component stack to the console so a
    // caught crash is still debuggable.
    console.error('ErrorBoundary caught an error:', error, info.componentStack)
  }

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children

    return (
      <div className="flex h-full min-h-[60vh] w-full flex-col items-center justify-center bg-surface px-6 text-center">
        <div className="max-w-md rounded-xl border border-border bg-card p-8 shadow-lg">
          <h1 className="text-xl font-semibold text-fg">Something went wrong</h1>
          <p className="mt-2 text-sm text-muted">
            The dashboard hit an unexpected error. Refresh the page to try again.
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-5 rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
          >
            Refresh
          </button>
        </div>
      </div>
    )
  }
}
