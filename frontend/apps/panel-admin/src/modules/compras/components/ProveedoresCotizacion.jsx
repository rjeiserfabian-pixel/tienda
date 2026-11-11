import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import BuscadorAsincrono from '../../../shared/components/BuscadorAsincrono'
import Can from '../../../shared/components/Can'
import { Icono } from '../../../shared/components/IconosPanel'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { descargarArchivo, mensajeDeErrorDescarga } from '../../../shared/utils/descarga'
import { cantidad as formatoCantidad, fechaCorta } from '../../almacen/inventario'
import { accionesDe, enlaceCorreo, enlaceWhatsapp, ESTADOS_RESPUESTA, MAX_PROVEEDORES, ORIGENES_RESPUESTA, telefonoWhatsapp, textoCotizacion } from '../cotizaciones'

const CREAR = 'COTIZACIONES_COMPRA.CREAR'

/** Un proveedor de la cotización con todo lo que se puede hacer con él. */
function TarjetaProveedor({ cotizacion: c, proveedor: p, comparativo, abiertas, onAccion }) {
  const notificar = useNotificar()
  const [bajando, setBajando] = useState(false)
  const [errorPlantilla, setErrorPlantilla] = useState('')
  const info = comparativo.find((x) => x.respuesta === p.respuesta)
  const estado = ESTADOS_RESPUESTA[p.estado]
  const acciones = accionesDe(c.estado)
  const texto = textoCotizacion(c, { fechaCorta, cantidad: formatoCantidad })
  const telefono = telefonoWhatsapp(p.telefono)
  const puedeActuar = acciones.responder && !p.orden

  const plantilla = async () => {
    if (bajando) return
    setBajando(true)
    setErrorPlantilla('')
    try {
      const nombre = await descargarArchivo(`/compras/cotizaciones/${c.id}/plantilla/`, { respuesta: p.respuesta })
      notificar('exito', `Se descargó ${nombre}.`)
    } catch (e) {
      setErrorPlantilla(await mensajeDeErrorDescarga(e))
    } finally {
      setBajando(false)
    }
  }

  return (
    <li className="cotiz-proveedor">
      <div className="cotiz-proveedor-cabecera">
        <div>
          <strong>{p.nombre}</strong>
          <span className="sub-texto">
            {[p.telefono, p.correo].filter(Boolean).join(' · ') || 'Sin teléfono ni correo guardados'}
          </span>
        </div>
        <span className="pildora" data-tono={estado?.tono}>
          {estado?.texto ?? p.estado}
        </span>
      </div>
      {p.estado === 'RESPONDIDA' && info && (
        <p className="celda-suave">
          {ORIGENES_RESPUESTA[info.origen] ?? 'Respondida'} · {info.productos_cotizados} de {c.lineas.length} productos
          {info.vencida ? ' · oferta vencida' : ''}
        </p>
      )}
      {p.orden && (
        <p>
          <Link to={`/compras/ordenes/${p.orden}`}>Orden de compra {p.orden_codigo}</Link>
        </p>
      )}
      <div className="cotiz-acciones">
        {acciones.responder && telefono && (
          <a className="boton-cabecera" href={enlaceWhatsapp(telefono, texto)} target="_blank" rel="noopener noreferrer">
            <Icono nombre="chat" tam={18} /> WhatsApp
          </a>
        )}
        {acciones.responder && p.correo && (
          <a className="boton-cabecera" href={enlaceCorreo(p.correo, `Solicitud de cotización ${c.codigo}`, texto)}>
            <Icono nombre="correo" tam={18} /> Correo
          </a>
        )}
        <Can permiso={CREAR}>
          {puedeActuar && (
            <>
              <button type="button" className="boton-cabecera" disabled={bajando} onClick={plantilla}>
                <Icono nombre="exportar" tam={18} /> {bajando ? 'Generando…' : 'Plantilla Excel'}
              </button>
              <button type="button" className="primario boton-cabecera" onClick={() => onAccion({ tipo: 'respuesta', proveedor: p })}>
                <Icono nombre="lapiz" tam={18} /> {p.estado === 'RESPONDIDA' ? 'Corregir respuesta' : 'Registrar respuesta'}
              </button>
              <button type="button" className="boton-cabecera" onClick={() => onAccion({ tipo: 'importar', proveedor: p })}>
                <Icono nombre="importar" tam={18} /> Importar Excel
              </button>
              {p.estado !== 'DECLINADA' && (
                <button type="button" className="boton-cabecera" onClick={() => onAccion({ tipo: 'declinar', proveedor: p })}>
                  No cotiza
                </button>
              )}
              {p.estado === 'PENDIENTE' && abiertas && (
                <button type="button" className="boton-cabecera" onClick={() => onAccion({ tipo: 'quitar', proveedor: p })}>
                  <Icono nombre="papelera" tam={18} /> Quitar
                </button>
              )}
            </>
          )}
        </Can>
      </div>
      {errorPlantilla && (
        <p role="alert" className="campo-error">
          {errorPlantilla}
        </p>
      )}
    </li>
  )
}

/** Suma otro proveedor a la cotización (mientras no esté adjudicada). */
function AgregarProveedor({ cotizacion: c }) {
  const [error, setError] = useState('')
  const agregar = useMutacion({
    mutationFn: (proveedor) => api.post(`/compras/cotizaciones/${c.id}/proveedores/`, { proveedor }).then((r) => r.data),
    invalidar: [['compras']],
    exito: 'Proveedor agregado.',
    avisarError: false,
  })
  const llena = c.proveedores.length >= MAX_PROVEEDORES
  return (
    <div className="cotiz-agregar">
      <BuscadorAsincrono
        clave="proveedores-cotizacion-ficha"
        url="/mantenimiento/proveedores/"
        parametros={{ estado: 'ACTIVO' }}
        etiqueta="Agregar proveedor"
        placeholder={llena ? 'Llegaste al máximo de proveedores' : 'Busca por razón social o RUC…'}
        icono="handshake"
        disabled={agregar.isPending || llena}
        onElegir={(p) => {
          setError('')
          if (c.proveedores.some((x) => x.proveedor === p.id)) return setError(`${p.nombre} ya está en esta cotización.`)
          agregar.mutate(p.id, { onError: (e) => setError(Object.values(erroresDeCampo(e)).join(' ') || mensajeDeError(e)) })
        }}
        mostrar={(p) => (
          <>
            <strong>{p.nombre}</strong>
            <span className="sub-texto">
              {p.tipo_documento} {p.numero_documento}
            </span>
          </>
        )}
      />
      {error && (
        <p role="alert" className="campo-error">
          {error}
        </p>
      )}
    </div>
  )
}

/** Quitar a un proveedor que todavía no respondió. */
export function useQuitarProveedor(cotizacionId) {
  return useMutacion({
    mutationFn: (respuesta) => api.post(`/compras/cotizaciones/${cotizacionId}/quitar-proveedor/`, { respuesta }).then((r) => r.data),
    invalidar: [['compras']],
    exito: 'Proveedor quitado.',
  })
}

/** Sección «Proveedores»: cada uno con su estado y acciones, y el buscador para sumar más. */
export default function ProveedoresCotizacion({ cotizacion: c, onAccion }) {
  const acciones = accionesDe(c.estado)
  return (
    <>
      <Can permiso={CREAR}>{acciones.responder && <AgregarProveedor cotizacion={c} />}</Can>
      {c.proveedores.length === 0 ? (
        <p className="estado-vacio">Esta cotización todavía no tiene proveedores. Agrega los que quieras consultar.</p>
      ) : (
        <ul className="cotiz-proveedores">
          {c.proveedores.map((p) => (
            <TarjetaProveedor key={p.respuesta} cotizacion={c} proveedor={p} comparativo={c.comparativo.proveedores} abiertas={acciones.responder} onAccion={onAccion} />
          ))}
        </ul>
      )}
    </>
  )
}
