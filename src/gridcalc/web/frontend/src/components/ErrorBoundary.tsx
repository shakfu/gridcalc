import { Component, type ErrorInfo, type ReactNode } from 'react'

interface State {
  error: Error | null
}

// A render crash inside a pywebview window is otherwise invisible: there is no
// devtools console the user will open, so an unhandled React error just blanks
// the app. This catches it and shows what happened, with the stack available
// for a bug report.
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('gridcalc web: unhandled render error', error, info.componentStack)
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <div className="crash" role="alert">
        <h1>gridcalc hit an unexpected error</h1>
        <p className="error">{error.message}</p>
        <pre>{error.stack}</pre>
        <button className="btn" onClick={() => this.setState({ error: null })}>
          Try again
        </button>
      </div>
    )
  }
}
