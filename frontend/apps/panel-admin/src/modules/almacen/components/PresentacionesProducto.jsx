import { useState } from 'react'
import { api } from '../../../core/api/client'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { soles } from '../utilidades'
import PresentacionModal from './PresentacionModal'

/**
 * Otras unidades en que se compra o vende el producto (caja, docena…). El stock siempre se lleva
 * en la unidad base; aquí se dice cuántas unidades base trae cada presentación. Cada cambio se
 * guarda al instante, sin depender del botón «Guardar cambios» del producto.
 */
export default function PresentacionesProducto({ producto, listas, puedeEditar, puedePrecios }) {
  const [modal, setModal] = useState(null) // { presentacion } para editar, {} para agregar
  const [quitando, setQuitando] = useState(null)
  const presentaciones = producto.presentaciones ?? []
  const principal = listas.find((l) => l.es_principal) ?? listas[0]

  const quitar = useMutacion({
    mutationFn: (id) => api.delete(`/mantenimiento/presentaciones/${id}/`),
    invalidar: [['productos'], ['opciones']],
    exito: 'Presentación eliminada.',
    alExito: () => setQuitando(null),
  })

  return (
    <PanelTarjeta
      id="presentaciones"
      icono="boxes"
      titulo="Otras unidades (presentaciones)"
      descripcion={`Por ejemplo, la caja de 12 o la docena. El stock siempre se lleva en ${producto.unidad_nombre ?? 'la unidad base'} (${producto.unidad_abreviatura}).`}
      acciones={
        puedeEditar && !producto.lleva_serie ? (
          <button type="button" className="boton-cabecera" onClick={() => setModal({})}>
            <Icono nombre="agregar" tam={19} /> Agregar presentación
          </button>
        ) : undefined
      }
    >
      {producto.lleva_serie ? (
        <p className="celda-suave">Un producto con serie o IMEI solo se maneja en su unidad base, porque cada unidad lleva su propia serie.</p>
      ) : presentaciones.length === 0 ? (
        <p className="celda-suave">Este producto solo se maneja en {producto.unidad_abreviatura}. Agrega una presentación si también se compra o se vende por caja, docena u otra unidad.</p>
      ) : (
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Presentación</th>
                <th>Equivale a</th>
                <th>Código de barras</th>
                {principal && <th className="num">Precio {principal.nombre}</th>}
                <th>Estado</th>
                {puedeEditar && <th className="centrado">Acciones</th>}
              </tr>
            </thead>
            <tbody>
              {presentaciones.map((p) => {
                const precio = principal ? p.precios.find((x) => x.lista === principal.id) : null
                return (
                  <tr key={p.id} className={p.estado === 'INACTIVO' ? 'anulado' : undefined}>
                    <td><strong>{p.unidad_nombre}</strong></td>
                    <td>{p.equivalencia}</td>
                    <td className="celda-suave">{p.codigo_barras || '—'}</td>
                    {principal && <td className="num">{precio ? soles(precio.precio) : '—'}</td>}
                    <td>{p.estado === 'ACTIVO' ? <span className="estado-pildora activo">Activa</span> : <span className="estado-pildora inactivo">Inactiva</span>}</td>
                    {puedeEditar && (
                      <td className="centrado">
                        <span className="acciones-fila">
                          <button type="button" className="accion-icono editar" aria-label={`Editar ${p.unidad_nombre}`} title="Editar" onClick={() => setModal({ presentacion: p })}>
                            <Icono nombre="lapiz" tam={19} />
                          </button>
                          <button type="button" className="accion-icono peligro-suave" aria-label={`Quitar ${p.unidad_nombre}`} title="Quitar" onClick={() => setQuitando(p)}>
                            <Icono nombre="papelera" tam={19} />
                          </button>
                        </span>
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {modal && <PresentacionModal producto={producto} presentacion={modal.presentacion} listas={listas} puedePrecios={puedePrecios} onCerrar={() => setModal(null)} />}
      {quitando && (
        <ConfirmarModal
          titulo="Quitar presentación"
          mensaje={`¿Quitar «${quitando.equivalencia}» de ${producto.nombre}? Los documentos ya registrados no cambian.`}
          textoConfirmar="Quitar"
          enviando={quitar.isPending}
          onConfirmar={() => quitar.mutate(quitando.id)}
          onCerrar={() => setQuitando(null)}
        />
      )}
    </PanelTarjeta>
  )
}
