import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Can from '../../../shared/components/Can'
import Campo from '../../../shared/components/Campo'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { fechaCorta } from '../../almacen/inventario'
import { Avance, Escalas, Metas } from '../components/EscalasYMetas'
import Liquidacion from '../components/Liquidacion'
import '../../almacen/inventario.css'
import '../../compras/compras.css'

const ALCANCES = { GENERAL: 'Cualquier venta', CATEGORIA: 'Una categoría', MARCA: 'Una marca', PRODUCTO: 'Un producto' }
const SIN_DATOS = []
const VISTAS = { reglas: 'Reglas', escalas: 'Escalas', metas: 'Metas y bonos', avance: 'Avance del mes', liquidacion: 'Cierre mensual' }
const VACIA = { alcance: 'GENERAL', categoria: '', marca: '', producto: '', vendedor_id: '', porcentaje: '', vigente_desde: '', vigente_hasta: '', nota: '' }

const porcentajeTexto = (p) => `${String(Number(p)).replace('.', ',')} %`

/** Busca un producto por nombre o código para elegirlo en una regla. */
function BuscarProducto({ valor, nombre, onElegir }) {
  const [texto, setTexto] = useState('')
  const q = useDebounce(texto, 400)
  const consulta = useQuery({
    queryKey: ['comisiones', 'productos', q],
    queryFn: ({ signal }) => api.get('/mantenimiento/productos/', { params: { q, page_size: 8, estado: 'ACTIVO', tipo: 'BIEN' }, signal }).then((r) => r.data.results),
    enabled: q.trim().length >= 2,
  })
  return (
    <div>
      {valor && (
        <p>
          Producto elegido: <strong>{nombre}</strong>{' '}
          <button type="button" onClick={() => onElegir(null)}>
            Cambiar
          </button>
        </p>
      )}
      {!valor && (
        <>
          <Campo etiqueta="Buscar el producto" requerido ayuda="Escribe el nombre o el código.">
            {(props) => <input {...props} value={texto} onChange={(e) => setTexto(e.target.value)} />}
          </Campo>
          <ul className="lista-simple">
            {(consulta.data ?? SIN_DATOS).map((p) => (
              <li key={p.id}>
                <button type="button" onClick={() => onElegir(p)}>
                  {p.nombre}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function ReglaModal({ regla, opciones, onCerrar }) {
  const [f, setF] = useState(() =>
    regla
      ? {
          alcance: regla.alcance,
          categoria: regla.categoria ?? '',
          marca: regla.marca ?? '',
          producto: regla.producto ?? '',
          vendedor_id: regla.vendedor ?? '',
          porcentaje: String(Number(regla.porcentaje)).replace('.', ','),
          vigente_desde: regla.vigente_desde ?? '',
          vigente_hasta: regla.vigente_hasta ?? '',
          nota: regla.nota ?? '',
        }
      : VACIA,
  )
  const [productoNombre, setProductoNombre] = useState(regla?.objetivo?.replace('Producto ', '') ?? '')
  const [error, setError] = useState('')
  const campo = (nombre) => (e) => setF((previo) => ({ ...previo, [nombre]: e.target.value }))
  const guardar = useMutacion({
    mutationFn: (cuerpo) => (regla ? api.patch(`/comisiones/reglas/${regla.id}/`, cuerpo) : api.post('/comisiones/reglas/', cuerpo)).then((r) => r.data),
    invalidar: [['comisiones']],
    exito: regla ? 'Regla guardada.' : 'Regla creada.',
    alExito: onCerrar,
    avisarError: false,
  })
  const enviar = (evento) => {
    evento.preventDefault()
    setError('')
    const cuerpo = {
      alcance: f.alcance,
      porcentaje: f.porcentaje,
      vendedor_id: f.vendedor_id || null,
      vigente_desde: f.vigente_desde || null,
      vigente_hasta: f.vigente_hasta || null,
      nota: f.nota,
      categoria: f.alcance === 'CATEGORIA' ? Number(f.categoria) || null : null,
      marca: f.alcance === 'MARCA' ? Number(f.marca) || null : null,
      producto: f.alcance === 'PRODUCTO' ? Number(f.producto) || null : null,
    }
    guardar.mutate(cuerpo, { onError: (e) => setError(Object.values(erroresDeCampo(e))[0] ?? mensajeDeError(e)) })
  }
  const lista = (nombre, items) => (
    <Campo etiqueta={nombre === 'categoria' ? 'Categoría' : 'Marca'} tipo="select" requerido>
      {(props) => (
        <select {...props} value={f[nombre]} onChange={campo(nombre)}>
          <option value="">Elige…</option>
          {items.map((x) => (
            <option key={x.id} value={x.id}>
              {x.nombre}
            </option>
          ))}
        </select>
      )}
    </Campo>
  )
  return (
    <Modal titulo={regla ? 'Editar regla de comisión' : 'Nueva regla de comisión'} onCerrar={onCerrar} ancho={560}>
      <form onSubmit={enviar} noValidate>
        <fieldset disabled={guardar.isPending}>
          <Campo etiqueta="¿A qué se aplica?" tipo="select" requerido>
            {(props) => (
              <select {...props} value={f.alcance} onChange={campo('alcance')}>
                {Object.entries(ALCANCES).map(([v, t]) => (
                  <option key={v} value={v}>
                    {t}
                  </option>
                ))}
              </select>
            )}
          </Campo>
          {f.alcance === 'CATEGORIA' && lista('categoria', opciones.categorias)}
          {f.alcance === 'MARCA' && lista('marca', opciones.marcas)}
          {f.alcance === 'PRODUCTO' && (
            <BuscarProducto
              valor={f.producto}
              nombre={productoNombre}
              onElegir={(p) => {
                setF((previo) => ({ ...previo, producto: p ? p.id : '' }))
                setProductoNombre(p ? p.nombre : '')
              }}
            />
          )}
          <Campo etiqueta="¿Para qué vendedor?" tipo="select">
            {(props) => (
              <select {...props} value={f.vendedor_id} onChange={campo('vendedor_id')}>
                <option value="">Todos los vendedores</option>
                {opciones.vendedores.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.nombre}
                  </option>
                ))}
              </select>
            )}
          </Campo>
          <Campo etiqueta="Porcentaje de comisión (%)" requerido ayuda="Sobre la venta sin IGV. Por ejemplo 2,5.">
            {(props) => <input {...props} inputMode="decimal" value={f.porcentaje} onChange={campo('porcentaje')} />}
          </Campo>
          <Campo etiqueta="Vale desde (opcional)">{(props) => <input {...props} type="date" value={f.vigente_desde} onChange={campo('vigente_desde')} />}</Campo>
          <Campo etiqueta="Vale hasta (opcional)">{(props) => <input {...props} type="date" value={f.vigente_hasta} onChange={campo('vigente_hasta')} />}</Campo>
          <Campo etiqueta="Nota (opcional)">{(props) => <input {...props} maxLength={120} value={f.nota} onChange={campo('nota')} />}</Campo>
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

/** «¿Qué porcentaje gana…?»: prueba cómo se aplican las reglas antes de que lleguen las ventas. */
function Simulador({ opciones }) {
  const [vendedor, setVendedor] = useState('')
  const [producto, setProducto] = useState(null)
  const consulta = useQuery({
    queryKey: ['comisiones', 'simular', vendedor, producto?.id],
    queryFn: ({ signal }) => api.get('/comisiones/reglas/simular/', { params: { producto: producto.id, vendedor }, signal }).then((r) => r.data),
    enabled: Boolean(producto),
  })
  return (
    <section className="tarjeta-seccion" aria-labelledby="titulo-simular">
      <h2 id="titulo-simular">¿Qué porcentaje gana…?</h2>
      <p className="celda-suave">Elige un producto y un vendedor para ver qué regla se aplicaría hoy.</p>
      <Campo etiqueta="Vendedor" tipo="select">
        {(props) => (
          <select {...props} value={vendedor} onChange={(e) => setVendedor(e.target.value)}>
            <option value="">Cualquiera</option>
            {opciones.vendedores.map((v) => (
              <option key={v.id} value={v.id}>
                {v.nombre}
              </option>
            ))}
          </select>
        )}
      </Campo>
      <BuscarProducto
        valor={producto?.id}
        nombre={producto?.nombre}
        onElegir={setProducto}
      />
      {producto && consulta.data && (
        <p>
          <strong>{porcentajeTexto(consulta.data.porcentaje)}</strong> — {consulta.data.texto}
        </p>
      )}
    </section>
  )
}

/** Reglas de comisión de los vendedores: quién gana qué porcentaje por vender qué. */
export default function ComisionesPage() {
  const [vista, setVista] = useState('reglas')
  const [modal, setModal] = useState(null) // null | 'nueva' | regla
  const [borrando, setBorrando] = useState(null)
  const reglas = useQuery({
    queryKey: ['comisiones', 'reglas'],
    queryFn: ({ signal }) => api.get('/comisiones/reglas/', { signal }).then((r) => r.data.results),
  })
  const opciones = useQuery({
    queryKey: ['comisiones', 'opciones'],
    queryFn: ({ signal }) => api.get('/comisiones/reglas/opciones/', { signal }).then((r) => r.data),
    staleTime: 60_000,
  })
  const pausar = useMutacion({
    mutationFn: (r) => api.patch(`/comisiones/reglas/${r.id}/`, { activa: !r.activa }).then((x) => x.data),
    invalidar: [['comisiones']],
    exito: 'Listo.',
  })
  const borrar = useMutacion({
    mutationFn: (r) => api.delete(`/comisiones/reglas/${r.id}/`),
    invalidar: [['comisiones']],
    exito: 'Regla eliminada.',
    alExito: () => setBorrando(null),
  })
  const filas = reglas.data ?? SIN_DATOS
  const op = opciones.data ?? { categorias: SIN_DATOS, marcas: SIN_DATOS, vendedores: SIN_DATOS }

  return (
    <main className="listado">
      <CabeceraListado icono="coins" titulo="Comisiones de vendedores" descripcion="Cuánto gana cada vendedor sobre la venta sin IGV. Gana la regla más específica: producto, luego marca, luego categoría y al final la general.">
        {vista === 'reglas' && (
          <Can permiso="COMISIONES.GESTIONAR">
            <button type="button" className="primario" onClick={() => setModal('nueva')}>
              Nueva regla
            </button>
          </Can>
        )}
      </CabeceraListado>

      <div className="segmentos" role="radiogroup" aria-label="Qué quieres ver">
        {Object.entries(VISTAS).map(([valor, texto]) => (
          <button key={valor} type="button" role="radio" aria-checked={vista === valor} className={vista === valor ? 'activo' : undefined} onClick={() => setVista(valor)}>
            {texto}
          </button>
        ))}
      </div>

      {vista === 'escalas' && <Escalas vendedores={op.vendedores} />}
      {vista === 'metas' && <Metas vendedores={op.vendedores} />}
      {vista === 'avance' && <Avance />}
      {vista === 'liquidacion' && <Liquidacion />}
      {vista === 'reglas' && (
        <>
      <EstadoConsulta consulta={reglas} hayDatos={Boolean(reglas.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Se aplica a</th>
                <th>Vendedor</th>
                <th className="num">Comisión</th>
                <th>Vigencia</th>
                <th>Estado</th>
                <th className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={6} icono="coins" titulo="Aún no hay reglas" descripcion="Sin reglas, las ventas no pagan comisión. Crea una regla general para empezar." />}
              {filas.map((r) => (
                <tr key={r.id}>
                  <td className="col-texto">
                    <strong>{r.objetivo}</strong>
                    {r.nota && <span className="sub-texto">{r.nota}</span>}
                  </td>
                  <td>{r.vendedor_nombre}</td>
                  <td className="num">
                    <strong>{porcentajeTexto(r.porcentaje)}</strong>
                  </td>
                  <td className="celda-suave">{r.vigente_desde || r.vigente_hasta ? `${r.vigente_desde ? fechaCorta(r.vigente_desde) : 'siempre'} → ${r.vigente_hasta ? fechaCorta(r.vigente_hasta) : 'sin fin'}` : 'Siempre'}</td>
                  <td>
                    <span className="pildora" data-tono={r.activa ? 'verde' : 'gris'}>
                      {r.activa ? 'Activa' : 'Pausada'}
                    </span>
                  </td>
                  <td className="centrado">
                    <Can permiso="COMISIONES.GESTIONAR">
                      <span className="acciones-fila">
                        <button type="button" onClick={() => setModal(r)}>
                          Editar
                        </button>
                        <button type="button" disabled={pausar.isPending} onClick={() => pausar.mutate(r)}>
                          {r.activa ? 'Pausar' : 'Activar'}
                        </button>
                        <button type="button" onClick={() => setBorrando(r)}>
                          Eliminar
                        </button>
                      </span>
                    </Can>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </EstadoConsulta>

      <Simulador opciones={op} />

        </>
      )}

      {modal && <ReglaModal regla={modal === 'nueva' ? null : modal} opciones={op} onCerrar={() => setModal(null)} />}
      {borrando && (
        <ConfirmarModal
          titulo="Eliminar la regla"
          mensaje={`¿Eliminar la regla «${borrando.objetivo}» (${porcentajeTexto(borrando.porcentaje)})? Las comisiones ya calculadas no cambian.`}
          textoConfirmar="Eliminar"
          enviando={borrar.isPending}
          onConfirmar={() => borrar.mutate(borrando)}
          onCerrar={() => setBorrando(null)}
        />
      )}
    </main>
  )
}
