import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useLocation, useParams } from 'react-router-dom'
import { api, erroresDeCampo } from '../../../core/api/client'
import { useAuth } from '../../../core/auth/AuthContext'
import BotonVolver from '../../../shared/components/BotonVolver'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Campo from '../../../shared/components/Campo'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import AvisoLectura from '../../../shared/components/AvisoLectura'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useModoLectura } from '../../../shared/hooks/useModoLectura'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import ListaSucursales from '../components/ListaSucursales'
import LogoEmpresa from '../components/LogoEmpresa'

const CAMPOS_FICHA = ['direccion_fiscal', 'telefono', 'correo', 'sitio_web', 'tienda_web']

function DatosEmpresa({ empresa, puedeEditar, puedeCambiarRuc }) {
  const { renovarSesion } = useAuth()
  const [f, setF] = useState({
    ruc: empresa.ruc,
    razon_social: empresa.razon_social,
    nombre_comercial: empresa.nombre_comercial,
    estado: empresa.estado,
    ...Object.fromEntries(CAMPOS_FICHA.map((k) => [k, empresa[k] ?? ''])),
    es_principal: empresa.es_principal,
  })
  const [errores, setErrores] = useState({})
  const [confirmandoRuc, setConfirmandoRuc] = useState(false)

  const guardar = useMutacion({
    mutationFn: async (datos) => {
      const { data } = await api.patch(`/organizacion/empresas/${empresa.id}/`, datos)
      // El token fija las empresas habilitadas y sus nombres: al cambiar el estado, la razón social
      // o el nombre comercial hay que renovarlo para que la barra superior muestre el cambio.
      if (Object.keys(datos).some((k) => datos[k] !== empresa[k])) await renovarSesion()
      return data
    },
    invalidar: [['empresas']],
    exito: 'Empresa actualizada.',
    avisarError: false,
  })
  const sinCambios = Object.keys(f).every((k) => f[k] === empresa[k])
  const cambiaRuc = f.ruc !== empresa.ruc

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending || sinCambios) return
    if (!f.razon_social.trim()) return setErrores({ razon_social: 'Ingrese la razón social.' })
    if (cambiaRuc && !/^\d{11}$/.test(f.ruc)) return setErrores({ ruc: 'El RUC debe tener 11 dígitos.' })
    setErrores({})
    if (cambiaRuc) return setConfirmandoRuc(true) // el RUC es la identidad tributaria: se confirma antes
    enviarCambios()
  }

  const enviarCambios = () => {
    // El RUC solo viaja si cambió (y el backend exige además el permiso de gestionar la organización).
    const { ruc, ...resto } = f
    guardar.mutate(cambiaRuc ? { ...resto, ruc } : resto, {
      onError: (error) => {
        setConfirmandoRuc(false)
        setErrores({ general: 'No se pudo guardar.', ...erroresDeCampo(error) })
      },
      onSuccess: () => setConfirmandoRuc(false),
    })
  }

  return (
    <section id="datos" className="bloque" aria-labelledby="empresa-datos">
      <h3 id="empresa-datos">Datos de la empresa</h3>
      <form onSubmit={enviar} noValidate style={{ maxWidth: 480 }}>
        <fieldset disabled={!puedeEditar || guardar.isPending} style={{ border: 0, padding: 0 }}>
          <Campo
            etiqueta="RUC"
            icono="documento"
            error={errores.ruc}
            ayuda={
              puedeCambiarRuc
                ? 'Puedes corregirlo mientras la empresa no haya emitido comprobantes. Cada cambio queda en la auditoría.'
                : 'Solo el Superadministrador puede cambiar el RUC.'
            }
          >
            {(p) => (
              <input
                {...p}
                placeholder="Ej. 20123456789"
                inputMode="numeric"
                maxLength={11}
                value={f.ruc}
                readOnly={!puedeCambiarRuc}
                onChange={(e) => setF({ ...f, ruc: e.target.value.replace(/\D/g, '') })}
              />
            )}
          </Campo>
          <Campo etiqueta="Razón social" icono="building" error={errores.razon_social}>
            {(p) => <input {...p} placeholder={puedeEditar ? 'Ej. Mi Empresa S.A.C.' : 'No registrado'} value={f.razon_social} onChange={(e) => setF({ ...f, razon_social: e.target.value })} />}
          </Campo>
          <Campo etiqueta="Nombre comercial" icono="store" error={errores.nombre_comercial}>
            {(p) => <input {...p} placeholder={puedeEditar ? 'Ej. Mi Empresa' : 'No registrado'} value={f.nombre_comercial} onChange={(e) => setF({ ...f, nombre_comercial: e.target.value })} />}
          </Campo>
          <Campo etiqueta="Dirección fiscal" icono="building" error={errores.direccion_fiscal} ayuda="Sale en los comprobantes como domicilio del emisor.">
            {(p) => <input {...p} placeholder={puedeEditar ? 'Ej. Av. Lima 123, Lima' : 'No registrada'} maxLength={250} value={f.direccion_fiscal} onChange={(e) => setF({ ...f, direccion_fiscal: e.target.value })} />}
          </Campo>
          <Campo etiqueta="Teléfono" icono="telefono" error={errores.telefono}>
            {(p) => <input {...p} type="tel" placeholder={puedeEditar ? 'Ej. 999 888 777' : 'No registrado'} maxLength={30} value={f.telefono} onChange={(e) => setF({ ...f, telefono: e.target.value })} />}
          </Campo>
          <Campo etiqueta="Correo" icono="correo" error={errores.correo}>
            {(p) => <input {...p} type="email" placeholder={puedeEditar ? 'Ej. ventas@miempresa.pe' : 'No registrado'} maxLength={150} value={f.correo} onChange={(e) => setF({ ...f, correo: e.target.value })} />}
          </Campo>
          <Campo etiqueta="Página web" icono="documento" error={errores.sitio_web}>
            {(p) => <input {...p} type="url" placeholder={puedeEditar ? 'https://www.miempresa.pe' : 'No registrada'} maxLength={200} value={f.sitio_web} onChange={(e) => setF({ ...f, sitio_web: e.target.value })} />}
          </Campo>
          <Campo etiqueta="Tienda web" icono="store" error={errores.tienda_web} ayuda="La tienda virtual es una sola para el grupo; aquí va su dirección.">
            {(p) => <input {...p} type="url" placeholder={puedeEditar ? 'https://tienda.miempresa.pe' : 'No registrada'} maxLength={200} value={f.tienda_web} onChange={(e) => setF({ ...f, tienda_web: e.target.value })} />}
          </Campo>
          <label className="campo-casilla">
            <input type="checkbox" checked={f.es_principal} onChange={(e) => setF({ ...f, es_principal: e.target.checked })} />
            <span>
              Empresa principal
              <small>Es la cara del grupo: su logo y datos identifican la tienda virtual. Solo una empresa puede serlo.</small>
            </span>
          </label>
          <Campo etiqueta="Estado" icono="settings" tipo="select" error={errores.estado} ayuda="Una empresa inactiva deja de aparecer para sus usuarios.">
            {(p) => (
              <select {...p} value={f.estado} onChange={(e) => setF({ ...f, estado: e.target.value })}>
                <option value="ACTIVO">Activa</option>
                <option value="INACTIVO">Inactiva</option>
                <option value="SUSPENDIDO">Suspendida</option>
              </select>
            )}
          </Campo>
        </fieldset>
        {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
        {puedeEditar && (
          <button type="submit" className="primario" disabled={guardar.isPending || sinCambios}>
            {guardar.isPending ? 'Guardando…' : 'Guardar cambios'}
          </button>
        )}
      </form>
      {confirmandoRuc && (
        <ConfirmarModal
          titulo="Cambiar el RUC"
          mensaje={`El RUC de ${empresa.razon_social} pasará de ${empresa.ruc} a ${f.ruc}. Revisa que sea el RUC correcto: quedará registrado en la auditoría y ya no podrá cambiarse cuando la empresa emita su primer comprobante.`}
          textoConfirmar="Cambiar RUC"
          enviando={guardar.isPending}
          onConfirmar={enviarCambios}
          onCerrar={() => setConfirmandoRuc(false)}
        />
      )}
    </section>
  )
}

export default function EmpresaDetallePage() {
  const { id } = useParams()
  const { tiene } = usePermisos()

  const consulta = useQuery({
    queryKey: ['empresas', 'detalle', id],
    queryFn: ({ signal }) => api.get(`/organizacion/empresas/${id}/`, { signal }).then((r) => r.data),
  })
  const empresa = consulta.data
  const lectura = useModoLectura()
  const gestiona = tiene('SEGURIDAD.EMPRESAS.GESTIONAR', { organizacion: true })
  const { hash } = useLocation()

  // Llegar con #datos (lápiz del listado) baja a esa sección apenas carga la ficha.
  useEffect(() => {
    if (empresa && hash) document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [empresa, hash])

  return (
    <main className="listado">
      <BotonVolver ruta="/seguridad/empresas" texto="Volver a Empresas" />
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(empresa)} vacio="La empresa no existe.">
        {empresa && (
          <>
            <CabeceraListado icono="building" titulo={empresa.razon_social} descripcion={`RUC ${empresa.ruc}${empresa.nombre_comercial ? ` · ${empresa.nombre_comercial}` : ''}`}>
              {empresa.es_principal && <span className="estado-pildora activo">Principal</span>}
              <span className={`estado-pildora ${empresa.estado === 'ACTIVO' ? 'activo' : 'inactivo'}`}>
                {empresa.estado === 'ACTIVO' ? 'Activa' : empresa.estado === 'SUSPENDIDO' ? 'Suspendida' : 'Inactiva'}
              </span>
            </CabeceraListado>
            {lectura && <AvisoLectura puedeEditar={gestiona} />}
            <DatosEmpresa
              key={[empresa.ruc, empresa.razon_social, empresa.nombre_comercial, empresa.estado, empresa.es_principal, ...CAMPOS_FICHA.map((k) => empresa[k])].join('|')}
              empresa={empresa}
              puedeEditar={gestiona && !lectura}
              puedeCambiarRuc={!lectura && gestiona && tiene('SEGURIDAD.ORGANIZACION.GESTIONAR', { organizacion: true })}
            />
            <LogoEmpresa empresa={empresa} puedeEditar={!lectura && gestiona} />
            <ListaSucursales
              empresaId={empresa.id}
              puedeEditar={!lectura && empresa.estado === 'ACTIVO' && tiene('SEGURIDAD.SUCURSALES.GESTIONAR', { organizacion: true })}
            />
          </>
        )}
      </EstadoConsulta>
    </main>
  )
}
