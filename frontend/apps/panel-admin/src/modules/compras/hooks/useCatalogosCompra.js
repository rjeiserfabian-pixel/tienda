import { useMemo } from 'react'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useOpciones } from '../../almacen/hooks/useOpciones'

/**
 * Catálogos que usa la pantalla de compras. Cada uno se pide una sola vez (y se comparte con el
 * resto del panel por la caché). Las cajas y cuentas piden su propio permiso: si falta, la
 * pantalla lo avisa en lugar de quedar sin opciones sin explicación.
 */
export function useCatalogosCompra(empresaId) {
  const { tiene } = usePermisos()
  const puedeVerCajas = tiene('CAJA.CUENTAS.VER')
  const puedeUbicar = tiene('INVENTARIO.UBICACIONES.ASIGNAR')
  const habilitado = Boolean(empresaId)

  const almacenes = useOpciones('/mantenimiento/almacenes/', { empresa: empresaId }, { enabled: habilitado })
  const comprobantes = useOpciones('/mantenimiento/tipos-comprobante/', { aplica_compras: '1' })
  const afectaciones = useOpciones('/mantenimiento/afectaciones-igv/', { aplica_compras: '1' })
  const medios = useOpciones('/mantenimiento/medios-pago/')
  const cuentas = useOpciones('/mantenimiento/cuentas/', { empresa: empresaId }, { enabled: habilitado && puedeVerCajas })
  const periodicidades = useOpciones('/mantenimiento/periodicidades/')
  const listas = useOpciones('/mantenimiento/listas-precio/')

  return useMemo(
    () => ({ almacenes, comprobantes, afectaciones, medios, cuentas, periodicidades, listas, puedeVerCajas, puedeUbicar }),
    [almacenes, comprobantes, afectaciones, medios, cuentas, periodicidades, listas, puedeVerCajas, puedeUbicar],
  )
}
