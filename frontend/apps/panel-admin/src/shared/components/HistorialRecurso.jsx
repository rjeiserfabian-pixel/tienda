import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../core/api/client'
import { fechaHora } from '../utils/fechas'
import Can from './Can'
import Cambios from './Cambios'
import EstadoConsulta from './EstadoConsulta'
import Modal from './Modal'
import './historial.css'

const MAXIMO = 50

/** Quién hizo qué con este registro y cuándo, del más reciente al más antiguo (con el antes y el después). */
function HistorialModal({ recursos, titulo, onCerrar }) {
  const clave = recursos.map(([t, i]) => `${t}:${i}`).join(',')
  const consulta = useQuery({
    queryKey: ['auditoria', 'historial', clave],
    queryFn: ({ signal }) => api.get('/auditoria/eventos/', { params: { recursos: clave, page_size: MAXIMO }, signal }).then((r) => r.data),
  })
  const filas = consulta.data?.results ?? []
  return (
    <Modal titulo="Historial de cambios" subtitulo={titulo} onCerrar={onCerrar} ancho={720}>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        {filas.length === 0 ? (
          <p className="celda-suave">Todavía no hay movimientos registrados de este registro.</p>
        ) : (
          <ol className="historial-lista">
            {filas.map((e) => (
              <li key={e.id}>
                <time dateTime={e.creado_en}>{fechaHora(e.creado_en)}</time> <strong>{e.usuario ?? 'Sistema'}</strong>: {e.resumen || e.accion}
                <Cambios detalle={e.detalle} />
              </li>
            ))}
          </ol>
        )}
        {consulta.data?.count > MAXIMO && <p className="celda-suave">Se muestran los {MAXIMO} más recientes de {consulta.data.count}. El resto está en Seguridad → Auditoría.</p>}
      </EstadoConsulta>
    </Modal>
  )
}

/**
 * Botón «Historial» para la ficha de un registro: abre quién lo creó, lo cambió o lo anuló, con el antes
 * y el después. Solo lo ven quienes pueden consultar la auditoría. `tipo` es el `recurso_tipo` con que el
 * sistema registra ese dato (por ejemplo «producto» o «comprobante_venta»); para un dato con varios
 * registros (una venta y sus comprobantes) se pasa `recursos={[['venta', 3], ['comprobante_venta', 7]]}`.
 */
export default function HistorialRecurso({ tipo, id, recursos, titulo = '' }) {
  const [abierto, setAbierto] = useState(false)
  const lista = recursos ?? (id === undefined || id === null ? [] : [[tipo, id]])
  if (lista.length === 0) return null
  return (
    <Can permiso="SEGURIDAD.AUDITORIA.VER">
      <button type="button" onClick={() => setAbierto(true)}>
        Historial
      </button>
      {abierto && <HistorialModal recursos={lista} titulo={titulo} onCerrar={() => setAbierto(false)} />}
    </Can>
  )
}
