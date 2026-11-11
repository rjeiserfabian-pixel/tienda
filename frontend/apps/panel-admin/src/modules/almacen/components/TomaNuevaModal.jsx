import { useState } from 'react'
import { api, codigoDeError, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Interruptor from '../../../shared/components/Interruptor'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useOpciones } from '../hooks/useOpciones'
import { paraServidor } from '../inventario'
import '../inventario.css'
import '../tomas.css'
import SelectorProducto from './SelectorProducto'

const MAX_EXCLUIDOS = 200
const ALCANCES = [
  ['TODO', 'Todo el almacén'],
  ['CATEGORIAS', 'Algunas categorías'],
]

/** Revisa el formulario antes de enviarlo; devuelve `{ campo: mensaje }` (vacío si está bien). */
function revisar(f) {
  const e = {}
  if (!f.almacen) e.almacen = 'Elija el almacén que se va a contar.'
  if (f.alcance === 'CATEGORIAS' && f.categorias.length === 0) e.categorias = 'Elija al menos una categoría.'
  const monto = paraServidor(f.umbralMonto)
  if (!/^\d+(\.\d{1,2})?$/.test(monto)) e.umbralMonto = 'Un monto en soles, con hasta 2 decimales.'
  const porcentaje = paraServidor(f.umbralPorcentaje)
  if (!/^\d+(\.\d{1,2})?$/.test(porcentaje) || Number(porcentaje) > 100) e.umbralPorcentaje = 'Un porcentaje de 0 a 100.'
  return e
}

/**
 * Crea una toma de inventario físico de UN almacén. Queda en borrador: todavía no congela nada.
 * El conteo a ciegas viene activado: quien cuenta no ve lo que dice el sistema.
 */
export default function TomaNuevaModal({ onCerrar, onCreada }) {
  const { empresaActivaId } = useEmpresas()
  const [f, setF] = useState({
    almacen: '',
    alcance: 'TODO',
    categorias: [],
    excluidos: [],
    ciego: true,
    umbralMonto: '500',
    umbralPorcentaje: '10',
    observacion: '',
  })
  const [errores, setErrores] = useState({})
  const [general, setGeneral] = useState('')

  const almacenes = useOpciones('/mantenimiento/almacenes/', { empresa: empresaActivaId }, { enabled: Boolean(empresaActivaId) })
  const categorias = useOpciones('/mantenimiento/categorias/', {}, { enabled: f.alcance === 'CATEGORIAS' })
  const opciones = almacenes.data ?? []
  const almacen = f.almacen || (opciones.length === 1 ? String(opciones[0].id) : '')

  const crear = useMutacion({
    mutationFn: (cuerpo) => api.post('/inventario/tomas/', cuerpo).then((r) => r.data),
    invalidar: [['tomas']],
    exito: 'Toma creada. Revísala y ábrela cuando vayas a empezar el conteo.',
    alExito: (toma) => onCreada(toma),
    avisarError: false,
  })

  const poner = (campo, valor) => setF((previo) => ({ ...previo, [campo]: valor }))
  const alternarCategoria = (id) => poner('categorias', f.categorias.includes(id) ? f.categorias.filter((c) => c !== id) : [...f.categorias, id])
  const excluir = (producto) => {
    if (producto && !f.excluidos.some((p) => p.id === producto.id)) poner('excluidos', [...f.excluidos, producto])
  }

  const enviar = (evento) => {
    evento.preventDefault()
    if (crear.isPending) return
    const revision = revisar({ ...f, almacen })
    setErrores(revision)
    setGeneral('')
    if (Object.keys(revision).length) return
    crear.mutate(
      {
        empresa: empresaActivaId,
        almacen: Number(almacen),
        alcance: f.alcance,
        categorias: f.alcance === 'CATEGORIAS' ? f.categorias : [],
        excluir_productos: f.excluidos.map((p) => p.id),
        conteo_ciego: f.ciego,
        umbral_monto: paraServidor(f.umbralMonto),
        umbral_porcentaje: paraServidor(f.umbralPorcentaje),
        observacion: f.observacion.trim(),
      },
      {
        onError: (error) => {
          const delServidor = erroresDeCampo(error)
          setErrores(delServidor)
          const conCampos = Object.keys(delServidor).length > 0 && codigoDeError(error) !== 'toma_vigente_existente'
          setGeneral(conCampos ? 'Revise los datos marcados.' : mensajeDeError(error))
        },
      },
    )
  }

  return (
    <Modal titulo="Nueva toma de inventario" subtitulo="Se cuenta un almacén a la vez. Queda en borrador: el stock se congela recién al abrirla." onCerrar={onCerrar} ancho={720}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={crear.isPending} className="toma-fieldset">
          <Campo etiqueta="Almacén a contar" tipo="select" requerido error={errores.almacen}>
            {(p) => (
              <select {...p} value={almacen} onChange={(e) => poner('almacen', e.target.value)}>
                <option value="">Elegir almacén</option>
                {opciones.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.nombre}
                  </option>
                ))}
              </select>
            )}
          </Campo>

          <div className="segmentos" role="radiogroup" aria-label="Qué se cuenta">
            {ALCANCES.map(([valor, texto]) => (
              <button key={valor} type="button" role="radio" aria-checked={f.alcance === valor} className={f.alcance === valor ? 'activo' : undefined} onClick={() => poner('alcance', valor)}>
                {texto}
              </button>
            ))}
          </div>

          {f.alcance === 'TODO' && <p className="campo-ayuda">Se contarán todos los productos que tengan stock en este almacén. No hace falta elegirlos uno por uno.</p>}

          {f.alcance === 'CATEGORIAS' && (
            <div className="toma-categorias" role="group" aria-label="Categorías a contar">
              {categorias.isLoading && <p className="celda-suave">Cargando categorías…</p>}
              {categorias.isError && (
                <p role="alert" className="campo-error">
                  No se pudieron cargar las categorías.
                </p>
              )}
              {(categorias.data ?? []).map((c) => (
                <label key={c.id} className={f.categorias.includes(c.id) ? 'marcada' : undefined}>
                  <input type="checkbox" checked={f.categorias.includes(c.id)} onChange={() => alternarCategoria(c.id)} />
                  {c.nombre}
                </label>
              ))}
              {errores.categorias && (
                <p role="alert" className="campo-error">
                  {errores.categorias}
                </p>
              )}
            </div>
          )}

          <details className="toma-excluir">
            <summary>
              Dejar algunos productos fuera de la toma (casi nunca hace falta)
              {f.excluidos.length > 0 && <strong> · {f.excluidos.length} elegido(s)</strong>}
            </summary>
            <SelectorProducto etiqueta="Productos que NO se van a contar" valor={null} disabled={f.excluidos.length >= MAX_EXCLUIDOS} onElegir={excluir} />
            <p className="campo-ayuda">Solo para lo que no debe contarse como propio, por ejemplo mercadería de terceros o en consignación. Si lo dejas vacío, se cuenta todo lo que tenga stock. Los productos que elijas aquí NO aparecerán en el conteo.</p>
            {f.excluidos.length > 0 && (
              <ul className="toma-chips" aria-label="Productos que se dejan fuera">
                {f.excluidos.map((p) => (
                  <li key={p.id}>
                    {p.nombre}
                    <button type="button" aria-label={`Volver a incluir ${p.nombre}`} onClick={() => poner('excluidos', f.excluidos.filter((x) => x.id !== p.id))}>
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </details>

          <Interruptor
            activo={f.ciego}
            onCambio={(valor) => poner('ciego', valor)}
            texto="Conteo a ciegas (recomendado)"
            descripcion="Quien cuenta no ve el stock del sistema ni las diferencias; solo quien aprueba las ve."
          />

          <div className="fila-campos">
            <Campo etiqueta="Pedir reconteo desde (S/)" error={errores.umbralMonto} ayuda="Diferencia valorizada al costo.">
              {(p) => <input {...p} inputMode="decimal" value={f.umbralMonto} onChange={(e) => poner('umbralMonto', e.target.value)} />}
            </Campo>
            <Campo etiqueta="…o desde (%)" error={errores.umbralPorcentaje} ayuda="Sobre el stock del sistema.">
              {(p) => <input {...p} inputMode="decimal" value={f.umbralPorcentaje} onChange={(e) => poner('umbralPorcentaje', e.target.value)} />}
            </Campo>
          </div>

          <Campo etiqueta="Observación" error={errores.observacion} contador={{ actual: f.observacion.length, max: 250 }}>
            {(p) => <input {...p} maxLength={250} placeholder="Opcional. Ej. Inventario de fin de año" value={f.observacion} onChange={(e) => poner('observacion', e.target.value)} />}
          </Campo>
        </fieldset>

        {general && (
          <p role="alert" className="campo-error">
            {general}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={crear.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={crear.isPending || almacenes.isLoading}>
            {crear.isPending ? 'Creando…' : 'Crear toma'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
