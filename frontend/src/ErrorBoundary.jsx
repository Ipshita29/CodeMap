import { Component } from 'react'

// React error boundaries must be class components -- there is still no
// hook equivalent of getDerivedStateFromError/componentDidCatch. Reuses
// the exact "panel" error-state markup already used for a failed
// repository analysis (see workspace.jsx/analyzing.jsx) so a render crash
// looks like the rest of the app's error states, not a one-off design.
export class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false }
    this.handleRetry = this.handleRetry.bind(this)
  }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error('CodeMap section crashed:', error, info)
  }

  handleRetry() {
    this.setState({ hasError: false })
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div className="panel error-boundary-panel">
        <h1 className="card-title">Something went wrong</h1>
        <p className="card-subtitle">
          {this.props.label ? `CodeMap couldn't render ${this.props.label}.` : "CodeMap couldn't render this section."}
        </p>
        <button type="button" className="btn btn-outline btn-block mt-6" onClick={this.handleRetry}>
          Try again
        </button>
      </div>
    )
  }
}
