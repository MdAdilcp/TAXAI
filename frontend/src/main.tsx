import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean; errorMessage: string }
> {
  state = { hasError: false, errorMessage: '' }

  static getDerivedStateFromError(error: unknown) {
    return {
      hasError: true,
      errorMessage: error instanceof Error ? error.message : 'Unknown runtime error',
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: '1rem', color: '#ef4444', fontFamily: 'system-ui, sans-serif' }}>
          Frontend crashed: {this.state.errorMessage}
        </div>
      )
    }
    return this.props.children
  }
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>,
)
