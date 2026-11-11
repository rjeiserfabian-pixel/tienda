/**
 * Color principal de la tienda (lo elige el negocio en el panel).
 *
 * Solo se acepta un color «#RRGGBB»; cualquier otra cosa se ignora, porque este texto termina dentro de
 * una etiqueta <style>. En modo oscuro el color se aclara para que se lea sobre el fondo oscuro.
 */
const COLOR = /^#[0-9a-fA-F]{6}$/

export function cssDelColor(color) {
  if (typeof color !== 'string' || !COLOR.test(color)) return null
  const c = color.toLowerCase()
  return [
    `:root{--accent:${c};--accent-hover:color-mix(in srgb,${c} 85%,#000);--accent-ink:#fff;--accent-soft:color-mix(in srgb,${c} 12%,#fff)}`,
    `@media (prefers-color-scheme:dark){:root{--accent:color-mix(in srgb,${c} 62%,#fff);--accent-hover:color-mix(in srgb,${c} 48%,#fff);--accent-ink:#0b0f19;--accent-soft:color-mix(in srgb,${c} 28%,#0b0f19)}}`,
  ].join('')
}
