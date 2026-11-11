import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { etiquetaPeriodo } from '../inventario'
import '../inventario.css'

/** Cierre mensual: un mes cerrado ya no admite movimientos, para que los libros no cambien. */
export default function CierreMensualModal({ onCerrar }) {
  const { empresaActivaId } = useEmpresas()
  const [accion, setAccion] = useState(null) // { tipo: 'cerrar' | 'reabrir', periodo }
  const [error, setError] = useState('')

  const consulta = useQuery({
    queryKey: ['periodos', empresaActivaId],
    queryFn: ({ signal }) => api.get('/inventario/periodos/', { params: { empresa: empresaActivaId }, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId),
  })
  const datos = consulta.data
  const ultimo = datos?.cerrados?.at(-1)

  const ejecutar = useMutacion({
    mutationFn: ({ tipo, periodo }) => api.post(`/inventario/periodos/${tipo}/`, { empresa: empresaActivaId, periodo }).then((r) => r.data),
    invalidar: [['periodos'], ['movimientos']],
    exito: 'Listo: el cierre mensual quedó actualizado.',
    alExito: () => setAccion(null),
    avisarError: false,
  })

  const confirmar = () => {
    setError('')
    ejecutar.mutate(accion, { onError: (e) => { setError(mensajeDeError(e)); setAccion(null) } })
  }

  return (
    <Modal titulo="Cierre mensual" subtitulo="Cierre cada mes cuando termine de revisarlo, en orden del más antiguo al más reciente." onCerrar={onCerrar} ancho={560}>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(datos)}>
        {datos && (
          <>
            <h3>Meses cerrados</h3>
            {datos.cerrados.length === 0 ? (
              <p className="celda-suave">Todavía no hay meses cerrados.</p>
            ) : (
              <ul className="periodos-lista">
                {datos.cerrados.map((p) => (
                  <li key={p} className="pildora" data-tono="gris">{etiquetaPeriodo(p)}</li>
                ))}
              </ul>
            )}
            {datos.proximo_a_cerrar ? (
              <p>
                Próximo mes por cerrar: <strong>{etiquetaPeriodo(datos.proximo_a_cerrar)}</strong>
              </p>
            ) : (
              <p className="celda-suave">No hay meses terminados pendientes de cierre.</p>
            )}
          </>
        )}
      </EstadoConsulta>
      {error && <p role="alert" className="campo-error">{error}</p>}
      <div className="modal-pie">
        <button type="button" onClick={onCerrar}>
          <Icono nombre="cerrar" tam={18} /> Cerrar ventana
        </button>
        {ultimo && (
          <button type="button" disabled={ejecutar.isPending} onClick={() => setAccion({ tipo: 'reabrir', periodo: ultimo })}>
            Reabrir {etiquetaPeriodo(ultimo)}
          </button>
        )}
        {datos?.proximo_a_cerrar && (
          <button type="button" className="primario" disabled={ejecutar.isPending} onClick={() => setAccion({ tipo: 'cerrar', periodo: datos.proximo_a_cerrar })}>
            Cerrar {etiquetaPeriodo(datos.proximo_a_cerrar)}
          </button>
        )}
      </div>
      {accion && (
        <ConfirmarModal
          titulo={accion.tipo === 'cerrar' ? 'Cerrar el mes' : 'Reabrir el mes'}
          mensaje={
            accion.tipo === 'cerrar'
              ? `Después de cerrar ${etiquetaPeriodo(accion.periodo)} no se podrán registrar ni anular movimientos con fecha de ese mes.`
              : `Se podrá volver a registrar movimientos con fecha de ${etiquetaPeriodo(accion.periodo)}. Queda constancia en la auditoría.`
          }
          textoConfirmar={accion.tipo === 'cerrar' ? 'Cerrar mes' : 'Reabrir mes'}
          enviando={ejecutar.isPending}
          onConfirmar={confirmar}
          onCerrar={() => setAccion(null)}
        />
      )}
    </Modal>
  )
}
