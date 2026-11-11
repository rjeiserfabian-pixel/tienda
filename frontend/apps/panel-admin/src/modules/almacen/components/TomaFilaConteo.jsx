import { memo, useState } from 'react'
import { cantidad, paraServidor } from '../inventario'
import { ESTADOS_FISICOS, revisarCantidad, soles } from '../tomas'
import '../tomas.css'

/** Cantidad del servidor (texto «9.000») → lo que se escribe en el campo («9»). */
const paraCampo = (valor) => (valor === null || valor === undefined || valor === '' ? '' : String(Number(valor)))

/**
 * Una fila de la hoja de conteo. Se puede contar con Enter. Guarda un conteo nuevo, o solo la nota
 * si es lo único que cambió. En un reconteo el campo arranca vacío: no se «confirma» lo anterior,
 * se vuelve a contar.
 */
function TomaFilaConteo({ fila, verSistema, editable, conAccion, conAjuste, enReconteo, turno, registrar, guardarNota }) {
  const contado = fila.cantidad_contada !== null && fila.cantidad_contada !== undefined
  const inicial = enReconteo && fila.requiere_reconteo ? '' : paraCampo(fila.cantidad_contada)
  const [valor, setValor] = useState(inicial)
  const [estadoFisico, setEstadoFisico] = useState(fila.estado_fisico)
  const [nota, setNota] = useState(fila.nota ?? '')
  const [error, setError] = useState('')
  const [enviando, setEnviando] = useState(false)

  const cambioCantidad = valor.trim() !== inicial
  const cambioEstado = estadoFisico !== fila.estado_fisico
  const cambioNota = nota.trim() !== (fila.nota ?? '')
  const soloNota = contado && cambioNota && !cambioCantidad && !cambioEstado
  const hayQueContar = valor.trim() !== '' && (cambioCantidad || cambioEstado || !contado || (enReconteo && fila.requiere_reconteo))
  const puedeGuardar = !enviando && (soloNota || hayQueContar)

  const alTerminar = { alExito: () => setEnviando(false), alError: (mensaje) => { setEnviando(false); if (mensaje) setError(mensaje) } }

  const guardar = () => {
    if (!puedeGuardar) return
    setError('')
    if (soloNota) {
      setEnviando(true)
      return guardarNota({ producto: fila.producto, nota: nota.trim() }, alTerminar)
    }
    const problema = revisarCantidad(valor, fila.admite_decimales)
    if (problema) return setError(problema)
    setEnviando(true)
    registrar(
      {
        producto: fila.producto,
        cantidad: paraServidor(valor),
        estado_fisico: estadoFisico,
        ...(nota.trim() ? { nota: nota.trim() } : {}),
        ...(turno ? { turno: Number(turno) } : {}),
      },
      alTerminar,
    )
  }

  const diferencia = verSistema && fila.diferencia !== undefined && fila.diferencia !== null ? Number(fila.diferencia) : null

  return (
    <tr className={fila.requiere_reconteo ? 'toma-fila-recontar' : undefined}>
      <td>
        <strong>{fila.producto_nombre}</strong>
        <span className="sub-texto">
          {fila.producto_codigo}
          {fila.codigo_barras ? ` · ${fila.codigo_barras}` : ''} · {fila.unidad}
        </span>
        <span className="toma-etiquetas">
          {fila.requiere_reconteo && (
            <span className="pildora" data-tono="naranja">
              Recontar
            </span>
          )}
          {fila.numero_conteos > 1 && (
            <span className="pildora" data-tono="gris">
              {fila.numero_conteos} conteos
            </span>
          )}
        </span>
      </td>
      {verSistema && (
        <>
          <td className="num">{cantidad(fila.stock_sistema)}</td>
          <td className={`num ${diferencia === null ? '' : diferencia < 0 ? 'toma-falta' : diferencia > 0 ? 'toma-sobra' : ''}`}>{diferencia === null ? '—' : cantidad(diferencia)}</td>
        </>
      )}
      <td className="toma-celda-conteo">
        {editable ? (
          <input
            className="toma-input-cantidad"
            inputMode="decimal"
            autoComplete="off"
            aria-label={`Cantidad contada de ${fila.producto_nombre}`}
            aria-invalid={Boolean(error)}
            placeholder={contado && !enReconteo ? '' : '—'}
            value={valor}
            disabled={enviando}
            onChange={(e) => setValor(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), guardar())}
          />
        ) : (
          <strong className="num">{contado ? cantidad(fila.cantidad_contada) : '—'}</strong>
        )}
        {error && (
          <small role="alert" className="campo-error">
            {error}
          </small>
        )}
      </td>
      {conAjuste && (
        <td className="num">
          {fila.diferencia_ajuste === null || fila.diferencia_ajuste === undefined ? '—' : cantidad(fila.diferencia_ajuste)}
          {fila.importe_ajuste ? <span className="sub-texto">{soles(fila.importe_ajuste)}</span> : null}
        </td>
      )}
      <td>
        {editable ? (
          <select className="toma-select" aria-label={`Estado físico de ${fila.producto_nombre}`} value={estadoFisico} disabled={enviando} onChange={(e) => setEstadoFisico(e.target.value)}>
            {Object.entries(ESTADOS_FISICOS).map(([v, texto]) => (
              <option key={v} value={v}>
                {texto}
              </option>
            ))}
          </select>
        ) : (
          ESTADOS_FISICOS[fila.estado_fisico]
        )}
      </td>
      <td>
        {editable ? (
          <input
            className="toma-input-nota"
            maxLength={250}
            aria-label={`Nota de ${fila.producto_nombre}`}
            placeholder="Nota (opcional)"
            value={nota}
            disabled={enviando}
            onChange={(e) => setNota(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), guardar())}
          />
        ) : (
          <span className="celda-suave">{fila.nota || '—'}</span>
        )}
      </td>
      {conAccion && (
        <td className="centrado">
          {editable ? (
            <button type="button" className={contado ? undefined : 'primario'} disabled={!puedeGuardar} onClick={guardar}>
              {enviando ? 'Guardando…' : soloNota ? 'Guardar nota' : contado ? 'Recontar' : 'Contar'}
            </button>
          ) : (
            <span className="celda-suave">—</span>
          )}
        </td>
      )}
    </tr>
  )
}

export default memo(TomaFilaConteo)
