'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { urlFoto } from '@/lib/format'
import Icono from './Icono'
import { MAX_COMPARAR, useComparar } from './ProveedorComparar'

/** Barra fija inferior con los productos elegidos para comparar. No aparece en /comparar. */
export default function BarraComparar() {
  const comparar = useComparar()
  const ruta = usePathname()
  if (!comparar?.listo || ruta?.startsWith('/comparar')) return null
  const { items, aviso } = comparar
  if (items.length === 0 && !aviso) return null
  const puede = items.length >= 2
  return (
    <div className="barra-comparar" role="region" aria-label="Productos para comparar">
      <p className="barra-comparar-aviso" role="status" aria-live="polite">
        {aviso}
      </p>
      {items.length > 0 && (
        <div className="barra-comparar-fila">
          <ul className="barra-comparar-lista">
            {items.map((i) => (
              <li key={i.id} className="barra-comparar-item">
                {i.foto ? <img src={urlFoto(i.foto)} alt="" width={44} height={44} decoding="async" /> : <span aria-hidden="true">?</span>}
                <button type="button" onClick={() => comparar.quitar(i.id)} aria-label={`Quitar ${i.nombre || 'producto'} de la comparación`}>
                  <Icono nombre="cerrar" tam={12} />
                </button>
              </li>
            ))}
          </ul>
          <p className="barra-comparar-texto">
            {puede ? `${items.length} de ${MAX_COMPARAR} productos` : 'Elige al menos 2 productos'}
          </p>
          <div className="barra-comparar-acciones">
            <button type="button" className="boton fantasma chico" onClick={comparar.limpiar}>
              Limpiar
            </button>
            {puede ? (
              <Link href={`/comparar?ids=${items.map((i) => i.id).join(',')}`} className="boton chico">
                Comparar ({items.length})
              </Link>
            ) : (
              <span className="boton chico" aria-disabled="true">
                Comparar
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
