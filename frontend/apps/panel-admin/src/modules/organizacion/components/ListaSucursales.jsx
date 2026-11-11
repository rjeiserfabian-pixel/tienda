import { useState } from 'react'
import { api, erroresDeCampo } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import CabeceraListado, { Buscador } from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import SelectorUbigeo from '../../../shared/components/SelectorUbigeo'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import Modal from '../../../shared/components/Modal'
import Paginacion from '../../../shared/components/Paginacion'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import { useMutacion } from '../../../shared/hooks/useMutacion'

function SucursalModal({ empresaId, sucursal, onCerrar }) {
  const editando = Boolean(sucursal)
  const [f, setF] = useState({
    codigo: sucursal?.codigo ?? '',
    nombre: sucursal?.nombre ?? '',
    local_fisico: sucursal?.local_fisico ?? '',
    direccion: sucursal?.direccion ?? '',
    ubigeo: sucursal?.ubigeo ?? '',
    estado: sucursal?.estado ?? 'ACTIVO',
  })
  const [errores, setErrores] = useState({})

  const guardar = useMutacion({
    mutationFn: (datos) =>
      editando
        ? api.patch(`/organizacion/sucursales/${sucursal.id}/`, datos).then((r) => r.data)
        : api.post('/organizacion/sucursales/', { ...datos, empresa: empresaId }).then((r) => r.data),
    invalidar: [['sucursales']],
    exito: editando ? 'Sucursal actualizada.' : 'Sucursal creada.',
    alExito: onCerrar,
    avisarError: false,
  })

  const cambiar = (e) => setF((p) => ({ ...p, [e.target.name]: e.target.value }))

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending) return
    const locales = {}
    if (!f.nombre.trim()) locales.nombre = 'Ingrese el nombre.'
    if (!editando && !f.codigo.trim()) locales.codigo = 'Ingrese el código.'
    setErrores(locales)
    if (Object.keys(locales).length) return
    const { codigo: _codigo, ...resto } = f // el código no se envía al editar
    guardar.mutate(editando ? resto : f, {
      onError: (error) => setErrores({ general: 'No se pudo guardar.', ...erroresDeCampo(error) }),
    })
  }

  return (
    <Modal
      titulo={editando ? `Sucursal ${sucursal.codigo}` : 'Nueva sucursal'}
      subtitulo={editando ? 'Modifica los datos de la sucursal.' : 'Registra una sucursal de esta empresa.'}
      onCerrar={onCerrar}
    >
      <form onSubmit={enviar} noValidate>
        {!editando && (
          <Campo etiqueta="Código" icono="tags" error={errores.codigo} ayuda="Único dentro de la empresa; no se cambia después.">
            {(p) => <input {...p} placeholder="Ej. 002" name="codigo" maxLength={10} value={f.codigo} onChange={cambiar} />}
          </Campo>
        )}
        <Campo etiqueta="Nombre" icono="tags" error={errores.nombre}>
          {(p) => <input {...p} placeholder="Ej. Tienda Centro" name="nombre" value={f.nombre} onChange={cambiar} />}
        </Campo>
        <Campo etiqueta="Dirección" icono="building" error={errores.direccion}>
          {(p) => <input {...p} placeholder="Ej. Av. Principal 123, Lima" name="direccion" value={f.direccion} onChange={cambiar} />}
        </Campo>
        <Campo etiqueta="Distrito (ubigeo)" icono="ubicacion" error={errores.ubigeo} ayuda="Opcional: la guía de remisión lo propone como ubigeo del punto de partida.">
          {(p) => <SelectorUbigeo {...p} name="ubigeo" valor={f.ubigeo} onCambio={(v) => setF((previo) => ({ ...previo, ubigeo: v }))} />}
        </Campo>
        <Campo etiqueta="Local físico" icono="store" error={errores.local_fisico} ayuda="Igual en las sucursales de distintas empresas que comparten un mismo local.">
          {(p) => <input {...p} placeholder="Ej. LOCAL-01 (si comparte local con otra empresa)" name="local_fisico" value={f.local_fisico} onChange={cambiar} />}
        </Campo>
        {editando && (
          <Campo etiqueta="Estado" icono="settings" tipo="select" error={errores.estado}>
            {(p) => (
              <select {...p} name="estado" value={f.estado} onChange={cambiar}>
                <option value="ACTIVO">Activa</option>
                <option value="INACTIVO">Inactiva</option>
              </select>
            )}
          </Campo>
        )}
        {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={guardar.isPending}>Cancelar</button>
          <button type="submit" className="primario" disabled={guardar.isPending}>
            {guardar.isPending ? 'Guardando…' : 'Guardar'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

/** Tabla de sucursales con sus acciones. Compartida por la página y la ficha de empresa. */
function TablaSucursales({ filas, desde, puedeEditar, alEditar, alCambiarEstado, pendienteId }) {
  const { empresas } = useEmpresas()
  const nombreEmpresa = (id) => {
    const e = empresas.find((x) => x.id === id)
    return e ? e.nombre_comercial || e.razon_social : '—'
  }
  return (
    <div className="marco-tabla">
      <table className="tabla-datos">
        <thead>
          <tr>
            <th className="centrado">#</th>
            <th>Empresa</th>
            <th>Código</th>
            <th>Nombre</th>
            <th>Dirección</th>
            <th>Local físico</th>
            <th>Estado</th>
            <th className="centrado">Acciones</th>
          </tr>
        </thead>
        <tbody>
          {filas.length === 0 && (
            <FilaVacia
              columnas={8}
              icono="store"
              titulo="No hay sucursales para mostrar"
              descripcion="Cambia la búsqueda o el estado, o crea una con el botón «Nueva sucursal»."
            />
          )}
          {filas.map((s, i) => (
            <tr key={s.id}>
              <td className="centrado celda-suave">{desde + i}</td>
              <td>{nombreEmpresa(s.empresa)}</td>
              <td className="celda-usuario">{s.codigo}</td>
              <td>{s.nombre}</td>
              <td className="celda-suave">{s.direccion || '—'}</td>
              <td className="celda-suave">{s.local_fisico || '—'}</td>
              <td>
                <span className={`estado-pildora ${s.estado === 'ACTIVO' ? 'activo' : 'inactivo'}`}>
                  {s.estado === 'ACTIVO' ? 'Activa' : 'Inactiva'}
                </span>
              </td>
              <td className="centrado">
                {puedeEditar && (
                  <span className="acciones-fila">
                    <button type="button" className="accion-icono editar" title="Editar" aria-label={`Editar la sucursal ${s.codigo}`} onClick={() => alEditar(s)}>
                      <Icono nombre="lapiz" tam={19} />
                    </button>
                    {s.estado === 'ACTIVO' ? (
                      <button type="button" className="accion-icono peligro-suave" title="Desactivar" aria-label={`Desactivar la sucursal ${s.codigo}`} disabled={pendienteId === s.id} onClick={() => alCambiarEstado(s)}>
                        <Icono nombre="apagar" tam={19} />
                      </button>
                    ) : (
                      <button type="button" className="accion-icono reactivar" title="Reactivar" aria-label={`Reactivar la sucursal ${s.codigo}`} disabled={pendienteId === s.id} onClick={() => alCambiarEstado(s)}>
                        <Icono nombre="reactivar" tam={19} />
                      </button>
                    )}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/**
 * Sucursales de una empresa. `variante="pagina"` muestra la cabecera completa (buscador, filtro y
 * botón de alta, como el resto de listados); `variante="seccion"` es la versión compacta que va
 * dentro de la ficha de la empresa.
 */
export default function ListaSucursales({ empresaId, empresaNombre, puedeEditar, variante = 'seccion' }) {
  const [busqueda, setBusqueda] = useState('')
  const [estado, setEstado] = useState('')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [modal, setModal] = useState(null) // null | {sucursal|null}
  const [cambiando, setCambiando] = useState(null) // sucursal a desactivar (pide confirmación)
  const q = useDebounce(busqueda, 400)

  const consulta = useListado(['sucursales'], '/organizacion/sucursales/', {
    empresa: empresaId,
    q,
    estado,
    page: pagina,
    page_size: tamano,
  })
  const filas = consulta.data?.results ?? []

  const cambiarEstado = useMutacion({
    mutationFn: (sucursal) =>
      api
        .patch(`/organizacion/sucursales/${sucursal.id}/`, { estado: sucursal.estado === 'ACTIVO' ? 'INACTIVO' : 'ACTIVO' })
        .then((r) => r.data),
    invalidar: [['sucursales']],
    exito: 'Sucursal actualizada.',
    alExito: () => setCambiando(null),
  })
  // Reactivar es inocuo y va directo; desactivar pide confirmación.
  const alCambiarEstado = (s) => (s.estado === 'ACTIVO' ? setCambiando(s) : cambiarEstado.mutate(s))

  const botonNueva = puedeEditar && (
    <button type="button" className="primario boton-cabecera" onClick={() => setModal({ sucursal: null })}>
      <Icono nombre="agregar" tam={20} /> Nueva sucursal
    </button>
  )
  const filtroEstado = (
    <select
      className="boton-cabecera"
      aria-label="Estado"
      value={estado}
      onChange={(e) => {
        setEstado(e.target.value)
        setPagina(1)
      }}
    >
      <option value="">Todos los estados</option>
      <option value="ACTIVO">Activas</option>
      <option value="INACTIVO">Inactivas</option>
    </select>
  )
  const buscador = (
    <Buscador
      valor={busqueda}
      onCambio={(valor) => {
        setBusqueda(valor)
        setPagina(1)
      }}
      etiqueta="Buscar sucursales"
      placeholder="Buscar sucursal…"
    />
  )

  const contenido = (
    <>
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <TablaSucursales filas={filas} desde={(pagina - 1) * tamano + 1} puedeEditar={puedeEditar} alEditar={(s) => setModal({ sucursal: s })} alCambiarEstado={alCambiarEstado} pendienteId={cambiarEstado.isPending ? cambiarEstado.variables?.id : null} />
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
      {cambiando && (
        <ConfirmarModal
          titulo="Desactivar sucursal"
          mensaje={`La sucursal ${cambiando.codigo} · ${cambiando.nombre} dejará de estar disponible para operar. No se borra nada y podrás reactivarla cuando quieras.`}
          textoConfirmar="Desactivar"
          enviando={cambiarEstado.isPending}
          onConfirmar={() => cambiarEstado.mutate(cambiando)}
          onCerrar={() => setCambiando(null)}
        />
      )}
      {modal && <SucursalModal empresaId={empresaId} sucursal={modal.sucursal} onCerrar={() => setModal(null)} />}
    </>
  )

  if (variante === 'pagina') {
    return (
      <>
        <CabeceraListado
          icono="store"
          titulo="Sucursales"
          descripcion={empresaNombre ? `Sucursales de ${empresaNombre}.` : 'Sucursales de la empresa activa.'}
        >
          {buscador}
          {filtroEstado}
          {botonNueva}
        </CabeceraListado>
        {contenido}
      </>
    )
  }

  return (
    <PanelTarjeta
      id="sucursales"
      icono="store"
      titulo="Sucursales"
      descripcion="Locales de esta empresa."
      acciones={
        <>
          {buscador}
          {botonNueva}
        </>
      }
    >
      {contenido}
    </PanelTarjeta>
  )
}
