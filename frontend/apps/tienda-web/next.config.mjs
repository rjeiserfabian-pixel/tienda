/**
 * Configuración de la tienda.
 *
 * - Las fotos y las consultas del navegador (sugerencias) van a la MISMA dirección de la tienda
 *   (`/api/v1/tienda/...`) y aquí se reenvían a la API: así no hace falta CORS y el navegador puede
 *   guardar las fotos (la API las marca como inmutables por un año).
 * - Las páginas se arman en el servidor con la API (`API_URL`) y se guardan un minuto, igual que la
 *   caché de la propia API, para que casi ninguna visita llegue hasta la base de datos.
 */
const API_URL = process.env.API_URL || 'http://localhost:8000'

const cabecerasDeSeguridad = [
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'X-Frame-Options', value: 'SAMEORIGIN' },
  { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
]

/** @type {import('next').NextConfig} */
const config = {
  // Carpeta de compilación (varias personas pueden trabajar a la vez con carpetas distintas).
  distDir: process.env.NEXT_DIST_DIR || '.next',
  reactStrictMode: true,
  poweredByHeader: false,
  compress: true,
  async rewrites() {
    // Next quita la barra final de las direcciones con un redirect; por eso la tienda pide siempre SIN
    // barra (ver lib/api.js y Buscador) y la API pública acepta las rutas con o sin ella.
    return [{ source: '/api/v1/tienda/:path*', destination: `${API_URL}/api/v1/tienda/:path*` }]
  },
  async headers() {
    return [{ source: '/:path*', headers: cabecerasDeSeguridad }]
  },
}

export default config
