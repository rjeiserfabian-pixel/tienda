import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, erroresDeCampo } from '../../../core/api/client'
import AvisoLectura from '../../../shared/components/AvisoLectura'
import BotonVolver from '../../../shared/components/BotonVolver'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Campo from '../../../shared/components/Campo'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import Interruptor from '../../../shared/components/Interruptor'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useModoLectura } from '../../../shared/hooks/useModoLectura'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import EspecificacionesProducto from '../components/EspecificacionesProducto'
import FotosPendientes from '../components/FotosPendientes'
import FotosProducto from '../components/FotosProducto'
import ParaLaTienda, { datosDeTienda, revisarTienda } from '../components/ParaLaTienda'
import PreciosProducto from '../components/PreciosProducto'
import PresentacionesProducto from '../components/PresentacionesProducto'
import RegistroRapidoModal from '../components/RegistroRapidoModal'
import UbicacionesProducto from '../components/UbicacionesProducto'
import { useCamposEspecificacion } from '../hooks/useCamposEspecificacion'
import { useOpciones } from '../hooks/useOpciones'
import { erroresDeEspecificaciones, revisarValores, valoresParaEnviar } from '../../mantenimiento/especificaciones'
import { aNumero, TIPOS_PRODUCTO } from '../utilidades'
import '../../mantenimiento/components/maestros.css'
import '../productos.css'

const RUTA = '/almacen/productos'
const CAMBIAR_PRECIO = 'MANTENIMIENTO.PRODUCTOS.CAMBIAR_PRECIO'
const BOTON_MAS = (alClick) => (
  <button type="button" className="mas-rapido" onClick={(e) => { e.preventDefault(); alClick() }}>
    + Nueva
  </button>
)
const texto = (v) => (v === null || v === undefined ? '' : String(v))
const numero = (v) => (v === null || v === undefined || v === '' ? '' : String(Number(v))) // «100.0000» → «100»

const VACIO = {
  nombre: '',
  tipo: 'BIEN',
  familia: '',
  categoria: '',
  marca: '',
  unidad: '',
  codigo_barras: '',
  codigo_fabricante: '',
  codigo_sunat: '',
  descripcion: '',
  stock_minimo: '',
  controla_stock: true,
  lleva_serie: false,
  precio_editable: false,
  afectacion_igv: '',
  costo: '',
  // Para la tienda
  especificaciones: {},
  publicado_web: false,
  destacado: false,
  es_nuevo: false,
  descripcion_web: '',
  puntos_destacados: [],
  slug: '',
  garantia_meses: '',
  peso_kg: '',
  largo_cm: '',
  ancho_cm: '',
  alto_cm: '',
}

const desdeRegistro = (p) => ({
  nombre: p.nombre,
  tipo: p.tipo,
  familia: texto(p.familia),
  categoria: texto(p.categoria),
  marca: texto(p.marca),
  unidad: texto(p.unidad),
  codigo_barras: p.codigo_barras,
  codigo_fabricante: p.codigo_fabricante,
  codigo_sunat: p.codigo_sunat ?? '',
  descripcion: p.descripcion,
  stock_minimo: numero(p.stock_minimo),
  controla_stock: p.controla_stock,
  lleva_serie: p.lleva_serie,
  precio_editable: p.precio_editable,
  afectacion_igv: texto(p.afectacion_igv),
  costo: numero(p.costo),
  especificaciones: { ...(p.especificaciones ?? {}) },
  publicado_web: Boolean(p.publicado_web),
  destacado: Boolean(p.destacado),
  es_nuevo: Boolean(p.es_nuevo),
  descripcion_web: p.descripcion_web ?? '',
  puntos_destacados: [...(p.puntos_destacados ?? [])],
  slug: p.slug ?? '',
  garantia_meses: texto(p.garantia_meses),
  peso_kg: numero(p.peso_kg),
  largo_cm: numero(p.largo_cm),
  ancho_cm: numero(p.ancho_cm),
  alto_cm: numero(p.alto_cm),
})

const preciosDe = (p) => Object.fromEntries((p?.precios ?? []).map((x) => [x.lista, { precio: numero(x.precio) }]))

function Formulario({ registro, listas, puedeEditar, puedePrecios }) {
  const navegar = useNavigate()
  const nuevo = !registro
  const [f, setF] = useState(() => (registro ? desdeRegistro(registro) : VACIO))
  const [precios, setPrecios] = useState(() => preciosDe(registro))
  const [errores, setErrores] = useState({})
  const [erroresEsp, setErroresEsp] = useState({}) // por clave de especificación
  const [rapido, setRapido] = useState(null) // catálogo que se está creando sin salir del producto
  const [pendientes, setPendientes] = useState([]) // fotos elegidas antes de registrar
  const { tiene } = usePermisos()
  const puedeCrear = (permiso) => puedeEditar && tiene(`MANTENIMIENTO.${permiso}.CREAR`, { organizacion: true })
  const cambiar = (campo, valor) => setF((previo) => ({ ...previo, [campo]: valor }))
  const esServicio = f.tipo === 'SERVICIO'
  const espec = useCamposEspecificacion(f.categoria)
  const cambiarDato = (clave, valor) => {
    setF((previo) => {
      const siguiente = { ...previo.especificaciones }
      if (valor === undefined) delete siguiente[clave]
      else siguiente[clave] = valor
      return { ...previo, especificaciones: siguiente }
    })
    setErroresEsp((previos) => (previos[clave] ? { ...previos, [clave]: undefined } : previos))
  }

  const familias = useOpciones('/mantenimiento/familias/')
  const categorias = useOpciones('/mantenimiento/categorias/', { familia: f.familia }, { enabled: Boolean(f.familia) })
  const marcas = useOpciones('/mantenimiento/marcas/')
  const unidades = useOpciones('/mantenimiento/unidades/')
  const veIgv = tiene('MANTENIMIENTO.IGV.VER', { organizacion: true })
  const afectaciones = useOpciones('/mantenimiento/afectaciones-igv/', {}, { enabled: veIgv })

  // Aviso (no bloqueo) si ya hay un producto con un nombre parecido.
  const nombre = useDebounce(f.nombre.trim(), 500)
  const parecidos = useQuery({
    queryKey: ['productos', 'parecidos', nombre],
    queryFn: ({ signal }) => api.get('/mantenimiento/productos/', { params: { q: nombre, page_size: 5 }, signal }).then((r) => r.data.results),
    enabled: puedeEditar && nombre.length >= 3 && nombre !== registro?.nombre,
  })
  const otros = (parecidos.data ?? []).filter((p) => p.id !== registro?.id)

  const guardar = useMutacion({
    mutationFn: async (datos) => {
      if (!nuevo) return api.patch(`/mantenimiento/productos/${registro.id}/`, datos).then((r) => r.data)
      const creado = await api.post('/mantenimiento/productos/', datos).then((r) => r.data)
      let fallidas = 0
      for (const { archivo } of pendientes) {
        const cuerpo = new FormData()
        cuerpo.append('imagen', archivo)
        try {
          await api.post(`/mantenimiento/productos/${creado.id}/fotos/`, cuerpo, { timeout: 60_000 })
        } catch {
          fallidas += 1 // el producto ya existe: las que fallen se suben desde su ficha
        }
      }
      return { ...creado, fotos_fallidas: fallidas }
    },
    invalidar: [['productos']],
    exito: (r) => (!nuevo ? 'Producto actualizado.' : r.fotos_fallidas ? `Producto registrado, pero ${r.fotos_fallidas} foto(s) no se pudieron subir. Agrégalas desde su ficha.` : 'Producto registrado.'),
    alExito: (creado) => nuevo && navegar(`${RUTA}/${creado.id}`, { replace: true }),
    avisarError: false,
  })

  const validar = () => {
    const e = {}
    if (!f.nombre.trim()) e.nombre = 'Ingrese el nombre del producto.'
    if (!f.categoria) e.categoria = 'Elija la categoría.'
    if (!f.unidad) e.unidad = 'Elija la unidad de medida.'
    if (f.codigo_sunat.trim() && !/^\d{8}$/.test(f.codigo_sunat.trim())) e.codigo_sunat = 'El código SUNAT tiene 8 dígitos.'
    if (f.stock_minimo !== '' && (aNumero(f.stock_minimo) ?? -1) < 0) e.stock_minimo = 'Debe ser un número desde 0.'
    if (f.costo !== '' && (aNumero(f.costo) ?? -1) < 0) e.costo = 'Debe ser un número desde 0.'
    for (const [id, p] of Object.entries(precios)) {
      if (p.precio !== '' && (aNumero(p.precio) ?? -1) < 0) e.precios = `El precio de «${listas.find((l) => String(l.id) === id)?.nombre}» no es válido.`
    }
    return { ...e, ...revisarTienda(f) }
  }

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending || !puedeEditar) return
    const locales = validar()
    const localesEsp = espec.listos ? revisarValores(espec.activos, f.especificaciones) : {}
    // Qué secciones de especificaciones tienen datos por corregir, para decirlo junto al botón.
    const avisoEsp = (porDato) => {
      const secciones = [...new Set(espec.activos.filter((c) => porDato[c.clave]).map((c) => c.seccion || 'General'))]
      return secciones.length ? `Hay datos técnicos por corregir, marcados en rojo (${secciones.join(', ')}).` : null
    }
    const resumen = avisoEsp(localesEsp)
    setErrores(resumen ? { ...locales, general: resumen } : locales)
    setErroresEsp(localesEsp)
    if (Object.keys(locales).length || Object.keys(localesEsp).length) return
    const datos = {
      nombre: f.nombre.trim(),
      tipo: f.tipo,
      categoria: Number(f.categoria),
      marca: f.marca ? Number(f.marca) : null,
      unidad: Number(f.unidad),
      codigo_barras: f.codigo_barras.trim(),
      codigo_fabricante: f.codigo_fabricante.trim(),
      codigo_sunat: f.codigo_sunat.trim(),
      descripcion: f.descripcion.trim(),
      stock_minimo: esServicio ? 0 : aNumero(f.stock_minimo) ?? 0,
      controla_stock: !esServicio && f.controla_stock,
      lleva_serie: !esServicio && f.lleva_serie,
      precio_editable: f.precio_editable,
      ...datosDeTienda(f, nuevo),
    }
    // Solo se envían las especificaciones cuando ya se conocen los datos de la categoría: así nunca se borran por error.
    if (espec.listos) datos.especificaciones = valoresParaEnviar(espec.activos, f.especificaciones)
    if (veIgv) datos.afectacion_igv = f.afectacion_igv ? Number(f.afectacion_igv) : null
    if (puedePrecios) {
      datos.costo = aNumero(f.costo) ?? 0
      datos.precios = listas
        .filter((l) => aNumero(precios[l.id]?.precio) !== null)
        .map((l) => ({ lista: l.id, precio: aNumero(precios[l.id].precio) }))
    }
    guardar.mutate(datos, {
      onError: (error) => {
        const delServidor = erroresDeCampo(error)
        const porDato = erroresDeEspecificaciones(error)
        delete delServidor.especificaciones // viene por dato, no como un texto
        setErroresEsp(porDato)
        setErrores({
          general: avisoEsp(porDato) ?? 'No se pudo guardar.',
          ...delServidor,
        })
      },
    })
  }

  const sinOpciones = (consulta, enlace, que) =>
    consulta.isSuccess && consulta.data.length === 0 ? (
      <>
        No hay {que}. <Link to={enlace}>Créalas aquí</Link>.
      </>
    ) : undefined

  return (
    <>
    <form onSubmit={enviar} noValidate className="producto-form">
      <fieldset disabled={!puedeEditar || guardar.isPending} className="sin-borde">
        <PanelTarjeta id="datos" icono="package" titulo="Datos del producto" descripcion="Cómo se llama, dónde se clasifica y cómo se cuenta.">
          <div className="maestro-campos">
            <div className="completo">
              <Campo
                etiqueta="Nombre del producto"
                icono="package"
                requerido
                error={errores.nombre}
                ayuda={otros.length ? undefined : 'Escribe el nombre completo y claro: es el que verán en ventas y en la tienda.'}
              >
                {(p) => <input {...p} name="nombre" value={f.nombre} maxLength={200} placeholder="Ej. Teclado Logitech K120 USB" onChange={(e) => cambiar('nombre', e.target.value)} />}
              </Campo>
              {otros.length > 0 && (
                <p className="aviso-parecidos" role="status">
                  <Icono nombre="ojo" tam={16} /> Ya hay productos parecidos:{' '}
                  {otros.map((p, i) => (
                    <span key={p.id}>
                      {i > 0 && ', '}
                      <Link to={`${RUTA}/${p.id}`} target="_blank" rel="noreferrer">{p.nombre}</Link>
                    </span>
                  ))}
                  . Revisa que no lo estés repitiendo.
                </p>
              )}
            </div>
            <Campo etiqueta="Código interno" icono="documento" ayuda="Lo asigna el sistema al guardar.">
              {(p) => <input {...p} value={registro?.codigo ?? 'Automático'} readOnly disabled />}
            </Campo>
            <Campo etiqueta="Tipo" icono="tags" tipo="select" error={errores.tipo}>
              {(p) => (
                <select {...p} name="tipo" value={f.tipo} onChange={(e) => cambiar('tipo', e.target.value)}>
                  {TIPOS_PRODUCTO.map(([v, t]) => (
                    <option key={v} value={v}>{t}</option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta={<>Familia{puedeCrear('CLASIFICACION') && BOTON_MAS(() => setRapido('familia'))}</>} icono="layers" requerido tipo="select" ayuda={sinOpciones(familias, '/mantenimiento/clasificacion', 'familias')}>
              {(p) => (
                <select
                  {...p}
                  name="familia"
                  value={f.familia}
                  onChange={(e) => setF((previo) => ({ ...previo, familia: e.target.value, categoria: '' }))}
                >
                  <option value="">Elija la familia</option>
                  {(familias.data ?? []).map((x) => (
                    <option key={x.id} value={String(x.id)}>{x.nombre}</option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo
              etiqueta={<>Categoría{puedeCrear('CLASIFICACION') && BOTON_MAS(() => (f.familia ? setRapido('categoria') : setErrores((e) => ({ ...e, categoria: 'Elija primero la familia.' }))))}</>}
              icono="layers"
              requerido
              tipo="select"
              error={errores.categoria}
              ayuda={f.familia ? sinOpciones(categorias, '/mantenimiento/clasificacion', 'categorías en esa familia') : undefined}
            >
              {(p) => (
                <select {...p} name="categoria" value={f.categoria} disabled={!f.familia || !puedeEditar} onChange={(e) => cambiar('categoria', e.target.value)}>
                  <option value="">{f.familia ? 'Elija la categoría' : 'Elija primero la familia'}</option>
                  {(categorias.data ?? []).map((x) => (
                    <option key={x.id} value={String(x.id)}>{x.nombre}</option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta={<>Marca{puedeCrear('MARCAS') && BOTON_MAS(() => setRapido('marca'))}</>} icono="tags" tipo="select" error={errores.marca} ayuda="Opcional.">
              {(p) => (
                <select {...p} name="marca" value={f.marca} onChange={(e) => cambiar('marca', e.target.value)}>
                  <option value="">Sin marca</option>
                  {(marcas.data ?? []).map((x) => (
                    <option key={x.id} value={String(x.id)}>{x.nombre}</option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta={<>Unidad de medida{puedeCrear('UNIDADES') && BOTON_MAS(() => setRapido('unidad'))}</>} icono="calculator" requerido tipo="select" error={errores.unidad} ayuda={sinOpciones(unidades, '/mantenimiento/unidades', 'unidades')}>
              {(p) => (
                <select {...p} name="unidad" value={f.unidad} onChange={(e) => cambiar('unidad', e.target.value)}>
                  <option value="">Elija la unidad</option>
                  {(unidades.data ?? []).map((x) => (
                    <option key={x.id} value={String(x.id)}>{x.nombre} ({x.abreviatura})</option>
                  ))}
                </select>
              )}
            </Campo>
            <Campo etiqueta="Código de barras" icono="scan" error={errores.codigo_barras} ayuda="Si no trae uno, al imprimir etiquetas se usa el código interno.">
              {(p) => <input {...p} name="codigo_barras" value={f.codigo_barras} maxLength={40} inputMode="numeric" placeholder="Ej. 7750182001234" onChange={(e) => cambiar('codigo_barras', e.target.value)} />}
            </Campo>
            <Campo etiqueta="Código del fabricante" icono="documento" error={errores.codigo_fabricante} ayuda="Opcional. El número de parte o modelo.">
              {(p) => <input {...p} name="codigo_fabricante" value={f.codigo_fabricante} maxLength={60} placeholder="Ej. K120" onChange={(e) => cambiar('codigo_fabricante', e.target.value)} />}
            </Campo>
            <Campo etiqueta="Código SUNAT" icono="documento" error={errores.codigo_sunat} ayuda="Opcional. 8 dígitos del catálogo de SUNAT; la factura electrónica lo pide. Si lo dejas vacío se usa el de la configuración de la empresa.">
              {(p) => <input {...p} name="codigo_sunat" value={f.codigo_sunat} maxLength={8} inputMode="numeric" placeholder="Ej. 43211503" onChange={(e) => cambiar('codigo_sunat', e.target.value.replace(/\D/g, ''))} />}
            </Campo>
            <div className="completo">
              <Campo etiqueta="Descripción" error={errores.descripcion} contador={{ actual: f.descripcion.length, max: 1000 }}>
                {(p) => <textarea {...p} name="descripcion" rows={3} value={f.descripcion} maxLength={1000} placeholder="Opcional. Detalles que ayuden a venderlo." onChange={(e) => cambiar('descripcion', e.target.value)} />}
              </Campo>
            </div>
          </div>
        </PanelTarjeta>

        <EspecificacionesProducto
          categoriaId={f.categoria}
          campos={espec.activos}
          cargando={espec.consulta.isLoading}
          huboError={espec.consulta.isError}
          valores={f.especificaciones}
          errores={erroresEsp}
          puedeDefinir={tiene('MANTENIMIENTO.CLASIFICACION.EDITAR', { organizacion: true })}
          onCambio={cambiarDato}
        />

        <PanelTarjeta id="control" icono="boxes" titulo="Control de inventario" descripcion={esServicio ? 'Un servicio no maneja stock ni series.' : 'Cómo se controla este producto en el almacén.'}>
          <div className="control-grilla">
            <Interruptor activo={!esServicio && f.controla_stock} disabled={esServicio || !puedeEditar} onCambio={(v) => cambiar('controla_stock', v)} texto="Controlar stock" descripcion="Descuenta del almacén en cada venta." />
            <Interruptor activo={!esServicio && f.lleva_serie} disabled={esServicio || !puedeEditar} onCambio={(v) => cambiar('lleva_serie', v)} texto="Lleva serie o IMEI" descripcion="Cada unidad se registra con su número." />
            <Interruptor activo={f.precio_editable} disabled={!puedeEditar} onCambio={(v) => cambiar('precio_editable', v)} texto="Precio editable" descripcion="Se puede cambiar el precio al vender." />
          </div>
          {veIgv && (
            <div className="control-stock">
              <Campo etiqueta="IGV de este producto" icono="calculator" tipo="select" error={errores.afectacion_igv} ayuda="Déjalo en automático: el sistema propone el IGV según el régimen de la empresa y la zona del cliente o proveedor. Elige uno solo si este producto siempre tiene el mismo trato.">
                {(p) => (
                  <select {...p} name="afectacion_igv" value={f.afectacion_igv} onChange={(e) => cambiar('afectacion_igv', e.target.value)}>
                    <option value="">Automático (según la zona y el régimen)</option>
                    {f.afectacion_igv && !(afectaciones.data ?? []).some((a) => String(a.id) === f.afectacion_igv) && <option value={f.afectacion_igv}>{registro?.afectacion_igv_nombre ?? 'Actual'}</option>}
                    {(afectaciones.data ?? []).map((a) => (
                      <option key={a.id} value={String(a.id)}>{a.codigo} · {a.nombre}</option>
                    ))}
                  </select>
                )}
              </Campo>
            </div>
          )}
          {!esServicio && (
            <div className="control-stock">
              <Campo etiqueta="Stock mínimo" icono="boxes" error={errores.stock_minimo} ayuda="Avisa cuando queden menos unidades que estas.">
                {(p) => <input {...p} name="stock_minimo" inputMode="decimal" value={f.stock_minimo} placeholder="0" onChange={(e) => cambiar('stock_minimo', e.target.value)} />}
              </Campo>
            </div>
          )}
        </PanelTarjeta>

        {puedePrecios && (
          <PreciosProducto
            listas={listas}
            costo={f.costo}
            precios={precios}
            errores={errores}
            deshabilitado={!puedeEditar || guardar.isPending}
            onCosto={(v) => cambiar('costo', v)}
            onPrecios={setPrecios}
          />
        )}
        <ParaLaTienda f={f} cambiar={cambiar} errores={errores} registro={registro} />
        {nuevo && <FotosPendientes fotos={pendientes} onCambio={setPendientes} deshabilitado={!puedeEditar || guardar.isPending} />}
      </fieldset>

      {!nuevo && !esServicio && <PresentacionesProducto producto={registro} listas={listas} puedeEditar={puedeEditar} puedePrecios={puedePrecios} />}
      {!nuevo && !esServicio && <UbicacionesProducto productoId={registro.id} />}

      {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
      {puedeEditar && (
        <div className="fila-botones">
          <button type="submit" className="primario boton-cabecera" disabled={guardar.isPending}>
            <Icono nombre="shield" tam={19} /> {guardar.isPending ? 'Guardando…' : nuevo ? 'Registrar producto' : 'Guardar cambios'}
          </button>
        </div>
      )}
    </form>
    {rapido && (
      <RegistroRapidoModal
        tipo={rapido}
        extra={rapido === 'categoria' ? { familia: Number(f.familia) } : {}}
        subtitulo={rapido === 'categoria' ? `Dentro de la familia «${(familias.data ?? []).find((x) => String(x.id) === f.familia)?.nombre ?? ''}».` : undefined}
        onCerrar={() => setRapido(null)}
        onCreado={(creado) => {
          setRapido(null)
          setF((previo) => ({ ...previo, [rapido === 'familia' ? 'familia' : rapido]: String(creado.id), ...(rapido === 'familia' ? { categoria: '' } : {}) }))
        }}
      />
    )}
    </>
  )
}

/** Alta y ficha de un producto: datos, inventario, precios (con permiso) y fotos. */
export default function ProductoFichaPage() {
  const { id } = useParams()
  const nuevo = id === undefined
  const navegar = useNavigate()
  const { hash } = useLocation()
  const { tiene } = usePermisos()
  const lectura = useModoLectura()
  const [eliminando, setEliminando] = useState(false)

  const consulta = useQuery({
    queryKey: ['productos', 'detalle', id],
    queryFn: ({ signal }) => api.get(`/mantenimiento/productos/${id}/`, { signal }).then((r) => r.data),
    enabled: !nuevo,
  })
  const registro = consulta.data
  const listasTodas = useOpciones('/mantenimiento/listas-precio/')
  const listas = useMemo(() => listasTodas.data ?? [], [listasTodas.data])

  const permitido = (accion) => tiene(`MANTENIMIENTO.PRODUCTOS.${accion}`, { organizacion: true })
  const puedeEditar = permitido(nuevo ? 'CREAR' : 'EDITAR') && !lectura
  const puedeEliminar = permitido('ELIMINAR') && !lectura
  const puedePrecios = tiene(CAMBIAR_PRECIO, { organizacion: true })

  // Llegar con #fotos (tras registrar) baja a esa sección.
  useEffect(() => {
    if (registro && hash) document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [registro, hash])

  const cambiarEstado = useMutacion({
    mutationFn: (estado) => api.patch(`/mantenimiento/productos/${id}/`, { estado }).then((r) => r.data),
    invalidar: [['productos']],
    exito: 'Estado actualizado.',
  })
  const eliminar = useMutacion({
    mutationFn: () => api.delete(`/mantenimiento/productos/${id}/`),
    invalidar: [['productos']],
    exito: 'Producto eliminado.',
    alExito: () => navegar(RUTA, { replace: true }),
  })

  const activo = registro?.estado === 'ACTIVO'
  const cuerpo = (
    <>
      {lectura && !nuevo && <AvisoLectura puedeEditar={permitido('EDITAR')} />}
      {/* Se vuelve a montar cuando cambian los datos guardados o las listas, para partir de lo último. */}
      <Formulario
        key={`${JSON.stringify(registro ?? null)}-${listas.map((l) => l.id).join()}`}
        registro={registro}
        listas={listas}
        puedeEditar={puedeEditar}
        puedePrecios={puedePrecios}
      />
      {registro && <FotosProducto productoId={registro.id} puedeEditar={puedeEditar} />}
    </>
  )

  return (
    <main className="listado">
      <BotonVolver ruta={RUTA} texto="Volver a Productos" />
      {nuevo ? (
        <>
          <CabeceraListado icono="package" titulo="Nuevo producto" descripcion="Registra el producto; después podrás agregarle sus fotos." />
          {cuerpo}
        </>
      ) : (
        <EstadoConsulta consulta={consulta} hayDatos={Boolean(registro)} vacio="El producto no existe.">
          {registro && (
            <>
              <CabeceraListado icono="package" titulo={registro.nombre} descripcion={`Código ${registro.codigo} · ${registro.categoria_nombre}`}>
                <span className={`estado-pildora ${activo ? 'activo' : 'inactivo'}`}>{activo ? 'Activo' : 'Inactivo'}</span>
                {puedeEditar && (
                  <button type="button" className={`${activo ? 'peligro' : 'primario'} boton-cabecera`} disabled={cambiarEstado.isPending} onClick={() => cambiarEstado.mutate(activo ? 'INACTIVO' : 'ACTIVO')}>
                    <Icono nombre={activo ? 'apagar' : 'reactivar'} tam={19} /> {cambiarEstado.isPending ? 'Guardando…' : activo ? 'Desactivar' : 'Activar'}
                  </button>
                )}
                {puedeEliminar && (
                  <button type="button" className="peligro boton-cabecera" onClick={() => setEliminando(true)}>
                    <Icono nombre="cerrar" tam={19} /> Eliminar
                  </button>
                )}
              </CabeceraListado>
              {cuerpo}
            </>
          )}
        </EstadoConsulta>
      )}
      {eliminando && (
        <ConfirmarModal
          titulo="Eliminar producto"
          mensaje={`¿Eliminar «${registro?.nombre}»? Dejará de aparecer en las listas y su código de barras quedará libre. El historial se conserva. Si solo quieres que no se use, mejor desactívalo.`}
          textoConfirmar="Eliminar"
          enviando={eliminar.isPending}
          onConfirmar={() => eliminar.mutate()}
          onCerrar={() => setEliminando(false)}
        />
      )}
    </main>
  )
}
