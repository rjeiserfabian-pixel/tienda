import { useQuery } from '@tanstack/react-query'
import { api } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import SelectorUbigeo from '../../../shared/components/SelectorUbigeo'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useConsultaDocumento } from '../../../shared/hooks/useConsultaDocumento'
import { limpiarDocumento, REGLA_DOCUMENTO } from '../maestros'
import './maestros.css'

/** Select cuyas opciones vienen del servidor y dependen de otro campo (p. ej. las sucursales de la empresa elegida). */
function SelectRemoto({ c, valores, registro, comun, valor, lectura, alCambiar }) {
  const fuente = c.fuente(valores, registro)
  const consulta = useQuery({
    queryKey: ['opciones', c.nombre, fuente?.url, fuente?.params],
    queryFn: ({ signal }) => api.get(fuente.url, { params: fuente.params, signal }).then((r) => r.data.results),
    enabled: Boolean(fuente) && !lectura,
    staleTime: 30_000,
  })
  const excluido = c.excluir?.(registro)
  const lista = (consulta.data ?? []).filter((x) => x.id !== excluido)
  const actual = valor && !lista.some((x) => String(x.id) === String(valor))
  // Si la lista llegó vacía se explica qué hacer (p. ej. «crea primero un grupo»).
  const sinOpciones = Boolean(fuente) && consulta.isSuccess && lista.length === 0
  const vacio = lectura ? 'No registrado' : sinOpciones && c.vacioSinOpciones ? c.vacioSinOpciones : fuente ? c.vacio : (c.vacioSinFuente ?? c.vacio)
  return (
    <select {...comun} value={valor} disabled={comun.disabled || (!fuente && !lectura)} onChange={(e) => alCambiar(e.target.value)}>
      <option value="">{vacio}</option>
      {actual && <option value={valor}>{registro?.[c.etiquetaDe] || 'Actual'}</option>}
      {lista.map((x) => (
        <option key={x.id} value={String(x.id)}>{c.etiquetaOpcion(x)}</option>
      ))}
    </select>
  )
}

const HOY = new Date().toISOString().slice(0, 10) // tope de las fechas de nacimiento

/**
 * Formulario de un maestro a partir de su configuración. Lo usan el alta (modal) y la ficha.
 * En consulta (`lectura`) un campo vacío dice «No registrado» en vez de mostrar el ejemplo,
 * para que el ejemplo en gris no se confunda con un dato real.
 */
export default function CamposMaestro({ config, valores, errores, onCambio, deshabilitado, registro, lectura = false, alta = false }) {
  const { empresas } = useEmpresas()
  const { tiene } = usePermisos()
  const { consultando, mensaje: consulta, consultar: pedir, avisar, limpiar } = useConsultaDocumento()

  const campos = config.campos.filter((c) => (alta ? !c.soloEdicion : !c.soloAlta) && (!c.visibleSi || c.visibleSi(valores, registro)) && (!c.soloConPermiso || tiene(c.soloConPermiso, { organizacion: true })))
  const campoUsuario = campos.find((c) => c.tipo === 'usuario')
  // Algunos campos de usuario (el asesor) solo los elige quien tiene el permiso; los demás ven el automático.
  const puedeElegirUsuario = Boolean(campoUsuario) && (!campoUsuario.permiso || tiene(campoUsuario.permiso, { organizacion: true }))
  const puedeVerUsuarios = tiene('SEGURIDAD.USUARIOS.VER', { organizacion: true })
  const usuarios = useQuery({
    queryKey: ['usuarios', 'para-vincular'],
    queryFn: ({ signal }) =>
      api.get('/seguridad/usuarios/', { params: { page_size: 100, activo: true }, signal }).then((r) => r.data.results),
    enabled: puedeElegirUsuario && puedeVerUsuarios && !lectura,
    staleTime: 60_000,
  })

  const consultaDeEste = config.consulta?.[valores.tipo_documento]
  const puedeConsultar = !lectura && !deshabilitado && Boolean(consultaDeEste) && tiene('MANTENIMIENTO.CONSULTAS.USAR', { organizacion: true })

  const cambiar = (campo, valor) => {
    onCambio(campo, valor)
    // Al cambiar el tipo de documento se ajusta el número ya escrito (largo y caracteres).
    if (campo === 'empresa') {
      // Lo que depende de la empresa (sucursal, responsable) se elige de nuevo.
      onCambio('sucursal', '')
      onCambio('responsable', '')
    }
    if (campo === 'tipo_documento') {
      onCambio('numero_documento', limpiarDocumento(valor, valores.numero_documento))
      limpiar()
    }
  }

  // Completa el formulario con los datos públicos (RENIEC/SUNAT). Solo rellena: se revisa antes de guardar.
  const consultar = async () => {
    const tipo = valores.tipo_documento
    const regla = REGLA_DOCUMENTO[tipo]
    const numero = valores.numero_documento
    if (!numero || numero.length !== regla.largo) {
      avisar(`Escribe los ${regla.largo} dígitos del ${tipo} antes de consultar.`)
      return
    }
    const datos = await pedir(tipo, numero)
    if (datos) for (const [campo, valor] of Object.entries(consultaDeEste(datos))) onCambio(campo, valor)
  }

  const control = (c, p) => {
    const comun = { ...p, name: c.nombre, disabled: deshabilitado }
    const valor = valores[c.nombre] ?? ''
    const vacio = lectura ? 'No registrado' : c.placeholder
    if (c.tipo === 'usuario' && !puedeElegirUsuario) {
      const texto = alta ? 'Se asignará a tu usuario' : registro?.[c.etiquetaDe] || 'Sin asesor'
      return <input {...comun} value={texto} readOnly disabled />
    }
    if (c.tipo === 'usuario') {
      const lista = usuarios.data ?? []
      const actual = valor && !lista.some((u) => u.id === valor)
      return (
        <select {...comun} value={valor} disabled={deshabilitado || !puedeVerUsuarios} onChange={(e) => cambiar(c.nombre, e.target.value)}>
          <option value="">{lectura ? 'Sin usuario' : (alta ? c.vacio : c.vacioEdicion) ?? 'Sin usuario (opcional)'}</option>
          {actual && <option value={valor}>{registro?.[c.etiquetaDe] || 'Usuario vinculado'}</option>}
          {lista.map((u) => (
            <option key={u.id} value={u.id}>
              {u.username} — {[u.nombres, u.apellidos].filter(Boolean).join(' ') || u.email}
            </option>
          ))}
        </select>
      )
    }
    if (c.tipo === 'ubigeo') {
      return <SelectorUbigeo {...p} name={c.nombre} valor={valor} lectura={lectura} disabled={deshabilitado} onCambio={(v) => cambiar(c.nombre, v)} />
    }
    if (c.tipo === 'remoto') {
      return <SelectRemoto c={c} valores={valores} registro={registro} comun={comun} valor={valor} lectura={lectura} alCambiar={(v) => cambiar(c.nombre, v)} />
    }
    if (c.tipo === 'booleano') {
      return (
        <select {...comun} value={valor} onChange={(e) => cambiar(c.nombre, e.target.value)}>
          <option value="true">Sí</option>
          <option value="false">No</option>
        </select>
      )
    }
    if (c.tipo === 'select') {
      const opciones = c.empresas
        ? empresas.map((e) => [String(e.id), e.nombre_comercial || e.razon_social])
        : c.opciones
      return (
        <select {...comun} value={valor} onChange={(e) => cambiar(c.nombre, e.target.value)}>
          {c.empresas && <option value="">Elija la empresa</option>}
          {c.vacio && !c.empresas && <option value="">{lectura ? 'No registrado' : c.vacio}</option>}
          {opciones.map(([v, texto]) => (
            <option key={v} value={v}>{texto}</option>
          ))}
        </select>
      )
    }
    if (c.tipo === 'textarea') {
      return <textarea {...comun} rows={3} value={valor} maxLength={c.maxLength} placeholder={vacio} onChange={(e) => cambiar(c.nombre, e.target.value)} />
    }
    if (c.documento) {
      const regla = REGLA_DOCUMENTO[valores.tipo_documento] ?? REGLA_DOCUMENTO.OTRO
      return (
        <input
          {...comun}
          value={valor}
          inputMode={regla.soloDigitos ? 'numeric' : 'text'}
          maxLength={regla.largo}
          placeholder={lectura ? vacio : regla.ejemplo}
          autoComplete="off"
          onChange={(e) => cambiar(c.nombre, limpiarDocumento(valores.tipo_documento, e.target.value))}
        />
      )
    }
    return (
      <input
        {...comun}
        type={c.tipo ?? 'text'}
        value={valor}
        maxLength={c.maxLength}
        max={c.max === 'hoy' ? HOY : undefined}
        min={c.tipo === 'date' && c.max === 'hoy' ? '1900-01-01' : undefined}
        placeholder={vacio}
        onChange={(e) => cambiar(c.nombre, c.transformar ? c.transformar(e.target.value) : e.target.value)}
      />
    )
  }

  const boton = (
    <button type="button" className="boton-consultar" onClick={consultar} disabled={consultando} title="Completar con los datos de RENIEC o SUNAT">
      <Icono nombre="buscar" tam={17} /> {consultando ? 'Consultando…' : 'Consultar'}
    </button>
  )

  return (
    <div className="maestro-campos">
      {campos.map((c) => {
        const esDocumento = Boolean(c.documento)
        const ayudaUsuario = c.tipo === 'usuario' && puedeElegirUsuario && !puedeVerUsuarios && !lectura ? 'Necesitas permiso para ver usuarios para poder vincular uno.' : c.ayuda
        return (
          <div key={c.nombre} className={c.completo ? 'completo' : undefined}>
            <Campo
              etiqueta={c.etiqueta}
              icono={c.icono}
              requerido={c.requerido && !lectura}
              tipo={['select', 'usuario', 'remoto', 'booleano'].includes(c.tipo) ? 'select' : undefined}
              error={errores[c.nombre] || (esDocumento ? consulta.error : '')}
              ayuda={esDocumento && consulta.ok ? consulta.ok : lectura ? undefined : ayudaUsuario}
              derecha={esDocumento && puedeConsultar ? boton : undefined}
              contador={c.tipo === 'textarea' && c.maxLength && !lectura ? { actual: (valores[c.nombre] ?? '').length, max: c.maxLength } : undefined}
            >
              {(p) => control(c, p)}
            </Campo>
          </div>
        )
      })}
    </div>
  )
}
