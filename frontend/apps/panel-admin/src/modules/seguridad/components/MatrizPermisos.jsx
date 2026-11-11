import { useMemo, useState } from 'react'
import { api } from '../../../core/api/client'
import { Icono } from '../../../shared/components/IconosPanel'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { ALCANCES, useCatalogoPermisos } from '../hooks/useCatalogos'
import './matriz.css'

const iguales = (a, b) => {
  const ka = Object.keys(a)
  return ka.length === Object.keys(b).length && ka.every((k) => a[k] === b[k])
}

const ICONOS_MODULO = {
  SEGURIDAD: 'shield',
  ORGANIZACION: 'building',
  VENTAS: 'cart',
  COMPRAS: 'truck',
  INVENTARIO: 'boxes',
  CAJA: 'wallet',
  CLIENTES: 'users',
  PRODUCTOS: 'package',
  REPORTES: 'chart',
  AUDITORIA: 'history',
  CONFIGURACION: 'settings',
}

const FILTROS = [
  ['todos', 'Todos'],
  ['con', 'Con permisos'],
  ['sin', 'Sin permisos'],
]

const SUBMODULOS = {
  USUARIOS: 'Usuarios',
  ROLES: 'Roles y permisos',
  SESIONES: 'Sesiones',
  EMPRESAS: 'Empresas',
  SUCURSALES: 'Sucursales',
  ORGANIZACION: 'Organización',
  AUDITORIA: 'Auditoría',
  CLASIFICACION: 'Familias y categorías',
  MARCAS: 'Marcas',
  ALMACENES: 'Almacenes',
  UBICACIONES: 'Ubicaciones',
  COMPROBANTES: 'Tipos de comprobante',
  SERIES: 'Series de comprobantes',
  CUENTAS: 'Cajas y cuentas',
  MEDIOS_PAGO: 'Métodos de pago',
  PERIODICIDADES: 'Periodicidades de cuotas',
  IGV: 'IGV e impuestos',
  TIPO_CAMBIO: 'Tipo de cambio',
  CENTROS_COSTO: 'Centros de costo',
  CONSULTAS: 'Consulta de DNI y RUC',
  UNIDADES: 'Unidades de medida',
  LISTAS_PRECIO: 'Listas de precios',
  TRANSPORTE: 'Transporte: empresas, conductores y vehículos',
  PRODUCTOS: 'Productos',
}

const ACENTOS = { FACTURACION: 'Facturación', ORGANIZACION: 'Organización', AUDITORIA: 'Auditoría', CATALOGO: 'Catálogo' }

const bonito = (modulo) => ACENTOS[modulo] ?? modulo.charAt(0) + modulo.slice(1).toLowerCase().replace(/_/g, ' ')

/** Permisos de un módulo agrupados por su submódulo (SEGURIDAD.USUARIOS.VER → «Usuarios»). */
function porSubmodulo(items) {
  const grupos = new Map()
  for (const p of items) {
    const partes = p.codigo.split('.')
    const clave = partes.length >= 3 ? partes[1] : ''
    if (!grupos.has(clave)) grupos.set(clave, [])
    grupos.get(clave).push(p)
  }
  return [...grupos.entries()].map(([clave, lista]) => [clave, SUBMODULOS[clave] ?? (clave ? bonito(clave) : ''), lista])
}

const plano = (texto) => (texto ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()

const esVer = (p) => p.codigo.split('.').at(-1).startsWith('VER')

/**
 * Matriz módulo → permiso → alcance, en dos paneles: a la izquierda los módulos (con buscador y
 * cuántos permisos tiene el rol en cada uno) y a la derecha los permisos del módulo elegido.
 * Edita una copia local y envía TODO el conjunto al guardar (el backend reemplaza la matriz y
 * valida que quien edita posea lo que agrega).
 */
export default function MatrizPermisos({ rol, soloLectura }) {
  const catalogo = useCatalogoPermisos()
  const [permisos, setPermisos] = useState(rol.permisos)
  const [elegido, setElegido] = useState(null)
  const [busqueda, setBusqueda] = useState('')
  const [filtro, setFiltro] = useState('todos')
  const [buscaSub, setBuscaSub] = useState('')

  const guardar = useMutacion({
    mutationFn: () => api.put(`/seguridad/roles/${rol.id}/permisos/`, { permisos }).then((r) => r.data),
    invalidar: [['roles']],
    exito: 'Permisos del rol actualizados.',
  })

  const porModulo = useMemo(() => {
    const grupos = {}
    for (const p of catalogo.data ?? []) (grupos[p.modulo] ??= []).push(p)
    return Object.entries(grupos)
  }, [catalogo.data])

  const asignados = (items) => items.filter((p) => permisos[p.codigo]).length

  const texto = busqueda.trim().toLowerCase()
  const visibles = porModulo.filter(([modulo, items]) => {
    const n = asignados(items)
    if (filtro === 'con' && n === 0) return false
    if (filtro === 'sin' && n > 0) return false
    if (!texto) return true
    return (
      modulo.toLowerCase().includes(texto) ||
      items.some((p) => p.codigo.toLowerCase().includes(texto) || (p.descripcion ?? '').toLowerCase().includes(texto))
    )
  })
  const activo = visibles.find(([m]) => m === elegido) ?? visibles[0]
  const [moduloActivo, itemsActivo = []] = activo ?? []
  const itemsMostrados = texto
    ? itemsActivo.filter(
        (p) =>
          moduloActivo.toLowerCase().includes(texto) ||
          p.codigo.toLowerCase().includes(texto) ||
          (p.descripcion ?? '').toLowerCase().includes(texto),
      )
    : itemsActivo

  const todosLosGrupos = porSubmodulo(itemsMostrados)
  const t = plano(buscaSub.trim())
  // Buscador de submódulos: por su nombre (muestra el grupo entero) o por un permiso (muestra solo los que coinciden).
  const gruposMostrados = t
    ? todosLosGrupos
        .map(([clave, nombre, lista]) => [
          clave,
          nombre,
          plano(nombre).includes(t) ? lista : lista.filter((p) => plano(p.descripcion).includes(t) || plano(p.codigo).includes(t)),
        ])
        .filter(([, , lista]) => lista.length > 0)
    : todosLosGrupos

  const cambiar = (codigo, alcance) =>
    setPermisos((previos) => {
      const siguientes = { ...previos }
      if (alcance) siguientes[codigo] = alcance
      else delete siguientes[codigo]
      return siguientes
    })

  const aplicarA = (items, alcance) =>
    setPermisos((previos) => {
      const siguientes = { ...previos }
      for (const p of items) {
        if (alcance) siguientes[p.codigo] = alcance
        else delete siguientes[p.codigo]
      }
      return siguientes
    })
  const aplicarAlModulo = (alcance) => aplicarA(itemsActivo, alcance)

  // «Solo ver»: deja únicamente los permisos de consulta (con su alcance actual o el más amplio) y quita el resto.
  const soloVer = (items) =>
    setPermisos((previos) => {
      const siguientes = { ...previos }
      for (const p of items) {
        if (!esVer(p)) delete siguientes[p.codigo]
        else siguientes[p.codigo] = previos[p.codigo] ?? 'ORGANIZACION'
      }
      return siguientes
    })

  const total = Object.keys(permisos).length
  const sinCambios = iguales(permisos, rol.permisos)
  const ocupado = soloLectura || guardar.isPending

  const acciones = !soloLectura && (
    <>
      <button type="button" className="boton-cabecera" disabled={sinCambios || guardar.isPending} onClick={() => setPermisos(rol.permisos)}>
        <Icono nombre="cerrar" tam={18} /> Descartar
      </button>
      <button type="button" className="primario boton-cabecera" disabled={sinCambios || guardar.isPending} onClick={() => guardar.mutate()}>
        <Icono nombre="shield" tam={19} /> {guardar.isPending ? 'Guardando…' : 'Guardar permisos'}
      </button>
    </>
  )

  return (
    <PanelTarjeta
      id="matriz"
      icono="shield"
      titulo={`Permisos del rol (${total})`}
      descripcion={
        soloLectura
          ? 'Este rol no se puede modificar (rol de sistema o sin permiso de gestión).'
          : 'Elige un módulo a la izquierda y define el alcance de cada permiso.'
      }
      acciones={acciones}
    >
      <EstadoConsulta consulta={catalogo} hayDatos={porModulo.length > 0}>
        <div className="matriz">
          <aside className="matriz-modulos" aria-label="Módulos">
            <label className="buscador">
              <span className="sr-only">Buscar módulo o permiso</span>
              <Icono nombre="buscar" tam={19} />
              <input type="search" value={busqueda} onChange={(e) => setBusqueda(e.target.value)} placeholder="Buscar módulo o permiso…" />
            </label>
            <div className="matriz-filtros" role="group" aria-label="Filtrar módulos">
              {FILTROS.map(([valor, etiqueta]) => (
                <button key={valor} type="button" className={filtro === valor ? 'activo' : ''} aria-pressed={filtro === valor} onClick={() => setFiltro(valor)}>
                  {etiqueta}
                </button>
              ))}
            </div>
            <ul className="matriz-lista">
              {visibles.length === 0 && <li className="matriz-vacio">Ningún módulo coincide.</li>}
              {visibles.map(([modulo, items]) => {
                const n = asignados(items)
                return (
                  <li key={modulo}>
                    <button
                      type="button"
                      className={`matriz-modulo${modulo === moduloActivo ? ' activo' : ''}`}
                      aria-current={modulo === moduloActivo ? 'true' : undefined}
                      onClick={() => {
                        setElegido(modulo)
                        setBuscaSub('')
                      }}
                    >
                      <Icono nombre={ICONOS_MODULO[modulo] ?? 'layers'} tam={20} />
                      <span className="matriz-modulo-nombre">{bonito(modulo)}</span>
                      <span className="matriz-conteo" data-estado={n === 0 ? 'ninguno' : n === items.length ? 'todos' : 'parcial'}>
                        {n}/{items.length}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </aside>

          <div className="matriz-detalle">
            {!activo ? (
              <p className="matriz-vacio">Elige un módulo para ver sus permisos.</p>
            ) : (
              <>
                <header className="matriz-detalle-cab">
                  <span className="panel-tarjeta-icono" aria-hidden="true">
                    <Icono nombre={ICONOS_MODULO[moduloActivo] ?? 'layers'} tam={22} />
                  </span>
                  <div>
                    <h4>{bonito(moduloActivo)}</h4>
                    <p>
                      {asignados(itemsActivo)} de {itemsActivo.length} permisos asignados
                    </p>
                  </div>
                  {!soloLectura && (
                    <div className="matriz-masivo">
                      <label className="sr-only" htmlFor="matriz-masivo">Aplicar un alcance a todo el módulo</label>
                      <select
                        id="matriz-masivo"
                        value=""
                        disabled={ocupado}
                        onChange={(e) => e.target.value && aplicarAlModulo(e.target.value)}
                      >
                        <option value="">Aplicar a todo el módulo…</option>
                        {ALCANCES.map(([valor, etiqueta]) => (
                          <option key={valor} value={valor}>{etiqueta}</option>
                        ))}
                      </select>
                      <button type="button" disabled={ocupado || asignados(itemsActivo) === 0} onClick={() => aplicarAlModulo('')}>
                        Quitar todo
                      </button>
                    </div>
                  )}
                </header>
                <div className="matriz-barra" aria-hidden="true">
                  <span style={{ width: `${(asignados(itemsActivo) / itemsActivo.length) * 100}%` }} />
                </div>
                {todosLosGrupos.length > 1 && (
                  <label className="buscador matriz-buscar-sub">
                    <span className="sr-only">Buscar submódulo o permiso</span>
                    <Icono nombre="buscar" tam={19} />
                    <input type="search" value={buscaSub} onChange={(e) => setBuscaSub(e.target.value)} placeholder="Buscar submódulo o permiso…" />
                  </label>
                )}
                {gruposMostrados.length === 0 && <p className="matriz-vacio">Ningún permiso coincide.</p>}
                {gruposMostrados.map(([clave, nombre, lista]) => (
                  <section key={clave || 'general'} className="matriz-submodulo" aria-label={nombre || undefined}>
                    {nombre && (
                      <header className="matriz-submodulo-cab">
                        <h5>{nombre}</h5>
                        <span className="matriz-conteo" data-estado={asignados(lista) === 0 ? 'ninguno' : asignados(lista) === lista.length ? 'todos' : 'parcial'}>
                          {asignados(lista)}/{lista.length}
                        </span>
                        {!soloLectura && (
                          <div className="matriz-masivo">
                            <button type="button" disabled={ocupado} onClick={() => soloVer(lista)} title="Deja solo los permisos de consulta">
                              Solo ver
                            </button>
                            <button type="button" disabled={ocupado || asignados(lista) === 0} onClick={() => aplicarA(lista, '')}>
                              Quitar todo
                            </button>
                          </div>
                        )}
                      </header>
                    )}
                    <ul className="matriz-permisos">
                      {lista.map((p) => (
                        <li key={p.codigo} data-activo={permisos[p.codigo] ? 'si' : 'no'}>
                          <div className="matriz-permiso-texto">
                            <label htmlFor={`perm-${p.codigo}`}>{p.descripcion || p.codigo}</label>
                            <small>{p.codigo}</small>
                            {p.es_critico && <span className="pildora" data-tono="rojo" style={{ minWidth: 0 }}>Crítico</span>}
                          </div>
                          <select
                            id={`perm-${p.codigo}`}
                            value={permisos[p.codigo] ?? ''}
                            disabled={ocupado}
                            onChange={(e) => cambiar(p.codigo, e.target.value)}
                          >
                            <option value="">Sin acceso</option>
                            {ALCANCES.map(([valor, etiqueta]) => (
                              <option key={valor} value={valor}>{etiqueta}</option>
                            ))}
                          </select>
                        </li>
                      ))}
                    </ul>
                  </section>
                ))}
              </>
            )}
          </div>
        </div>
      </EstadoConsulta>
    </PanelTarjeta>
  )
}
