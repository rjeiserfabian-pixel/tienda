'use client'

import { useId, useState } from 'react'
import { ErrorTienda, errorDeCampo, llamar } from '@/lib/cliente'
import SelectorUbigeo from './SelectorUbigeo'

/**
 * Formulario de una dirección de entrega (nueva o para editar).
 * Guarda con la API de la cuenta y devuelve a `alGuardar` la lista completa de direcciones.
 */
export default function DireccionForm({ inicial = null, celularSugerido = '', nombreSugerido = '', alGuardar, alCancelar }) {
  const id = useId()
  const editando = Boolean(inicial?.id)
  const [datos, setDatos] = useState({
    etiqueta: inicial?.etiqueta ?? '',
    receptor: inicial?.receptor ?? nombreSugerido,
    celular: inicial?.celular ?? celularSugerido,
    ubigeo: inicial?.ubigeo ?? '',
    direccion: inicial?.direccion ?? '',
    referencia: inicial?.referencia ?? '',
    es_principal: inicial?.es_principal ?? false,
  })
  const [error, setError] = useState(null)
  const [enviando, setEnviando] = useState(false)

  const poner = (campo) => (e) => setDatos((d) => ({ ...d, [campo]: e.target.value }))

  async function enviar(e) {
    e.preventDefault()
    setError(null)
    if (!datos.ubigeo) {
      setError(new ErrorTienda(400, 'datos_invalidos', 'Elige el departamento, la provincia y el distrito.', { ubigeo: ['Elige el distrito.'] }))
      return
    }
    setEnviando(true)
    try {
      const lista = await llamar(editando ? `cuenta/direcciones/${inicial.id}` : 'cuenta/direcciones', {
        metodo: editando ? 'PATCH' : 'POST',
        cuerpo: datos,
      })
      alGuardar(lista)
    } catch (err) {
      setError(err instanceof ErrorTienda ? err : new ErrorTienda(0, 'error', 'No pudimos guardar la dirección.'))
    } finally {
      setEnviando(false)
    }
  }

  const f = (campo) => errorDeCampo(error, campo)
  const hayErrorGeneral = error && !error.campos

  return (
    <form className="form" onSubmit={enviar} noValidate>
      {hayErrorGeneral && (
        <p className="alerta error" role="alert">
          {error.message}
        </p>
      )}
      <div className="form-fila dos">
        <div className="campo">
          <label htmlFor={`${id}-receptor`}>Quién recibe</label>
          <input id={`${id}-receptor`} value={datos.receptor} onChange={poner('receptor')} autoComplete="name" maxLength={150} required aria-invalid={f('receptor') ? 'true' : undefined} />
          {f('receptor') && <span className="campo-error">{f('receptor')}</span>}
        </div>
        <div className="campo">
          <label htmlFor={`${id}-celular`}>Celular de contacto</label>
          <input id={`${id}-celular`} value={datos.celular} onChange={poner('celular')} type="tel" inputMode="tel" autoComplete="tel" maxLength={20} required aria-invalid={f('celular') ? 'true' : undefined} />
          {f('celular') && <span className="campo-error">{f('celular')}</span>}
        </div>
      </div>
      <SelectorUbigeo valor={datos.ubigeo} onChange={(u) => setDatos((d) => ({ ...d, ubigeo: u }))} error={f('ubigeo')} />
      <div className="campo">
        <label htmlFor={`${id}-direccion`}>Dirección</label>
        <input id={`${id}-direccion`} value={datos.direccion} onChange={poner('direccion')} autoComplete="street-address" maxLength={250} placeholder="Calle o avenida, número, piso o dpto." required aria-invalid={f('direccion') ? 'true' : undefined} />
        {f('direccion') && <span className="campo-error">{f('direccion')}</span>}
      </div>
      <div className="form-fila dos">
        <div className="campo">
          <label htmlFor={`${id}-referencia`}>
            Referencia <span className="campo-opcional">(opcional)</span>
          </label>
          <input id={`${id}-referencia`} value={datos.referencia} onChange={poner('referencia')} maxLength={200} placeholder="Ej.: frente al parque, portón negro" />
        </div>
        <div className="campo">
          <label htmlFor={`${id}-etiqueta`}>
            Nombre de la dirección <span className="campo-opcional">(opcional)</span>
          </label>
          <input id={`${id}-etiqueta`} value={datos.etiqueta} onChange={poner('etiqueta')} maxLength={40} placeholder="Ej.: Casa, Oficina" />
        </div>
      </div>
      <label className="campo-check">
        <input type="checkbox" checked={datos.es_principal} onChange={(e) => setDatos((d) => ({ ...d, es_principal: e.target.checked }))} />
        <span>Usar como mi dirección principal</span>
      </label>
      <div className="form-acciones">
        <button type="submit" className="boton" disabled={enviando}>
          {enviando ? 'Guardando…' : editando ? 'Guardar cambios' : 'Guardar dirección'}
        </button>
        {alCancelar && (
          <button type="button" className="boton secundario" onClick={alCancelar} disabled={enviando}>
            Cancelar
          </button>
        )}
      </div>
    </form>
  )
}
