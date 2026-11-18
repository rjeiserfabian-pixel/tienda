'use client'

import { useRouter } from 'next/navigation'
import { useId, useState } from 'react'
import { ErrorTienda, llamar } from '@/lib/cliente'
import { extraerToken } from '@/lib/garantia'
import Icono from '../Icono'

/**
 * «Consulta tu garantía»: con la serie (o IMEI) del producto y el documento de quien compró, o con el
 * código o enlace del QR del certificado. Hay que acertar serie y documento a la vez.
 */
export default function ConsultaGarantia() {
  const router = useRouter()
  const id = useId()
  const [modo, setModo] = useState('serie')
  const [serie, setSerie] = useState('')
  const [documento, setDocumento] = useState('')
  const [codigo, setCodigo] = useState('')
  const [error, setError] = useState(null)
  const [buscando, setBuscando] = useState(false)

  async function enviar(e) {
    e.preventDefault()
    setError(null)
    if (modo === 'codigo') {
      const token = extraerToken(codigo)
      if (!token) return setError('Ese código no parece válido. Escribe el código del certificado o pega el enlace de su QR.')
      setBuscando(true)
      return router.push(`/garantia/${encodeURIComponent(token)}`)
    }
    if (serie.trim().length < 3 || documento.trim().length < 6) {
      return setError('Escribe la serie o IMEI del producto y el DNI o RUC con el que compraste.')
    }
    setBuscando(true)
    try {
      const { token } = await llamar('garantia/buscar', { metodo: 'POST', cuerpo: { serie: serie.trim(), documento: documento.trim() } })
      router.push(`/garantia/${encodeURIComponent(token)}`)
    } catch (fallo) {
      setBuscando(false)
      setError(fallo instanceof ErrorTienda && fallo.estado === 404 ? 'No encontramos una garantía con esos datos. Revisa la serie y el documento.' : fallo.message)
    }
  }

  return (
    <form className="form st-consulta" onSubmit={enviar} noValidate>
      <div className="st-segmentos" role="radiogroup" aria-label="Cómo quieres consultar">
        <button type="button" role="radio" aria-checked={modo === 'serie'} className={modo === 'serie' ? 'activo' : undefined} onClick={() => setModo('serie')}>
          Con la serie y mi documento
        </button>
        <button type="button" role="radio" aria-checked={modo === 'codigo'} className={modo === 'codigo' ? 'activo' : undefined} onClick={() => setModo('codigo')}>
          Con el código del certificado
        </button>
      </div>
      {modo === 'serie' ? (
        <>
          <div className="campo">
            <label htmlFor={`${id}-serie`}>Serie o IMEI del producto</label>
            <input id={`${id}-serie`} value={serie} onChange={(e) => setSerie(e.target.value)} maxLength={40} autoComplete="off" autoCapitalize="characters" spellCheck={false} required />
          </div>
          <div className="campo">
            <label htmlFor={`${id}-documento`}>DNI o RUC con el que compraste</label>
            <input id={`${id}-documento`} value={documento} onChange={(e) => setDocumento(e.target.value)} maxLength={20} inputMode="numeric" autoComplete="off" required />
          </div>
        </>
      ) : (
        <div className="campo">
          <label htmlFor={`${id}-codigo`}>Código o enlace del certificado</label>
          <input id={`${id}-codigo`} value={codigo} onChange={(e) => setCodigo(e.target.value)} maxLength={300} autoComplete="off" autoCapitalize="none" spellCheck={false} inputMode="url" placeholder="Ej.: aBc123xYz9_k o el enlace del QR" required />
        </div>
      )}
      {error && (
        <p className="campo-error" role="alert">
          {error}
        </p>
      )}
      <div className="form-acciones">
        <button type="submit" className="boton grande" disabled={buscando}>
          <Icono nombre="lupa" tam={18} /> {buscando ? 'Buscando…' : 'Consultar mi garantía'}
        </button>
      </div>
    </form>
  )
}
