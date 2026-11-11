// Nombre legible y color de cada rol en las tablas. Los roles de plantilla tienen color fijo; los
// que cree la organización reciben uno estable según su código.
const PLANTILLA = {
  SUPERADMIN: { texto: 'Superadmin', tono: 'ambar' },
  ADMIN: { texto: 'Administrador', tono: 'rojo' },
  VENDEDOR: { texto: 'Vendedor', tono: 'azul' },
  CAJERO: { texto: 'Cajero', tono: 'naranja' },
  ALMACENERO: { texto: 'Almacenero', tono: 'cian' },
  TECNICO: { texto: 'Técnico', tono: 'morado' },
  MARKETING: { texto: 'Marketing', tono: 'rosa' },
  CONTADOR: { texto: 'Contador', tono: 'verde' },
}

const TONOS = ['azul', 'morado', 'naranja', 'verde', 'cian', 'ambar', 'rosa']

const capitalizar = (codigo) => codigo.charAt(0) + codigo.slice(1).toLowerCase().replaceAll('_', ' ')

export function etiquetaRol(codigo) {
  if (PLANTILLA[codigo]) return PLANTILLA[codigo]
  let hash = 0
  for (const c of codigo) hash = (hash * 31 + c.charCodeAt(0)) % TONOS.length
  return { texto: capitalizar(codigo), tono: TONOS[hash] }
}
