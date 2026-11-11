import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import { useAuth } from '../../../core/auth/AuthContext'
import Campo from '../../../shared/components/Campo'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import Interruptor from '../../../shared/components/Interruptor'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useMutacion } from '../../../shared/hooks/useMutacion'

const OPCIONES_PRECIO = {
  UTILIDAD: {
    titulo: 'Utilidad (sobre el costo)',
    detalle: 'El porcentaje se calcula sobre lo que te costó: precio = costo × (1 + utilidad).',
    ejemplo: 'Con utilidad 25 % el precio es S/ 112.50 (90 × 1.25).',
  },
  MARGEN: {
    titulo: 'Margen (sobre el precio)',
    detalle: 'El porcentaje se calcula sobre lo que cobras: precio = costo ÷ (1 − margen).',
    ejemplo: 'Con margen 25 % el precio es S/ 120.00 (90 ÷ 0.75).',
  },
}

function Formulario({ organizacion }) {
  const { renovarSesion } = useAuth()
  const [f, setF] = useState({ nombre: organizacion.nombre, mfa_obligatorio: organizacion.mfa_obligatorio, calculo_precios: organizacion.calculo_precios })
  const [errores, setErrores] = useState({})

  const guardar = useMutacion({
    mutationFn: async (datos) => {
      const { data } = await api.patch('/organizacion/', datos)
      await renovarSesion() // el usuario puede quedar obligado a activar su verificación
      return data
    },
    invalidar: [['organizacion'], ['mfa'], ['productos']],
    exito: 'Organización actualizada.',
    avisarError: false,
  })
  const sinCambios = f.nombre === organizacion.nombre && f.mfa_obligatorio === organizacion.mfa_obligatorio && f.calculo_precios === organizacion.calculo_precios

  return (
    <form
      noValidate
      className="pagina-formulario"
      onSubmit={(e) => {
        e.preventDefault()
        if (guardar.isPending || sinCambios) return
        if (!f.nombre.trim()) return setErrores({ nombre: 'Ingrese el nombre.' })
        setErrores({})
        guardar.mutate(f, { onError: (error) => setErrores({ general: mensajeDeError(error), ...erroresDeCampo(error) }) })
      }}
    >
      <PanelTarjeta icono="building" titulo="Datos generales" descripcion="Cómo se identifica tu organización en el sistema.">
        <div className="formulario-ancho">
          <Campo etiqueta="Nombre de la organización" requerido icono="building" error={errores.nombre}>
            {(p) => <input {...p} placeholder="Ej. Grupo Mi Empresa" value={f.nombre} maxLength={200} onChange={(e) => setF({ ...f, nombre: e.target.value })} disabled={guardar.isPending} />}
          </Campo>
        </div>
      </PanelTarjeta>

      <PanelTarjeta icono="coins" titulo="Precios de venta" descripcion="Cómo piensas tu ganancia al poner precios. Cambiarlo no modifica ningún precio ya guardado: solo cambia el porcentaje que escribes y ves.">
        <div className="segmentos" role="radiogroup" aria-label="Cómo se calcula el precio de venta">
          {Object.entries(OPCIONES_PRECIO).map(([valor, { titulo }]) => (
            <button key={valor} type="button" role="radio" aria-checked={f.calculo_precios === valor} className={f.calculo_precios === valor ? 'activo' : undefined} disabled={guardar.isPending} onClick={() => setF({ ...f, calculo_precios: valor })}>
              {titulo}
            </button>
          ))}
        </div>
        <p className="campo-ayuda">{OPCIONES_PRECIO[f.calculo_precios].detalle}</p>
        <p className="campo-ayuda" style={{ marginBottom: 0 }}>
          Ejemplo: compras a S/ 90 y quieres ganar el 25 %. {OPCIONES_PRECIO[f.calculo_precios].ejemplo}
        </p>
      </PanelTarjeta>

      <PanelTarjeta icono="shield" titulo="Políticas de seguridad" descripcion="Reglas que se aplican a todos los usuarios de la organización.">
        <Interruptor
          activo={f.mfa_obligatorio}
          onCambio={(v) => setF({ ...f, mfa_obligatorio: v })}
          disabled={guardar.isPending}
          texto="Exigir verificación en dos pasos"
          descripcion="Quien no la tenga activa deberá configurarla antes de poder seguir operando."
        />
        {f.mfa_obligatorio && !organizacion.mfa_obligatorio && (
          <p className="campo-ayuda" style={{ marginBottom: 0 }}>
            Al guardar, esto también te incluye a ti: se te pedirá activar la verificación en tu cuenta.
          </p>
        )}
      </PanelTarjeta>

      {errores.general && <p role="alert" className="campo-error">{errores.general}</p>}
      <div className="fila-botones">
        <button type="button" className="boton-cabecera" disabled={guardar.isPending || sinCambios} onClick={() => { setF({ nombre: organizacion.nombre, mfa_obligatorio: organizacion.mfa_obligatorio, calculo_precios: organizacion.calculo_precios }); setErrores({}) }}>
          <Icono nombre="cerrar" tam={18} /> Descartar
        </button>
        <button type="submit" className="primario boton-cabecera" disabled={guardar.isPending || sinCambios}>
          <Icono nombre="shield" tam={19} /> {guardar.isPending ? 'Guardando…' : 'Guardar cambios'}
        </button>
      </div>
    </form>
  )
}

export default function OrganizacionPage() {
  const consulta = useQuery({
    queryKey: ['organizacion'],
    queryFn: ({ signal }) => api.get('/organizacion/', { signal }).then((r) => r.data),
  })
  const organizacion = consulta.data

  return (
    <main className="listado">
      <CabeceraListado icono="settings" titulo="Organización" descripcion="Datos generales y políticas de seguridad de tu organización." />
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(organizacion)}>
        {organizacion && <Formulario key={organizacion.nombre + organizacion.mfa_obligatorio + organizacion.calculo_precios} organizacion={organizacion} />}
      </EstadoConsulta>
    </main>
  )
}
