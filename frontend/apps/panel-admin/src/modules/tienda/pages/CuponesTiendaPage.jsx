import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../../core/api/client'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import Paginacion from '../../../shared/components/Paginacion'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import CarritoAbandonadoTarjeta from '../components/CarritoAbandonadoTarjeta'
import CuponModal from '../components/CuponModal'
import { ALCANCES, ESTADOS_CUPON, FILTROS_ESTADO, resumenDeCupon } from '../cupones'
import { fechaHora, soles } from '../ofertas'
import '../tienda.css'
import '../ofertas.css'
import '../cupones.css'

const CLAVE = ['tienda', 'cupones']
const TAMANO = 25

/** Los últimos usos de un cupón: quién, en qué pedido y cuánto se le descontó. */
function UsosModal({ cupon, onCerrar }) {
  const consulta = useQuery({
    queryKey: ['tienda', 'cupon-usos', cupon.id],
    queryFn: ({ signal }) => api.get(`/tienda/admin/cupones/${cupon.id}/usos/`, { signal }).then((r) => r.data),
  })
  const filas = consulta.data?.results ?? []
  return (
    <Modal titulo={`Usos del cupón ${cupon.codigo}`} subtitulo="Los últimos 50 pedidos que lo usaron." onCerrar={onCerrar} ancho={680}>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        {filas.length === 0 ? (
          <p className="celda-suave">Todavía nadie lo ha usado.</p>
        ) : (
          <div className="marco-tabla">
            <table className="tabla-datos">
              <thead>
                <tr>
                  <th>Pedido</th>
                  <th>Cliente</th>
                  <th className="num">Descuento</th>
                  <th>Estado</th>
                  <th>Fecha</th>
                </tr>
              </thead>
              <tbody>
                {filas.map((u) => (
                  <tr key={u.pedido}>
                    <td data-etiqueta="Pedido">{u.pedido}</td>
                    <td data-etiqueta="Cliente" className="col-texto">
                      {u.cliente}
                    </td>
                    <td data-etiqueta="Descuento" className="num">
                      {soles(u.monto)}
                    </td>
                    <td data-etiqueta="Estado">{u.estado_texto}</td>
                    <td data-etiqueta="Fecha">{fechaHora(u.fecha)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </EstadoConsulta>
    </Modal>
  )
}

/** Cupones de descuento de la tienda virtual. */
export default function CuponesTiendaPage() {
  const [estado, setEstado] = useState('')
  const [busqueda, setBusqueda] = useState('')
  const [pagina, setPagina] = useState(1)
  const [abierto, setAbierto] = useState(null) // {} = nuevo
  const [verUsos, setVerUsos] = useState(null)
  const [aEliminar, setAEliminar] = useState(null)
  const q = useDebounce(busqueda, 400)
  const consulta = useListado(CLAVE, '/tienda/admin/cupones/', { estado, q, page: pagina }, { refetchInterval: 60_000 })
  const filas = consulta.data?.results ?? []

  const eliminar = useMutacion({
    mutationFn: (c) => api.delete(`/tienda/admin/cupones/${c.id}/`),
    invalidar: [CLAVE],
    exito: 'Cupón eliminado.',
    alExito: () => setAEliminar(null),
  })
  const alternar = useMutacion({
    mutationFn: (c) => api.patch(`/tienda/admin/cupones/${c.id}/`, { activo: !c.activo }).then((r) => r.data),
    invalidar: [CLAVE],
  })

  return (
    <main className="listado tienda-pagina">
      <CabeceraListado
        icono="megaphone"
        titulo="Cupones"
        descripcion="Códigos de descuento para tus clientes. No se combinan con productos en oferta (salvo que el cupón lo permita) y nunca bajan un producto de su precio mínimo."
      />

      <CarritoAbandonadoTarjeta />

      <div className="ofertas-barra">
        <div className="tienda-segmentos" role="group" aria-label="Estado de los cupones">
          {FILTROS_ESTADO.map((f) => (
            <button
              key={f.valor || 'todos'}
              type="button"
              aria-pressed={estado === f.valor}
              onClick={() => {
                setEstado(f.valor)
                setPagina(1)
              }}
            >
              {f.texto}
            </button>
          ))}
        </div>
        <Buscador
          valor={busqueda}
          onCambio={(v) => {
            setBusqueda(v)
            setPagina(1)
          }}
          etiqueta="Buscar cupones"
          placeholder="Código o nombre…"
        />
        <button type="button" className="boton-cabecera primario" onClick={() => setAbierto({})}>
          <Icono nombre="agregar" tam={18} /> Nuevo cupón
        </button>
      </div>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Código</th>
                <th>Descuento</th>
                <th>Vigencia</th>
                <th className="num">Usos</th>
                <th className="num">Descontado</th>
                <th>Estado</th>
                <th>
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && (
                <FilaVacia columnas={7} icono="megaphone" titulo="Todavía no hay cupones" descripcion="Crea un cupón para que tus clientes tengan un código de descuento al comprar." />
              )}
              {filas.map((c) => {
                const e = ESTADOS_CUPON[c.estado] ?? { texto: c.estado, tono: 'gris' }
                return (
                  <tr key={c.id}>
                    <td data-etiqueta="Código" className="col-texto">
                      <b className="cupon-codigo">{c.codigo}</b>
                      {c.nombre && <span className="sub-texto">{c.nombre}</span>}
                    </td>
                    <td data-etiqueta="Descuento" className="col-texto">
                      {resumenDeCupon(c)}
                      <span className="sub-texto">
                        {ALCANCES[c.alcance]}
                        {Number(c.compra_minima) > 0 ? ` · desde ${soles(c.compra_minima)}` : ''}
                        {c.solo_primera_compra ? ' · primera compra' : ''}
                        {c.incluye_ofertas ? ' · incluye ofertas' : ''}
                      </span>
                    </td>
                    <td data-etiqueta="Vigencia">
                      {c.inicia_en ? fechaHora(c.inicia_en) : 'Desde ya'}
                      <span className="sub-texto">{c.termina_en ? `hasta ${fechaHora(c.termina_en)}` : 'sin fecha final'}</span>
                    </td>
                    <td data-etiqueta="Usos" className="num">
                      {c.usos}
                      {c.usos_maximos ? ` / ${c.usos_maximos}` : ''}
                      <span className="sub-texto">{c.usos_pagados} pagados</span>
                    </td>
                    <td data-etiqueta="Descontado" className="num">
                      {soles(c.descontado)}
                    </td>
                    <td data-etiqueta="Estado">
                      <span className="pildora" data-tono={e.tono}>
                        {e.texto}
                      </span>
                    </td>
                    <td data-etiqueta="Acciones" className="celda-acciones">
                      <div className="envios-acciones">
                        <button type="button" className="icono-boton" aria-label={`Ver los usos del cupón ${c.codigo}`} onClick={() => setVerUsos(c)}>
                          <Icono nombre="checklist" tam={18} />
                        </button>
                        <button type="button" className="icono-boton" aria-label={`${c.activo ? 'Pausar' : 'Reanudar'} el cupón ${c.codigo}`} disabled={alternar.isPending} onClick={() => alternar.mutate(c)}>
                          <Icono nombre={c.activo ? 'apagar' : 'reactivar'} tam={18} />
                        </button>
                        <button type="button" className="icono-boton" aria-label={`Editar el cupón ${c.codigo}`} onClick={() => setAbierto(c)}>
                          <Icono nombre="lapiz" tam={18} />
                        </button>
                        <button type="button" className="icono-boton" aria-label={`Eliminar el cupón ${c.codigo}`} onClick={() => setAEliminar(c)}>
                          <Icono nombre="papelera" tam={18} />
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <Paginacion pagina={pagina} tamano={TAMANO} total={consulta.data?.count ?? 0} onPagina={setPagina} onTamano={() => {}} />
      </EstadoConsulta>

      {abierto && <CuponModal cupon={abierto.id ? abierto : null} onCerrar={() => setAbierto(null)} />}
      {verUsos && <UsosModal cupon={verUsos} onCerrar={() => setVerUsos(null)} />}
      {aEliminar && (
        <ConfirmarModal
          titulo="¿Eliminar el cupón?"
          mensaje={`Se borra el cupón ${aEliminar.codigo}. Si ya se usó en algún pedido no se puede borrar: en ese caso, pausa el cupón.`}
          textoConfirmar="Eliminar"
          enviando={eliminar.isPending}
          onConfirmar={() => eliminar.mutate(aEliminar)}
          onCerrar={() => setAEliminar(null)}
        />
      )}
    </main>
  )
}
