import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // /api/v1 se reenvía al backend Django, tanto en desarrollo como en la vista previa de la
  // compilación: así el navegador habla con UN solo origen (sin CORS ni cookies cruzadas) y basta
  // un túnel (ngrok) para mostrar el sistema completo.
  const backend = env.VITE_BACKEND_URL || 'http://localhost:8000'
  const proxy = { '/api/v1': { target: backend, changeOrigin: true } }

  // Vite rechaza peticiones con un nombre de host que no conoce. Los túneles de ngrok se aceptan
  // (el punto inicial incluye cualquier subdominio); otros dominios van en VITE_HOSTS_PERMITIDOS,
  // separados por comas.
  const allowedHosts = [
    '.ngrok-free.app',
    '.ngrok-free.dev',
    '.ngrok.app',
    '.ngrok.dev',
    '.ngrok.io',
    ...(env.VITE_HOSTS_PERMITIDOS || '').split(',').map((h) => h.trim()).filter(Boolean),
  ]

  return {
    plugins: [react()],
    server: { port: 5173, proxy, allowedHosts },
    preview: { port: 4173, proxy, allowedHosts },
  }
})
