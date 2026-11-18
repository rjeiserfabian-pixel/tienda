'use client'

import { useRef, useState } from 'react'
import { ErrorTienda, llamar } from '@/lib/cliente'
import { soles } from '@/lib/format'
import Icono from './Icono'

const MAX_BYTES = 8 * 1024 * 1024

/** Un dato de la cuenta con un botón para copiarlo (se pega en la app del banco). */
function Dato({ etiqueta, valor }) {
  const [copiado, setCopiado] = useState(false)
  if (!valor) return null
  async function copiar() {
    try {
      await navigator.clipboard.writeText(valor)
      setCopiado(true)
      setTimeout(() => setCopiado(false), 1800)
    } catch {
      // sin permiso para el portapapeles: el dato sigue visible para copiarlo a mano
    }
  }
  return (
    <div className="tr-dato">
      <dt>{etiqueta}</dt>
      <dd>
        <span>{valor}</span>
        <button type="button" className="enlace" onClick={copiar} aria-label={`Copiar ${etiqueta}`}>
          {copiado ? 'Copiado' : 'Copiar'}
        </button>
      </dd>
    </div>
  )
}

/**
 * Pedido pagado por transferencia o depósito: a qué cuenta pagar y dónde subir el comprobante.
 * Mientras el equipo lo verifica solo se muestra el aviso de espera.
 */
export default function TransferenciaPedido({ pedido, alCambiar }) {
  const t = pedido.transferencia
  const [archivo, setArchivo] = useState(null)
  const [operacion, setOperacion] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState(null)
  const entrada = useRef(null)
  if (!t) return null
  const total = pedido.forma_pago?.cobrado_ahora ?? pedido.total
  const cuenta = t.cuenta

  function elegir(evento) {
    setError(null)
    const f = evento.target.files?.[0] ?? null
    if (f && f.size > MAX_BYTES) {
      setArchivo(null)
      setError('La foto pesa más de 8 MB. Prueba con una más liviana.')
      return
    }
    setArchivo(f)
  }

  async function subir(evento) {
    evento.preventDefault()
    if (!archivo) {
      setError('Elige la foto o captura de tu comprobante.')
      return
    }
    setEnviando(true)
    setError(null)
    const formulario = new FormData()
    formulario.append('imagen', archivo)
    if (operacion.trim()) formulario.append('operacion', operacion.trim())
    try {
      alCambiar(await llamar(`pedidos/${encodeURIComponent(pedido.numero)}/voucher`, { metodo: 'POST', cuerpo: formulario }))
      setArchivo(null)
      setOperacion('')
      if (entrada.current) entrada.current.value = ''
    } catch (e) {
      setError(e instanceof ErrorTienda ? e.message : 'No pudimos enviar tu comprobante. Inténtalo de nuevo.')
    } finally {
      setEnviando(false)
    }
  }

  if (pedido.estado === 'POR_VERIFICAR') {
    return (
      <section className="alerta ok tr-espera" role="status" aria-labelledby="tr-espera-t">
        <Icono nombre="reloj" tam={20} />
        <div>
          <h2 id="tr-espera-t">Recibimos tu comprobante</h2>
          <p>
            Estamos verificando tu transferencia de <strong>{soles(total)}</strong>. Apenas la confirmemos te avisaremos por correo y empezaremos con tu pedido.
          </p>
          {t.operacion && <p className="com-chico">N.º de operación: {t.operacion}</p>}
        </div>
      </section>
    )
  }

  return (
    <section className="com-paso tr" aria-labelledby="tr-t">
      <h2 id="tr-t">Paga por transferencia o depósito</h2>
      {t.rechazo && (
        <p className="alerta error" role="alert">
          <Icono nombre="info" tam={18} />
          <span>
            No pudimos verificar tu pago: <strong>{t.rechazo}</strong> Sube un comprobante nuevo.
          </span>
        </p>
      )}
      <p>
        Transfiere <strong>{soles(total)}</strong> a esta cuenta y luego sube la foto de tu comprobante. Guardamos tus productos hasta el{' '}
        <strong>{new Date(pedido.expira_en).toLocaleString('es-PE', { dateStyle: 'medium', timeStyle: 'short' })}</strong>.
      </p>
      {cuenta && (
        <dl className="tr-cuenta">
          <Dato etiqueta="Banco" valor={cuenta.banco || cuenta.nombre} />
          <Dato etiqueta="Titular" valor={cuenta.titular} />
          <Dato etiqueta="RUC" valor={cuenta.ruc} />
          <Dato etiqueta="N.º de cuenta" valor={cuenta.numero} />
          <Dato etiqueta="CCI" valor={cuenta.cci} />
        </dl>
      )}
      {t.instrucciones && <p className="com-chico">{t.instrucciones}</p>}
      <form onSubmit={subir} className="tr-form" noValidate>
        <div className="campo">
          <label htmlFor="tr-foto">Foto o captura de tu comprobante</label>
          <input ref={entrada} id="tr-foto" type="file" accept="image/jpeg,image/png,image/webp" onChange={elegir} aria-describedby={error ? 'tr-error' : undefined} />
        </div>
        <div className="campo">
          <label htmlFor="tr-operacion">N.º de operación (opcional)</label>
          <input id="tr-operacion" value={operacion} onChange={(e) => setOperacion(e.target.value)} maxLength={40} autoComplete="off" />
        </div>
        {error && (
          <p id="tr-error" className="campo-error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="boton grande" disabled={enviando || !archivo}>
          {enviando ? 'Enviando…' : 'Enviar mi comprobante'}
        </button>
      </form>
    </section>
  )
}
