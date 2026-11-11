import { Component } from 'react'

/** Evita la pantalla en blanco: muestra un mensaje controlado si un componente falla. */
export default class ErrorBoundary extends Component {
  state = { fallo: false }

  static getDerivedStateFromError() {
    return { fallo: true }
  }

  componentDidCatch(error, info) {
    console.error('Error de interfaz', error, info.componentStack)
  }

  render() {
    if (this.state.fallo) {
      return (
        <div role="alert" style={{ padding: 24 }}>
          <h2>Ocurrió un problema</h2>
          <p>Recargue la página. Si persiste, contacte al administrador.</p>
        </div>
      )
    }
    return this.props.children
  }
}
