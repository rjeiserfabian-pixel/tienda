import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Can from '../../../shared/components/Can'
import Campo from '../../../shared/components/Campo'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { dinero } from '../../compras/compras'
import '../../compras/compras.css'

const SIN_DATOS = []
const pct = (p) => `${String(Number(p)).replace('.', ',')} %`
const vigencia = (x) => (x.vigente_desde || x.vigente_hasta ? `${x.vigente_desde ?? 'siempre'} → ${x.vigente_hasta ?? 'sin fin'}` : 'Siempre')

function SelectorVendedor({ valor, onCambio, vendedores }) {
  return (
    <Campo etiqueta="¿Para qué vendedor?" tipo="select">
      {(props) => (
        <select {...props} value={valor} onChange={onCambio}>
          <option value="">Todos los vendedores</option>
          {vendedores.map((v) => (
            <option key={v.id} value={v.id}>
              {v.nombre}
            </option>
          ))}
        </select>
      )}
    </Campo>
  )
}

// ---------------------------------------------------------------------------------------------
// Escalas
// ---------------------------------------------------------------------------------------------
function EscalaModal({ escala, vendedores, onCerrar }) {
  const [f, setF] = useState(() =>
    escala
      ? { nombre: escala.nombre, vendedor_id: escala.vendedor ?? '', vigente_desde: escala.vigente_desde ?? '', vigente_hasta: escala.vigente_hasta ?? '', tramos: escala.tramos.map((t) => ({ desde: String(Number(t.desde)), porcentaje: String(Number(t.porcentaje)).replace('.', ',') })) }
      : { nombre: '', vendedor_id: '', vigente_desde: '', vigente_hasta: '', tramos: [{ desde: '0', porcentaje: '' }, { desde: '', porcentaje: '' }] },
  )
  const [error, setError] = useState('')
  const guardar = useMutacion({
    mutationFn: (cuerpo) => (escala ? api.patch(`/comisiones/escalas/${escala.id}/`, cuerpo) : api.post('/comisiones/escalas/', cuerpo)).then((r) => r.data),
    invalidar: [['comisiones']],
    exito: escala ? 'Escala guardada.' : 'Escala creada.',
    alExito: onCerrar,
    avisarError: false,
  })
  const campo = (nombre) => (e) => setF((p) => ({ ...p, [nombre]: e.target.value }))
  const tramo = (i, nombre) => (e) => setF((p) => ({ ...p, tramos: p.tramos.map((t, j) => (j === i ? { ...t, [nombre]: e.target.value } : t)) }))
  const enviar = (evento) => {
    evento.preventDefault()
    setError('')
    guardar.mutate(
      { nombre: f.nombre, vendedor_id: f.vendedor_id || null, vigente_desde: f.vigente_desde || null, vigente_hasta: f.vigente_hasta || null, tramos: f.tramos.filter((t) => t.desde !== '' || t.porcentaje !== '') },
      { onError: (e) => setError(Object.values(erroresDeCampo(e))[0] ?? mensajeDeError(e)) },
    )
  }
  return (
    <Modal titulo={escala ? 'Editar escala' : 'Nueva escala mensual'} onCerrar={onCerrar} ancho={600}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={guardar.isPending}>
          <Campo etiqueta="Nombre" requerido>
            {(props) => <input {...props} maxLength={80} value={f.nombre} onChange={campo('nombre')} />}
          </Campo>
          <SelectorVendedor valor={f.vendedor_id} onCambio={campo('vendedor_id')} vendedores={vendedores} />
          <p className="celda-suave">Según lo que venda en el mes (sin IGV), gana un porcentaje. El porcentaje del tramo alcanzado vale para todo lo vendido en el mes que no tenga una regla de producto, marca o categoría.</p>
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Desde (S/ vendidos en el mes)</th>
                <th>Comisión (%)</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {f.tramos.map((t, i) => (
                <tr key={i}>
                  <td>
                    <input aria-label={`Desde, tramo ${i + 1}`} inputMode="decimal" value={t.desde} onChange={tramo(i, 'desde')} disabled={i === 0} />
                  </td>
                  <td>
                    <input aria-label={`Porcentaje, tramo ${i + 1}`} inputMode="decimal" value={t.porcentaje} onChange={tramo(i, 'porcentaje')} />
                  </td>
                  <td>
                    {i > 0 && (
                      <button type="button" onClick={() => setF((p) => ({ ...p, tramos: p.tramos.filter((_, j) => j !== i) }))}>
                        Quitar
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button type="button" onClick={() => setF((p) => ({ ...p, tramos: [...p.tramos, { desde: '', porcentaje: '' }] }))} disabled={f.tramos.length >= 10}>
            Agregar tramo
          </button>
          <Campo etiqueta="Vale desde (opcional)">{(props) => <input {...props} type="date" value={f.vigente_desde} onChange={campo('vigente_desde')} />}</Campo>
          <Campo etiqueta="Vale hasta (opcional)">{(props) => <input {...props} type="date" value={f.vigente_hasta} onChange={campo('vigente_hasta')} />}</Campo>
        </fieldset>
        {error && (
          <p role="alert" className="campo-error">
            {error}
          </p>
        )}
        <div className="acciones">
          <button type="button" onClick={onCerrar}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={guardar.isPending}>
            {guardar.isPending ? 'Guardando…' : 'Guardar'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

function Escalas({ vendedores }) {
  const [modal, setModal] = useState(null)
  const [borrando, setBorrando] = useState(null)
  const consulta = useQuery({ queryKey: ['comisiones', 'escalas'], queryFn: ({ signal }) => api.get('/comisiones/escalas/', { signal }).then((r) => r.data.results) })
  const pausar = useMutacion({ mutationFn: (e) => api.patch(`/comisiones/escalas/${e.id}/`, { activa: !e.activa }).then((r) => r.data), invalidar: [['comisiones']], exito: 'Listo.' })
  const borrar = useMutacion({ mutationFn: (e) => api.delete(`/comisiones/escalas/${e.id}/`), invalidar: [['comisiones']], exito: 'Escala eliminada.', alExito: () => setBorrando(null) })
  const filas = consulta.data ?? SIN_DATOS
  return (
    <section aria-labelledby="titulo-escalas">
      <h2 id="titulo-escalas">Escalas mensuales</h2>
      <p className="celda-suave">Cuanto más vende el vendedor en el mes, mayor es su porcentaje. El tramo alcanzado se aplica a todo lo vendido del mes, no solo al excedente.</p>
      <Can permiso="COMISIONES.GESTIONAR">
        <button type="button" className="primario" onClick={() => setModal('nueva')}>
          Nueva escala
        </button>
      </Can>
      {filas.length === 0 && <p className="celda-suave">Aún no hay escalas: todos ganan el porcentaje de sus reglas.</p>}
      {filas.map((e) => (
        <article key={e.id} className="tarjeta-seccion">
          <h3>
            {e.nombre} <span className="pildora" data-tono={e.activa ? 'verde' : 'gris'}>{e.activa ? 'Activa' : 'Pausada'}</span>
          </h3>
          <p className="celda-suave">
            {e.vendedor_nombre} · {vigencia(e)}
          </p>
          <ul>
            {e.tramos.map((t, i) => (
              <li key={t.desde}>
                {i === 0 ? 'Desde la primera venta' : `Desde ${dinero(t.desde, 'PEN')}`}: <strong>{pct(t.porcentaje)}</strong>
              </li>
            ))}
          </ul>
          <Can permiso="COMISIONES.GESTIONAR">
            <span className="acciones-fila">
              <button type="button" onClick={() => setModal(e)}>
                Editar
              </button>
              <button type="button" disabled={pausar.isPending} onClick={() => pausar.mutate(e)}>
                {e.activa ? 'Pausar' : 'Activar'}
              </button>
              <button type="button" onClick={() => setBorrando(e)}>
                Eliminar
              </button>
            </span>
          </Can>
        </article>
      ))}
      {modal && <EscalaModal escala={modal === 'nueva' ? null : modal} vendedores={vendedores} onCerrar={() => setModal(null)} />}
      {borrando && <ConfirmarModal titulo="Eliminar la escala" mensaje={`¿Eliminar la escala «${borrando.nombre}»?`} textoConfirmar="Eliminar" enviando={borrar.isPending} onConfirmar={() => borrar.mutate(borrando)} onCerrar={() => setBorrando(null)} />}
    </section>
  )
}

// ---------------------------------------------------------------------------------------------
// Metas con bono
// ---------------------------------------------------------------------------------------------
function MetaModal({ meta, vendedores, onCerrar }) {
  const [f, setF] = useState(() => (meta ? { nombre: meta.nombre, vendedor_id: meta.vendedor ?? '', meta: String(Number(meta.meta)), bono: String(Number(meta.bono)), vigente_desde: meta.vigente_desde ?? '', vigente_hasta: meta.vigente_hasta ?? '' } : { nombre: '', vendedor_id: '', meta: '', bono: '', vigente_desde: '', vigente_hasta: '' }))
  const [error, setError] = useState('')
  const guardar = useMutacion({
    mutationFn: (cuerpo) => (meta ? api.patch(`/comisiones/metas/${meta.id}/`, cuerpo) : api.post('/comisiones/metas/', cuerpo)).then((r) => r.data),
    invalidar: [['comisiones']],
    exito: meta ? 'Meta guardada.' : 'Meta creada.',
    alExito: onCerrar,
    avisarError: false,
  })
  const campo = (nombre) => (e) => setF((p) => ({ ...p, [nombre]: e.target.value }))
  const enviar = (evento) => {
    evento.preventDefault()
    setError('')
    guardar.mutate({ ...f, vendedor_id: f.vendedor_id || null, vigente_desde: f.vigente_desde || null, vigente_hasta: f.vigente_hasta || null }, { onError: (e) => setError(Object.values(erroresDeCampo(e))[0] ?? mensajeDeError(e)) })
  }
  return (
    <Modal titulo={meta ? 'Editar meta' : 'Nueva meta con bono'} onCerrar={onCerrar} ancho={520}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={guardar.isPending}>
          <Campo etiqueta="Nombre" requerido>{(props) => <input {...props} maxLength={80} value={f.nombre} onChange={campo('nombre')} />}</Campo>
          <SelectorVendedor valor={f.vendedor_id} onCambio={campo('vendedor_id')} vendedores={vendedores} />
          <Campo etiqueta="Meta del mes (S/ vendidos, sin IGV)" requerido>{(props) => <input {...props} inputMode="decimal" value={f.meta} onChange={campo('meta')} />}</Campo>
          <Campo etiqueta="Bono fijo al cumplirla (S/)" requerido>{(props) => <input {...props} inputMode="decimal" value={f.bono} onChange={campo('bono')} />}</Campo>
          <Campo etiqueta="Vale desde (opcional)">{(props) => <input {...props} type="date" value={f.vigente_desde} onChange={campo('vigente_desde')} />}</Campo>
          <Campo etiqueta="Vale hasta (opcional)">{(props) => <input {...props} type="date" value={f.vigente_hasta} onChange={campo('vigente_hasta')} />}</Campo>
        </fieldset>
        {error && (
          <p role="alert" className="campo-error">
            {error}
          </p>
        )}
        <div className="acciones">
          <button type="button" onClick={onCerrar}>Cancelar</button>
          <button type="submit" className="primario" disabled={guardar.isPending}>
            {guardar.isPending ? 'Guardando…' : 'Guardar'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

function Metas({ vendedores }) {
  const [modal, setModal] = useState(null)
  const [borrando, setBorrando] = useState(null)
  const consulta = useQuery({ queryKey: ['comisiones', 'metas'], queryFn: ({ signal }) => api.get('/comisiones/metas/', { signal }).then((r) => r.data.results) })
  const pausar = useMutacion({ mutationFn: (m) => api.patch(`/comisiones/metas/${m.id}/`, { activa: !m.activa }).then((r) => r.data), invalidar: [['comisiones']], exito: 'Listo.' })
  const borrar = useMutacion({ mutationFn: (m) => api.delete(`/comisiones/metas/${m.id}/`), invalidar: [['comisiones']], exito: 'Meta eliminada.', alExito: () => setBorrando(null) })
  const filas = consulta.data ?? SIN_DATOS
  return (
    <section aria-labelledby="titulo-metas">
      <h2 id="titulo-metas">Metas con bono</h2>
      <p className="celda-suave">Un premio fijo: si el vendedor vende al menos la meta en el mes, gana el bono. Se otorga al cerrar el mes.</p>
      <Can permiso="COMISIONES.GESTIONAR">
        <button type="button" className="primario" onClick={() => setModal('nueva')}>
          Nueva meta
        </button>
      </Can>
      {filas.length === 0 && <p className="celda-suave">Aún no hay metas.</p>}
      {filas.length > 0 && (
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Meta</th>
                <th>Vendedor</th>
                <th className="num">Vender al menos</th>
                <th className="num">Bono</th>
                <th>Estado</th>
                <th className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filas.map((m) => (
                <tr key={m.id}>
                  <td className="col-texto">
                    <strong>{m.nombre}</strong>
                    <span className="sub-texto">{vigencia(m)} · otorgada {m.otorgados} {m.otorgados === 1 ? 'vez' : 'veces'}</span>
                  </td>
                  <td>{m.vendedor_nombre}</td>
                  <td className="num">{dinero(m.meta, 'PEN')}</td>
                  <td className="num"><strong>{dinero(m.bono, 'PEN')}</strong></td>
                  <td><span className="pildora" data-tono={m.activa ? 'verde' : 'gris'}>{m.activa ? 'Activa' : 'Pausada'}</span></td>
                  <td className="centrado">
                    <Can permiso="COMISIONES.GESTIONAR">
                      <span className="acciones-fila">
                        <button type="button" onClick={() => setModal(m)}>Editar</button>
                        <button type="button" disabled={pausar.isPending} onClick={() => pausar.mutate(m)}>{m.activa ? 'Pausar' : 'Activar'}</button>
                        <button type="button" onClick={() => setBorrando(m)}>Eliminar</button>
                      </span>
                    </Can>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {modal && <MetaModal meta={modal === 'nueva' ? null : modal} vendedores={vendedores} onCerrar={() => setModal(null)} />}
      {borrando && <ConfirmarModal titulo="Eliminar la meta" mensaje={`¿Eliminar la meta «${borrando.nombre}»?`} textoConfirmar="Eliminar" enviando={borrar.isPending} onConfirmar={() => borrar.mutate(borrando)} onCerrar={() => setBorrando(null)} />}
    </section>
  )
}

// ---------------------------------------------------------------------------------------------
// Avance del mes
// ---------------------------------------------------------------------------------------------
function Avance() {
  const hoy = new Date().toLocaleDateString('en-CA').slice(0, 7)
  const [mes, setMes] = useState(hoy)
  const consulta = useQuery({ queryKey: ['comisiones', 'avance', mes], queryFn: ({ signal }) => api.get('/comisiones/avance/', { params: { mes }, signal }).then((r) => r.data), enabled: Boolean(mes) })
  const filas = consulta.data?.results ?? SIN_DATOS
  return (
    <section aria-labelledby="titulo-avance">
      <h2 id="titulo-avance">Avance del mes</h2>
      <Campo etiqueta="Mes">{(props) => <input {...props} type="month" value={mes} max={hoy} onChange={(e) => setMes(e.target.value)} />}</Campo>
      <div className="marco-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th>Vendedor</th>
              <th className="num">Vendido en el mes</th>
              <th>Escala</th>
              <th>Metas</th>
            </tr>
          </thead>
          <tbody>
            {filas.length === 0 && (
              <tr>
                <td colSpan={4} className="celda-suave">{consulta.isLoading ? 'Cargando…' : 'No hay vendedores.'}</td>
              </tr>
            )}
            {filas.map((v) => (
              <tr key={v.vendedor}>
                <td className="col-texto"><strong>{v.vendedor_nombre}</strong></td>
                <td className="num">{dinero(v.ventas, 'PEN')}</td>
                <td className="col-texto">
                  {v.escala ? (
                    <>
                      <strong>{v.escala.porcentaje ? pct(v.escala.porcentaje) : '—'}</strong>
                      {v.escala.siguiente && <span className="sub-texto">Le faltan {dinero(v.escala.siguiente.falta, 'PEN')} para {pct(v.escala.siguiente.porcentaje)}</span>}
                    </>
                  ) : (
                    <span className="celda-suave">Sin escala</span>
                  )}
                </td>
                <td className="col-texto">
                  {v.metas.length === 0 && <span className="celda-suave">Sin metas</span>}
                  {v.metas.map((m) => (
                    <span key={m.id} className="sub-texto">
                      {m.nombre}: {m.cumplida ? `cumplida (bono ${dinero(m.bono, 'PEN')})` : `faltan ${dinero(m.falta, 'PEN')}`}
                    </span>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="celda-suave">El tramo de la escala y los bonos se fijan al cerrar el mes; aquí ves cómo va hasta hoy.</p>
    </section>
  )
}

export { Avance, Escalas, Metas }
