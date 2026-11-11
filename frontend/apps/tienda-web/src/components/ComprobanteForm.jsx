'use client'

import { useId } from 'react'

export const COMPROBANTE_INICIAL = { tipo: '03', documento_tipo: 'DNI', documento_numero: '', nombre: '', direccion_fiscal: '' }

const LARGO = { DNI: 8, RUC: 11, CE: 12, PASAPORTE: 12 }

/** Revisa los datos antes de pedir el pago. Devuelve `{ campo: mensaje }` (vacío si todo está bien). */
export function validarComprobante(c) {
  const errores = {}
  const numero = c.documento_numero.replace(/\s/g, '')
  if (c.tipo === '01') {
    if (!/^\d{11}$/.test(numero)) errores.documento_numero = 'El RUC tiene 11 dígitos.'
    if (!c.nombre.trim()) errores.nombre = 'Escribe la razón social.'
    if (!c.direccion_fiscal.trim()) errores.direccion_fiscal = 'Escribe la dirección fiscal.'
  } else if (c.documento_tipo && numero) {
    if (c.documento_tipo === 'DNI' && !/^\d{8}$/.test(numero)) errores.documento_numero = 'El DNI tiene 8 dígitos.'
    if (c.documento_tipo !== 'DNI' && numero.length < 6) errores.documento_numero = 'Revisa el número de documento.'
  }
  return errores
}

/** Lo que se manda al servidor (boleta sin documento = sin número). */
export function comprobanteParaApi(c) {
  const numero = c.documento_numero.replace(/\s/g, '')
  if (c.tipo === '01') {
    return { tipo: '01', documento_tipo: 'RUC', documento_numero: numero, nombre: c.nombre.trim(), direccion_fiscal: c.direccion_fiscal.trim() }
  }
  return numero
    ? { tipo: '03', documento_tipo: c.documento_tipo, documento_numero: numero, nombre: c.nombre.trim() }
    : { tipo: '03', nombre: c.nombre.trim() }
}

/**
 * Datos para el comprobante: boleta (con DNI, CE o pasaporte, o sin documento en compras chicas)
 * o factura (con RUC). `errores` trae los mensajes del navegador o del servidor, por campo.
 */
export default function ComprobanteForm({ valor, onChange, errores = {}, deshabilitado = false }) {
  const id = useId()
  const poner = (campo) => (e) => onChange({ ...valor, [campo]: e.target.value })
  const esFactura = valor.tipo === '01'
  const sinDocumento = !esFactura && !valor.documento_tipo

  function cambiarTipo(tipo) {
    onChange(
      tipo === '01'
        ? { ...valor, tipo, documento_tipo: 'RUC', documento_numero: '' }
        : { ...valor, tipo, documento_tipo: 'DNI', documento_numero: '', direccion_fiscal: '' },
    )
  }

  return (
    <div className="com-detalle">
      <div className="com-modalidades" role="radiogroup" aria-label="Tipo de comprobante">
        <label className={`com-opcion chica${!esFactura ? ' activa' : ''}`}>
          <input type="radio" name="tipo-comprobante" checked={!esFactura} disabled={deshabilitado} onChange={() => cambiarTipo('03')} />
          <span>
            <strong>Boleta</strong>
            <small>Para ti, con tu DNI</small>
          </span>
        </label>
        <label className={`com-opcion chica${esFactura ? ' activa' : ''}`}>
          <input type="radio" name="tipo-comprobante" checked={esFactura} disabled={deshabilitado} onChange={() => cambiarTipo('01')} />
          <span>
            <strong>Factura</strong>
            <small>Para tu empresa, con RUC</small>
          </span>
        </label>
      </div>

      <div className="form">
        {!esFactura && (
          <div className="form-fila dos">
            <div className="campo">
              <label htmlFor={`${id}-tipo`}>Documento</label>
              <select
                id={`${id}-tipo`}
                value={valor.documento_tipo}
                disabled={deshabilitado}
                onChange={(e) => onChange({ ...valor, documento_tipo: e.target.value, documento_numero: e.target.value ? valor.documento_numero : '' })}
              >
                <option value="DNI">DNI</option>
                <option value="CE">Carné de extranjería</option>
                <option value="PASAPORTE">Pasaporte</option>
                <option value="">Sin documento</option>
              </select>
            </div>
            {!sinDocumento && (
              <div className="campo">
                <label htmlFor={`${id}-numero`}>Número</label>
                <input
                  id={`${id}-numero`}
                  value={valor.documento_numero}
                  onChange={poner('documento_numero')}
                  inputMode={valor.documento_tipo === 'DNI' ? 'numeric' : 'text'}
                  maxLength={LARGO[valor.documento_tipo] ?? 12}
                  autoComplete="off"
                  disabled={deshabilitado}
                  aria-invalid={errores.documento_numero ? 'true' : undefined}
                />
                {errores.documento_numero && <span className="campo-error">{errores.documento_numero}</span>}
              </div>
            )}
          </div>
        )}
        {esFactura && (
          <div className="campo">
            <label htmlFor={`${id}-ruc`}>RUC</label>
            <input
              id={`${id}-ruc`}
              value={valor.documento_numero}
              onChange={poner('documento_numero')}
              inputMode="numeric"
              maxLength={11}
              autoComplete="off"
              disabled={deshabilitado}
              aria-invalid={errores.documento_numero ? 'true' : undefined}
            />
            {errores.documento_numero && <span className="campo-error">{errores.documento_numero}</span>}
          </div>
        )}
        <div className="campo">
          <label htmlFor={`${id}-nombre`}>
            {esFactura ? 'Razón social' : 'Nombre en la boleta'} {!esFactura && <span className="campo-opcional">(opcional)</span>}
          </label>
          <input
            id={`${id}-nombre`}
            value={valor.nombre}
            onChange={poner('nombre')}
            maxLength={250}
            autoComplete={esFactura ? 'organization' : 'name'}
            disabled={deshabilitado}
            aria-invalid={errores.nombre ? 'true' : undefined}
          />
          {errores.nombre && <span className="campo-error">{errores.nombre}</span>}
        </div>
        {esFactura && (
          <div className="campo">
            <label htmlFor={`${id}-fiscal`}>Dirección fiscal</label>
            <input
              id={`${id}-fiscal`}
              value={valor.direccion_fiscal}
              onChange={poner('direccion_fiscal')}
              maxLength={250}
              autoComplete="street-address"
              disabled={deshabilitado}
              aria-invalid={errores.direccion_fiscal ? 'true' : undefined}
            />
            {errores.direccion_fiscal && <span className="campo-error">{errores.direccion_fiscal}</span>}
          </div>
        )}
        {!esFactura && <p className="campo-ayuda">En compras grandes la boleta debe llevar tu DNI; si hace falta, te lo avisaremos.</p>}
      </div>
    </div>
  )
}
