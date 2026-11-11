import { useState } from 'react'
import { useParams } from 'react-router-dom'
import BotonVolver from '../../../shared/components/BotonVolver'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import TomaAcciones from '../components/TomaAcciones'
import TomaAvance from '../components/TomaAvance'
import TomaEscaner from '../components/TomaEscaner'
import TomaHojaConteo from '../components/TomaHojaConteo'
import TomaResultado from '../components/TomaResultado'
import TomaTurnos from '../components/TomaTurnos'
import { useAvanceToma, useRegistroConteo, useToma } from '../hooks/useToma'
import { fechaCorta } from '../inventario'
import { ESTADOS_TOMA, fechaHora, numeroToma, puedeContarEn } from '../tomas'
import '../inventario.css'
import '../tomas.css'

/** Mensaje de lo que significa el estado actual de la toma (y lo que falta para avanzar). */
function AvisoEstado({ toma, puedeAprobar }) {
  if (toma.estado === 'BORRADOR') {
    return (
      <p className="modal-aviso" role="status">
        Esta toma todavía no se abrió: no se congeló ningún stock. Al abrirla se guarda el stock y el costo de cada producto
        {toma.alcance === 'CATEGORIAS' ? ' de las categorías elegidas' : ' del almacén'} y recién entonces se puede contar.
        {toma.productos_excluidos?.length > 0 && ` Se dejan fuera ${toma.productos_excluidos.length} producto(s) que elegiste excluir.`}
      </p>
    )
  }
  if (toma.estado === 'CERRADA') {
    return (
      <p className="modal-aviso" role="status">
        El conteo está cerrado ({fechaHora(toma.cerrada_en)}). La toma espera su aprobación: el Kardex solo se ajusta cuando se aprueba.{puedeAprobar ? ' Revise las diferencias y apruebe para generar el ajuste.' : ''}
      </p>
    )
  }
  if (toma.estado === 'APROBADA') {
    return (
      <p className="modal-aviso" role="status">
        Toma aprobada el {fechaHora(toma.aprobada_en)}. El ajuste se registró en el Kardex con fecha {fechaCorta(toma.fecha_ajuste)}
        {toma.movimientos?.length ? ` (${toma.movimientos.map((m) => `${m.tipo === 'ENTRADA' ? 'entrada' : 'salida'} ${numeroToma(m.numero)}`).join(', ')})` : ' (no hubo diferencias que ajustar)'}.
        {toma.nota_aprobacion ? ` Nota: ${toma.nota_aprobacion}` : ''}
      </p>
    )
  }
  if (toma.estado === 'ANULADA') {
    return (
      <p className="modal-aviso" role="status">
        Toma anulada el {fechaHora(toma.anulada_en)}. Motivo: {toma.motivo_anulacion || '—'}
      </p>
    )
  }
  return null
}

/** Una toma de inventario: su estado, el avance, el conteo (con lector o por hoja) y el cierre. */
export default function TomaFichaPage() {
  const { id } = useParams()
  const { tiene } = usePermisos()
  const [turno, setTurno] = useState('')
  const [categoria, setCategoria] = useState('')
  const registro = useRegistroConteo(id)

  const consulta = useToma(id)
  const toma = consulta.data
  const conDetalle = Boolean(toma) && toma.estado !== 'BORRADOR'
  const avance = useAvanceToma(id, { enabled: conDetalle })

  const puedeGestionar = tiene('INVENTARIO.TOMAS.GESTIONAR')
  const puedeAprobar = tiene('INVENTARIO.TOMAS.APROBAR')
  const puedeContar = tiene('INVENTARIO.TOMAS.CONTAR')
  const puedeExportar = puedeAprobar && tiene('INVENTARIO.EXPORTAR')
  const contando = Boolean(toma) && puedeContar && puedeContarEn(toma.estado)
  const estado = toma && (ESTADOS_TOMA[toma.estado] ?? { texto: toma.estado_nombre, tono: 'gris' })

  return (
    <main className="listado">
      <BotonVolver ruta="/almacen/tomas" texto="Tomas de inventario" />
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(toma)}>
        {toma && (
          <>
            <header className="toma-cabecera">
              <div>
                <h1>
                  Toma de inventario {numeroToma(toma.numero)} · {toma.almacen_nombre}
                </h1>
                <p className="celda-suave">
                  {toma.alcance === 'TODO' ? 'Todo el almacén' : `${toma.categorias.length} categoría(s)`}
                  {toma.fecha_corte ? ` · stock al ${fechaHora(toma.fecha_corte)}` : ''}
                  {toma.observacion ? ` · ${toma.observacion}` : ''}
                </p>
              </div>
              <span className="toma-etiquetas">
                <span className="pildora" data-tono={estado.tono}>
                  {estado.texto}
                </span>
                {toma.conteo_ciego && (
                  <span className="pildora" data-tono="gris">
                    Conteo a ciegas
                  </span>
                )}
              </span>
            </header>

            <TomaAcciones toma={toma} avance={avance.data} puedeGestionar={puedeGestionar} puedeAprobar={puedeAprobar} />
            <AvisoEstado toma={toma} puedeAprobar={puedeAprobar} />

            {conDetalle && (
              <>
                <div className="toma-lateral">
                  {avance.isLoading && <p aria-busy="true">Cargando el avance…</p>}
                  {avance.data && <TomaAvance avance={avance.data} onCategoria={(c) => setCategoria(String(c))} />}
                  {contando && <TomaTurnos tomaId={id} turnoActivo={turno} onTurno={setTurno} />}
                </div>
                {avance.data?.resultado && <TomaResultado toma={toma} resultado={avance.data.resultado} puedeDescargar={puedeExportar} />}
                {contando && <TomaEscaner toma={toma} turno={turno} registro={registro} />}
                <TomaHojaConteo toma={toma} verResultado={Boolean(avance.data?.resultado)} categorias={avance.data?.por_categoria ?? []} categoria={categoria} onCategoria={setCategoria} puedeContar={puedeContar} turno={turno} registro={registro} />
              </>
            )}
          </>
        )}
      </EstadoConsulta>

      {registro.cero && (
        <ConfirmarModal titulo="Confirmar conteo en 0" mensaje={registro.cero.mensaje} textoConfirmar="Sí, no hay ninguno" onConfirmar={registro.confirmarCero} onCerrar={registro.cancelarCero} />
      )}
    </main>
  )
}
