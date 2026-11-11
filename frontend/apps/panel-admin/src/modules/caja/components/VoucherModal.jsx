import { useQuery } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaCorta } from '../../almacen/inventario'
import { pesoLegible, validarVoucher } from '../caja'

/**
 * Vouchers de un movimiento (foto del depósito, recibo, boleta). Se ven y se descargan con la sesión
 * iniciada: el archivo no tiene enlace público. Las fotos se guardan sin datos del celular (ubicación).
 */
export default function VoucherModal({ movimiento, puedeSubir, onCerrar }) {
  const entrada = useRef(null)
  const [error, setError] = useState('')
  const lista = useQuery({
    queryKey: ['caja', 'adjuntos', movimiento.id],
    queryFn: ({ signal }) => api.get('/caja/adjuntos/', { params: { movimiento: movimiento.id }, signal }).then((r) => r.data.results),
  })
  const adjuntos = lista.data ?? []
  const vigente = movimiento.estado === 'EMITIDO'

  const subir = useMutacion({
    mutationFn: (archivo) => {
      const cuerpo = new FormData()
      cuerpo.append('movimiento', movimiento.id)
      cuerpo.append('archivo', archivo)
      return api.post('/caja/adjuntos/', cuerpo, { timeout: 60_000 }).then((r) => r.data)
    },
    invalidar: [['caja']],
    exito: 'Voucher guardado.',
    avisarError: false,
  })
  const quitar = useMutacion({
    mutationFn: (id) => api.delete(`/caja/adjuntos/${id}/`),
    invalidar: [['caja']],
    exito: 'Voucher quitado.',
    avisarError: false,
  })

  const elegir = (evento) => {
    const archivo = evento.target.files?.[0]
    evento.target.value = '' // permite elegir otra vez el mismo archivo
    const malo = validarVoucher(archivo)
    setError(malo)
    if (malo || subir.isPending) return
    subir.mutate(archivo, { onError: (e) => setError(mensajeDeError(e)) })
  }
  const ver = async (adjunto) => {
    setError('')
    try {
      const respuesta = await api.get(`/caja/adjuntos/${adjunto.id}/archivo/`, { responseType: 'blob' })
      const direccion = URL.createObjectURL(respuesta.data)
      window.open(direccion, '_blank', 'noopener')
      setTimeout(() => URL.revokeObjectURL(direccion), 60_000)
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  return (
    <Modal titulo="Vouchers" subtitulo={`Movimiento N° ${String(movimiento.numero).padStart(6, '0')} · ${movimiento.concepto_nombre}`} onCerrar={onCerrar} ancho={620}>
      <EstadoConsulta consulta={lista} hayDatos={Boolean(lista.data)}>
        {adjuntos.length === 0 ? (
          <p className="estado-vacio">Este movimiento no tiene vouchers. Guarda la foto del depósito o del recibo para tener el respaldo.</p>
        ) : (
          <ul className="voucher-lista">
            {adjuntos.map((a) => (
              <li key={a.id}>
                <span>{a.tipo_contenido === 'application/pdf' ? 'PDF' : 'Foto'}</span>
                <span className="celda-suave">
                  {a.nombre_original || 'Sin nombre'} · {pesoLegible(a.tamano)} · {a.subido_por_nombre}, {fechaCorta(a.creado_en.slice(0, 10))}
                </span>
                <button type="button" className="boton-cabecera" onClick={() => ver(a)}>
                  <Icono nombre="ojo" tam={17} /> Ver
                </button>
                {puedeSubir && vigente && (
                  <button type="button" className="accion-icono peligro-suave" aria-label="Quitar el voucher" title="Quitar" disabled={quitar.isPending} onClick={() => quitar.mutate(a.id, { onError: (e) => setError(mensajeDeError(e)) })}>
                    <Icono nombre="papelera" tam={18} />
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </EstadoConsulta>
      {puedeSubir && vigente && adjuntos.length < 5 && (
        <>
          <input ref={entrada} type="file" accept="image/jpeg,image/png,image/webp,application/pdf" hidden onChange={elegir} />
          <button type="button" className="primario boton-cabecera" disabled={subir.isPending} onClick={() => entrada.current?.click()}>
            <Icono nombre="camara" tam={18} /> {subir.isPending ? 'Guardando…' : 'Agregar foto o PDF'}
          </button>
          <p className="celda-suave">Hasta 5 por movimiento, de 5 MB cada uno.</p>
        </>
      )}
      {error && (
        <p role="alert" className="campo-error">
          {error}
        </p>
      )}
      <div className="modal-pie">
        <button type="button" onClick={onCerrar}>
          Cerrar
        </button>
      </div>
    </Modal>
  )
}
