import { useState } from 'react'
import { codigoDeError, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { useAccionToma } from '../hooks/useToma'
import { cantidad } from '../inventario'
import { numeroToma } from '../tomas'
import '../tomas.css'
import TomaAprobarModal from './TomaAprobarModal'
import TomaImportarModal from './TomaImportarModal'

/** Cuadro de confirmación de una acción de la toma (no peligrosa): explica qué pasará. */
function ConfirmarAccion({ titulo, subtitulo, textoConfirmar, textoEnviando, enviando, error, onConfirmar, onCerrar, children }) {
  return (
    <Modal titulo={titulo} subtitulo={subtitulo} onCerrar={onCerrar} ancho={520}>
      {children}
      {error && (
        <p role="alert" className="campo-error">
          {error}
        </p>
      )}
      <div className="modal-pie">
        <button type="button" onClick={onCerrar} disabled={enviando}>
          Cancelar
        </button>
        <button type="button" className="primario" onClick={onConfirmar} disabled={enviando}>
          {enviando ? textoEnviando : textoConfirmar}
        </button>
      </div>
    </Modal>
  )
}

function AbrirModal({ toma, onCerrar }) {
  const [error, setError] = useState('')
  const abrir = useAccionToma(toma.id, 'abrir', { exito: 'Toma abierta: el stock quedó congelado.', alExito: onCerrar })
  return (
    <ConfirmarAccion
      titulo="Abrir la toma"
      subtitulo={`${numeroToma(toma.numero)} · ${toma.almacen_nombre}`}
      textoConfirmar="Abrir y congelar el stock"
      textoEnviando="Abriendo…"
      enviando={abrir.isPending}
      error={error}
      onCerrar={onCerrar}
      onConfirmar={() => !abrir.isPending && abrir.mutate(undefined, { onError: (e) => setError(mensajeDeError(e)) })}
    >
      <p>
        Al abrirla, el sistema guarda el stock y el costo de cada producto del almacén tal como están ahora. Desde ese momento se cuenta contra esa foto; las ventas y compras que sigan ocurriendo no la cambian y se tienen en cuenta al aprobar.
      </p>
      {toma.conteo_ciego && <p className="celda-suave">Es un conteo a ciegas: quien cuente no verá el stock del sistema.</p>}
    </ConfirmarAccion>
  )
}

function ReconteoModal({ toma, avance, onCerrar }) {
  const [error, setError] = useState('')
  const reconteo = useAccionToma(toma.id, 'reconteo', { exito: 'Reconteo iniciado.', alExito: onCerrar })
  const n = avance?.por_recontar ?? 0
  return (
    <ConfirmarAccion
      titulo="Iniciar el reconteo"
      subtitulo={`${numeroToma(toma.numero)} · ${toma.almacen_nombre}`}
      textoConfirmar="Iniciar reconteo"
      textoEnviando="Iniciando…"
      enviando={reconteo.isPending}
      error={error}
      onCerrar={onCerrar}
      onConfirmar={() => !reconteo.isPending && reconteo.mutate(undefined, { onError: (e) => setError(mensajeDeError(e)) })}
    >
      <p>
        {n ? `${cantidad(n)} producto(s)` : 'Los productos'} con una diferencia importante se vuelven a contar. Mientras dure el reconteo solo se pueden contar esos productos.
      </p>
    </ConfirmarAccion>
  )
}

function CerrarModal({ toma, onCerrar }) {
  const [error, setError] = useState('')
  const [pendientes, setPendientes] = useState(0)
  const cerrar = useAccionToma(toma.id, 'cerrar', { exito: 'Toma cerrada. Queda lista para aprobarse.', alExito: onCerrar })

  const intentar = (confirmar) => {
    if (cerrar.isPending) return
    setError('')
    cerrar.mutate(
      { confirmar_pendientes: confirmar },
      {
        onError: (e) => {
          const detalle = e?.response?.data?.error?.detalle
          if (codigoDeError(e) === 'toma_incompleta' && detalle?.pendientes) setPendientes(detalle.pendientes)
          setError(mensajeDeError(e))
        },
      },
    )
  }

  return (
    <ConfirmarAccion
      titulo="Cerrar la toma"
      subtitulo={`${numeroToma(toma.numero)} · ${toma.almacen_nombre}`}
      textoConfirmar={pendientes ? 'Dejarlos fuera y cerrar' : 'Cerrar la toma'}
      textoEnviando="Cerrando…"
      enviando={cerrar.isPending}
      error={error}
      onCerrar={onCerrar}
      onConfirmar={() => intentar(pendientes > 0)}
    >
      <p>Al cerrar ya no se puede contar. Queda lista para que quien aprueba revise las diferencias y genere el ajuste.</p>
      <p className="celda-suave">Para cerrar, no debe quedar nada por recontar y las diferencias importantes deben tener su nota.</p>
    </ConfirmarAccion>
  )
}

function AnularModal({ toma, onCerrar }) {
  const [motivo, setMotivo] = useState('')
  const [error, setError] = useState('')
  const anular = useAccionToma(toma.id, 'anular', { exito: 'Toma anulada.', alExito: onCerrar })
  const aprobada = toma.estado === 'APROBADA'

  const enviar = (evento) => {
    evento.preventDefault()
    if (anular.isPending) return
    if (!motivo.trim()) return setError('Escriba el motivo de la anulación.')
    setError('')
    anular.mutate({ motivo: motivo.trim() }, { onError: (e) => setError(erroresDeCampo(e).motivo || mensajeDeError(e)) })
  }

  return (
    <Modal titulo="Anular la toma" subtitulo={`${numeroToma(toma.numero)} · ${toma.almacen_nombre}`} onCerrar={onCerrar} ancho={520}>
      <form onSubmit={enviar} noValidate>
        <p>
          {aprobada
            ? 'La toma ya ajustó el Kardex: se registrarán los movimientos inversos (extornos). Si parte de la mercadería sobrante ya se vendió, no se podrá anular.'
            : 'No se borra nada: los conteos quedan como rastro y el almacén queda libre para una nueva toma.'}
        </p>
        <Campo etiqueta="Motivo" requerido error={error} contador={{ actual: motivo.length, max: 250 }}>
          {(p) => <textarea {...p} rows={3} maxLength={250} value={motivo} disabled={anular.isPending} placeholder="Ej. Se eligió mal el almacén" onChange={(e) => setMotivo(e.target.value)} />}
        </Campo>
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={anular.isPending}>
            Cancelar
          </button>
          <button type="submit" className="peligro" disabled={anular.isPending}>
            {anular.isPending ? 'Anulando…' : 'Anular toma'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

/**
 * Botones del ciclo de la toma según su estado y los permisos de quien la mira.
 * Abrir y cerrar son de quien gestiona; anular una toma ya aprobada exige además poder aprobar.
 */
export default function TomaAcciones({ toma, avance, puedeGestionar, puedeAprobar }) {
  const [dialogo, setDialogo] = useState(null)
  const cerrarDialogo = () => setDialogo(null)
  const enConteo = toma.estado === 'EN_CONTEO' || toma.estado === 'EN_RECONTEO'
  const puedeAnular = toma.estado !== 'ANULADA' && (toma.estado === 'APROBADA' ? puedeAprobar : puedeGestionar)
  const porAprobar = puedeAprobar && toma.estado === 'CERRADA'
  const puedeImportar = puedeGestionar && (toma.estado === 'ABIERTA' || toma.estado === 'EN_CONTEO')
  const hayAlgo = porAprobar || puedeImportar || (puedeGestionar && (toma.estado === 'BORRADOR' || enConteo))

  if (!hayAlgo && !puedeAnular) return null
  return (
    <div className="toma-acciones">
      {puedeGestionar && toma.estado === 'BORRADOR' && (
        <button type="button" className="primario" onClick={() => setDialogo('abrir')}>
          <Icono nombre="reactivar" tam={18} /> Abrir toma
        </button>
      )}
      {puedeImportar && (
        <button type="button" onClick={() => setDialogo('importar')}>
          <Icono nombre="importar" tam={18} /> Importar conteo (Excel)
        </button>
      )}
      {puedeGestionar && toma.estado === 'EN_CONTEO' && (avance?.por_recontar ?? 0) > 0 && (
        <button type="button" onClick={() => setDialogo('reconteo')}>
          <Icono nombre="ordenar" tam={18} /> Iniciar reconteo ({cantidad(avance.por_recontar)})
        </button>
      )}
      {puedeGestionar && enConteo && (
        <button type="button" className="primario" onClick={() => setDialogo('cerrar')}>
          <Icono nombre="lock" tam={18} /> Cerrar toma
        </button>
      )}
      {porAprobar && (
        <button type="button" className="primario" onClick={() => setDialogo('aprobar')}>
          <Icono nombre="checklist" tam={18} /> Revisar y aprobar
        </button>
      )}
      {puedeAnular && (
        <button type="button" className="peligro" onClick={() => setDialogo('anular')}>
          <Icono nombre="cerrar" tam={18} /> Anular toma
        </button>
      )}
      {dialogo === 'abrir' && <AbrirModal toma={toma} onCerrar={cerrarDialogo} />}
      {dialogo === 'reconteo' && <ReconteoModal toma={toma} avance={avance} onCerrar={cerrarDialogo} />}
      {dialogo === 'cerrar' && <CerrarModal toma={toma} onCerrar={cerrarDialogo} />}
      {dialogo === 'anular' && <AnularModal toma={toma} onCerrar={cerrarDialogo} />}
      {dialogo === 'aprobar' && <TomaAprobarModal toma={toma} onCerrar={cerrarDialogo} />}
      {dialogo === 'importar' && <TomaImportarModal toma={toma} onCerrar={cerrarDialogo} />}
    </div>
  )
}
