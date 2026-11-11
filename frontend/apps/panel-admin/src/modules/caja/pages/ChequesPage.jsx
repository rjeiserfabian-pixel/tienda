import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../../../core/api/client'
import Can from '../../../shared/components/Can'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import { fechaCorta } from '../../almacen/inventario'
import AccionChequeModal from '../components/AccionChequeModal'
import RegistrarChequeModal from '../components/RegistrarChequeModal'
import { dinero } from '../caja'
import { ACCIONES, accionesDeCheque, diasParaVencer, ESTADOS_CHEQUE, situacionDeVencimiento, TIPOS_CHEQUE } from '../cheques'
import '../../almacen/inventario.css'
import '../caja.css'

const TIPOS_PESTANA = [
  ['', 'Todos'],
  ['RECIBIDO', 'Recibidos'],
  ['EMITIDO', 'Girados'],
]

/** Textos del vencimiento de un cheque recibido pendiente. */
function Vence({ cheque }) {
  const situacion = situacionDeVencimiento(cheque)
  if (!situacion) return cheque.tipo === 'RECIBIDO' && ['EN_CARTERA', 'DEPOSITADO'].includes(cheque.estado) ? fechaCorta(cheque.vence) : '—'
  const dias = diasParaVencer(cheque.vence)
  return (
    <span className={`cheque-vence ${situacion}`}>
      {fechaCorta(cheque.vence)}
      <small>{situacion === 'vencido' ? `Venció hace ${Math.abs(dias)} d` : dias === 0 ? 'Vence hoy' : `Vence en ${dias} d`}</small>
    </span>
  )
}

/** Cheques recibidos de clientes y girados a proveedores: su estado, su vencimiento y su cobro. */
export default function ChequesPage() {
  const { empresaActivaId } = useEmpresas()
  const { tiene } = usePermisos()
  const [params] = useSearchParams()
  const [busqueda, setBusqueda] = useState('')
  const [filtros, setFiltros] = useState(() => ({
    tipo: TIPOS_PESTANA.some(([v]) => v === params.get('tipo')) ? params.get('tipo') : '',
    estado: Object.keys(ESTADOS_CHEQUE).includes(params.get('estado')) ? params.get('estado') : '',
    vencidos: params.get('vencidos') === '1' ? '1' : '',
    desde: '',
    hasta: '',
  }))
  const [filtrosAbiertos, setFiltrosAbiertos] = useState(() => Boolean(filtros.estado || filtros.vencidos))
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [dialogo, setDialogo] = useState(null) // { tipo: 'nuevo' } o { tipo: 'accion', accion, cheque }
  const q = useDebounce(busqueda, 400)
  const puedeGestionar = tiene('CAJA.CHEQUES.GESTIONAR')

  const saldos = useQuery({
    queryKey: ['caja', 'saldos', empresaActivaId],
    queryFn: ({ signal }) => api.get('/caja/saldos/', { params: { empresa: empresaActivaId }, signal }).then((r) => r.data.cuentas),
    enabled: Boolean(empresaActivaId),
  })
  const consulta = useListado(['caja', 'cheques'], '/caja/cheques/', { empresa: empresaActivaId, q, ...filtros, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []
  const hayFiltros = Boolean(filtros.estado || filtros.vencidos || filtros.desde || filtros.hasta)
  const rangoInvalido = filtros.desde && filtros.hasta && filtros.desde > filtros.hasta

  const poner = (campo, valor) => {
    setFiltros((previos) => ({ ...previos, [campo]: valor }))
    setPagina(1)
  }
  const cerrar = () => setDialogo(null)

  return (
    <main className="listado">
      <CabeceraListado icono="documento" titulo="Cheques" descripcion="Los cheques que recibes de clientes y los que giras a proveedores: en qué estado están y cuáles ya vencen o siguen sin cobrar.">
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar cheques"
          placeholder="Número, banco o nombre…"
        />
        <button type="button" className={`boton-cabecera${filtrosAbiertos || hayFiltros ? ' activo' : ''}`} aria-expanded={filtrosAbiertos} onClick={() => setFiltrosAbiertos((v) => !v)}>
          <Icono nombre="filtro" tam={19} /> Filtros{hayFiltros ? ' •' : ''}
        </button>
        <Can permiso="CAJA.CHEQUES.GESTIONAR">
          <button type="button" className="primario boton-cabecera" onClick={() => setDialogo({ tipo: 'nuevo' })}>
            <Icono nombre="agregar" tam={20} /> Registrar cheque
          </button>
        </Can>
      </CabeceraListado>

      <div className="segmentos" role="group" aria-label="Tipo de cheque">
        {TIPOS_PESTANA.map(([valor, texto]) => (
          <button key={valor || 'todos'} type="button" aria-pressed={filtros.tipo === valor} className={filtros.tipo === valor ? 'activo' : undefined} onClick={() => poner('tipo', valor)}>
            {texto}
          </button>
        ))}
      </div>

      {filtrosAbiertos && (
        <div className="filtros-panel" role="search">
          <label>
            Estado
            <select value={filtros.estado} onChange={(e) => poner('estado', e.target.value)}>
              <option value="">Todos</option>
              {Object.entries(ESTADOS_CHEQUE).map(([valor, e]) => (
                <option key={valor} value={valor}>
                  {e.texto}
                </option>
              ))}
            </select>
          </label>
          <label>
            Emitidos desde
            <input type="date" value={filtros.desde} onChange={(e) => poner('desde', e.target.value)} />
          </label>
          <label>
            Hasta
            <input type="date" value={filtros.hasta} onChange={(e) => poner('hasta', e.target.value)} />
          </label>
          <label className="filtro-casilla">
            <input type="checkbox" checked={filtros.vencidos === '1'} onChange={(e) => poner('vencidos', e.target.checked ? '1' : '')} />
            Solo recibidos vencidos
          </label>
          {hayFiltros && (
            <button
              type="button"
              onClick={() => {
                setFiltros((previos) => ({ ...previos, estado: '', vencidos: '', desde: '', hasta: '' }))
                setPagina(1)
              }}
            >
              Limpiar filtros
            </button>
          )}
          {rangoInvalido && (
            <p role="alert" className="campo-error">
              «Desde» no puede ser posterior a «Hasta».
            </p>
          )}
        </div>
      )}

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Tipo</th>
                <th>Cheque</th>
                <th>Quién / a quién</th>
                <th className="num">Importe</th>
                <th>Fecha de pago</th>
                <th>Vence</th>
                <th>Estado</th>
                <th className="centrado">
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={8} icono="documento" titulo="No hay cheques" descripcion="Registra un cheque recibido o girado para controlar su cobro." />}
              {filas.map((c) => {
                const e = ESTADOS_CHEQUE[c.estado] ?? { texto: c.estado_nombre, tono: 'gris' }
                const acciones = puedeGestionar ? accionesDeCheque(c) : []
                return (
                  <tr key={c.id}>
                    <td>{TIPOS_CHEQUE[c.tipo]?.texto ?? c.tipo_nombre}</td>
                    <td>
                      <strong>{c.numero}</strong>
                      <span className="sub-texto">
                        {c.banco} · emitido el {fechaCorta(c.fecha_emision)}
                      </span>
                    </td>
                    <td>
                      {c.tercero}
                      {c.motivo && <span className="sub-texto">{c.motivo}</span>}
                    </td>
                    <td className="num">{dinero(c.importe, c.moneda)}</td>
                    <td>{c.fecha_pago ? fechaCorta(c.fecha_pago) : '—'}</td>
                    <td>
                      <Vence cheque={c} />
                    </td>
                    <td>
                      <span className="pildora" data-tono={e.tono}>
                        {e.texto}
                      </span>
                    </td>
                    <td className="centrado">
                      {acciones.map((a) => (
                        <button key={a} type="button" className="accion-icono" aria-label={`${ACCIONES[a].boton} el cheque ${c.numero}`} title={a === 'cobrar' && c.tipo === 'EMITIDO' ? 'Marcar cobrado' : ACCIONES[a].boton} onClick={() => setDialogo({ tipo: 'accion', accion: a, cheque: c })}>
                          <Icono nombre={ACCIONES[a].icono} tam={19} />
                        </button>
                      ))}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </EstadoConsulta>

      <Paginacion
        pagina={pagina}
        tamano={tamano}
        total={consulta.data?.count ?? 0}
        onPagina={setPagina}
        onTamano={(t) => {
          setTamano(t)
          setPagina(1)
        }}
      />

      {dialogo?.tipo === 'nuevo' && <RegistrarChequeModal cuentas={saldos.data ?? []} onCerrar={cerrar} />}
      {dialogo?.tipo === 'accion' && <AccionChequeModal cheque={dialogo.cheque} accion={dialogo.accion} cuentas={saldos.data ?? []} onCerrar={cerrar} />}
    </main>
  )
}
