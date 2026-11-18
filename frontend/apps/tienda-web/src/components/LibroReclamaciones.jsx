'use client'

import { useState } from 'react'
import { ErrorTienda, errorDeCampo, llamar } from '@/lib/cliente'
import Icono from './Icono'
import { useCuenta } from './Proveedores'

const INICIAL = {
  tipo: 'RECLAMO',
  nombre: '',
  documento_tipo: 'DNI',
  documento_numero: '',
  domicilio: '',
  telefono: '',
  correo: '',
  menor_de_edad: false,
  apoderado: '',
  bien_tipo: 'PRODUCTO',
  monto: '',
  bien_descripcion: '',
  pedido_numero: '',
  detalle: '',
  pedido_consumidor: '',
}

const fecha = (iso) => new Date(iso).toLocaleDateString('es-PE', { day: 'numeric', month: 'long', year: 'numeric' })

/** Hoja de reclamación del Libro de Reclamaciones virtual. */
export default function LibroReclamaciones({ libro }) {
  const cuenta = useCuenta()
  const empresas = libro?.empresas ?? []
  const [form, setForm] = useState(() => ({ ...INICIAL, empresa: empresas[0]?.id ?? '' }))
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState(null)
  const [hecho, setHecho] = useState(null)

  // Con sesión iniciada se proponen el nombre y el correo (se pueden cambiar).
  const perfil = cuenta?.perfil
  const nombrePropuesto = [perfil?.nombres, perfil?.apellidos].filter(Boolean).join(' ')
  const valor = (campo) => (form[campo] === '' && campo === 'nombre' ? nombrePropuesto : form[campo] === '' && campo === 'correo' ? (perfil?.correo ?? '') : form[campo])
  const poner = (campo) => (e) => setForm((f) => ({ ...f, [campo]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))

  async function enviar(evento) {
    evento.preventDefault()
    setEnviando(true)
    setError(null)
    try {
      const cuerpo = { ...form, nombre: valor('nombre'), correo: valor('correo'), empresa: Number(form.empresa), monto: form.monto || null }
      setHecho(await llamar('reclamos', { metodo: 'POST', cuerpo }))
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (e) {
      setError(e instanceof ErrorTienda ? e : new ErrorTienda(0, 'error', 'No pudimos registrar tu hoja. Inténtalo de nuevo.'))
    } finally {
      setEnviando(false)
    }
  }

  if (hecho) {
    return (
      <section className="tarjeta-centrada" role="status" aria-labelledby="lib-ok-t">
        <span className="ped-check" aria-hidden="true">
          <Icono nombre="check" tam={30} />
        </span>
        <h1 id="lib-ok-t">Registramos tu {hecho.tipo === 'QUEJA' ? 'queja' : 'reclamo'}</h1>
        <p className="sub">
          Tu hoja de reclamación es la N.º <strong>{hecho.numero}</strong>. Te enviamos una constancia a <strong>{hecho.correo}</strong>.
        </p>
        <p className="sub">Te responderemos a ese correo a más tardar el {fecha(hecho.vence_en)} ({libro.plazo_dias_habiles} días hábiles).</p>
      </section>
    )
  }

  const e = (campo) => (error ? errorDeCampo(error, campo) : undefined)

  return (
    <form className="lib-form" onSubmit={enviar} noValidate>
      <h1 className="titulo-pagina">Libro de Reclamaciones</h1>
      <p className="sub">
        Completa tu hoja de reclamación. Te enviaremos una constancia por correo y te responderemos en un máximo de {libro.plazo_dias_habiles} días hábiles. Los campos con * son obligatorios.
      </p>

      <fieldset className="lib-bloque">
        <legend>1. Proveedor</legend>
        {empresas.length > 1 ? (
          <div className="campo">
            <label htmlFor="lib-empresa">¿Contra qué empresa es? *</label>
            <select id="lib-empresa" value={form.empresa} onChange={poner('empresa')}>
              {empresas.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.razon_social} · RUC {x.ruc}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <p>
            <strong>{empresas[0]?.razon_social}</strong> · RUC {empresas[0]?.ruc}
            {empresas[0]?.direccion ? ` · ${empresas[0].direccion}` : ''}
          </p>
        )}
      </fieldset>

      <fieldset className="lib-bloque">
        <legend>2. Tus datos</legend>
        <div className="campo">
          <label htmlFor="lib-nombre">Nombres y apellidos *</label>
          <input id="lib-nombre" value={valor('nombre')} onChange={poner('nombre')} maxLength={150} autoComplete="name" />
        </div>
        <div className="lib-fila">
          <div className="campo">
            <label htmlFor="lib-doc-tipo">Documento *</label>
            <select id="lib-doc-tipo" value={form.documento_tipo} onChange={poner('documento_tipo')}>
              <option value="DNI">DNI</option>
              <option value="CE">Carné de extranjería</option>
              <option value="PASAPORTE">Pasaporte</option>
              <option value="RUC">RUC</option>
            </select>
          </div>
          <div className="campo">
            <label htmlFor="lib-doc-num">Número *</label>
            <input id="lib-doc-num" value={form.documento_numero} onChange={poner('documento_numero')} maxLength={20} inputMode="numeric" autoComplete="off" />
          </div>
        </div>
        <div className="campo">
          <label htmlFor="lib-domicilio">Domicilio *</label>
          <input id="lib-domicilio" value={form.domicilio} onChange={poner('domicilio')} maxLength={250} autoComplete="street-address" />
        </div>
        <div className="lib-fila">
          <div className="campo">
            <label htmlFor="lib-correo">Correo electrónico *</label>
            <input id="lib-correo" type="email" value={valor('correo')} onChange={poner('correo')} maxLength={150} autoComplete="email" />
          </div>
          <div className="campo">
            <label htmlFor="lib-tel">Teléfono</label>
            <input id="lib-tel" value={form.telefono} onChange={poner('telefono')} maxLength={30} inputMode="tel" autoComplete="tel" />
          </div>
        </div>
        <label className="lib-check">
          <input type="checkbox" checked={form.menor_de_edad} onChange={poner('menor_de_edad')} /> Soy menor de edad
        </label>
        {form.menor_de_edad && (
          <div className="campo">
            <label htmlFor="lib-apoderado">Nombre del padre, madre o apoderado *</label>
            <input id="lib-apoderado" value={form.apoderado} onChange={poner('apoderado')} maxLength={150} />
          </div>
        )}
      </fieldset>

      <fieldset className="lib-bloque">
        <legend>3. Producto o servicio</legend>
        <div className="lib-fila">
          <div className="campo">
            <label htmlFor="lib-bien">Se trata de un *</label>
            <select id="lib-bien" value={form.bien_tipo} onChange={poner('bien_tipo')}>
              <option value="PRODUCTO">Producto</option>
              <option value="SERVICIO">Servicio</option>
            </select>
          </div>
          <div className="campo">
            <label htmlFor="lib-monto">Monto reclamado (S/)</label>
            <input id="lib-monto" value={form.monto} onChange={poner('monto')} inputMode="decimal" maxLength={12} />
          </div>
        </div>
        <div className="campo">
          <label htmlFor="lib-desc">Descripción del producto o servicio *</label>
          <input id="lib-desc" value={form.bien_descripcion} onChange={poner('bien_descripcion')} maxLength={300} />
        </div>
        <div className="campo">
          <label htmlFor="lib-pedido">Número de pedido (si lo tienes)</label>
          <input id="lib-pedido" value={form.pedido_numero} onChange={poner('pedido_numero')} maxLength={20} placeholder="T-000123" />
        </div>
      </fieldset>

      <fieldset className="lib-bloque">
        <legend>4. Tu reclamo o queja</legend>
        <div className="lib-tipos" role="radiogroup" aria-label="Tipo">
          <label className={`com-opcion${form.tipo === 'RECLAMO' ? ' activa' : ''}`}>
            <input type="radio" name="lib-tipo" checked={form.tipo === 'RECLAMO'} onChange={() => setForm((f) => ({ ...f, tipo: 'RECLAMO' }))} />
            <span>
              <strong>Reclamo</strong>
              <small>Disconformidad con el producto o servicio.</small>
            </span>
          </label>
          <label className={`com-opcion${form.tipo === 'QUEJA' ? ' activa' : ''}`}>
            <input type="radio" name="lib-tipo" checked={form.tipo === 'QUEJA'} onChange={() => setForm((f) => ({ ...f, tipo: 'QUEJA' }))} />
            <span>
              <strong>Queja</strong>
              <small>Malestar por la atención recibida.</small>
            </span>
          </label>
        </div>
        <div className="campo">
          <label htmlFor="lib-detalle">Detalle *</label>
          <textarea id="lib-detalle" rows={5} value={form.detalle} onChange={poner('detalle')} maxLength={2000} />
          <small className="com-chico">{form.detalle.length}/2000</small>
        </div>
        <div className="campo">
          <label htmlFor="lib-pide">¿Qué solución pides? *</label>
          <textarea id="lib-pide" rows={3} value={form.pedido_consumidor} onChange={poner('pedido_consumidor')} maxLength={1000} />
        </div>
      </fieldset>

      {error && (
        <p className="alerta error" role="alert">
          <Icono nombre="info" tam={18} />
          <span>{e('detalle') || error.message}</span>
        </p>
      )}
      <p className="com-chico">
        La formulación del reclamo no impide acudir a otras vías de solución de controversias ni es requisito previo para interponer una denuncia ante INDECOPI.
      </p>
      <button type="submit" className="boton grande" disabled={enviando}>
        {enviando ? 'Enviando…' : 'Enviar mi hoja de reclamación'}
      </button>
    </form>
  )
}
