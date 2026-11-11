'use client'

import Link from 'next/link'
import { useState } from 'react'
import { llamar } from '@/lib/cliente'
import Icono from '../Icono'
import { useCuenta } from '../Proveedores'

export default function SeccionResumen() {
  const { perfil } = useCuenta()
  const [reenvio, setReenvio] = useState(null)

  async function reenviar() {
    setReenvio('enviando')
    try {
      await llamar('cuenta/reenviar-verificacion', { metodo: 'POST', cuerpo: {} })
      setReenvio('ok')
    } catch {
      setReenvio('error')
    }
  }

  return (
    <>
      <h1>Hola, {perfil.nombres.split(' ')[0]}</h1>
      <p className="cta-sub">Desde aquí manejas tus datos, direcciones y pedidos.</p>
      {!perfil.correo_verificado && (
        <div className="alerta aviso" role="status">
          <Icono nombre="info" tam={18} />
          <div>
            <p>
              Aún no confirmaste tu correo <strong>{perfil.correo}</strong>. Lo necesitas para completar tus compras.
            </p>
            {reenvio === 'ok' ? (
              <p className="cta-nota">Te enviamos un correo nuevo. Revisa tu bandeja y el spam.</p>
            ) : (
              <button type="button" className="boton chico" onClick={reenviar} disabled={reenvio === 'enviando'}>
                {reenvio === 'enviando' ? 'Enviando…' : 'Reenviar correo'}
              </button>
            )}
            {reenvio === 'error' && <p className="campo-error">No pudimos enviarlo. Inténtalo en unos minutos.</p>}
          </div>
        </div>
      )}
      <ul className="cta-atajos">
        <li>
          <Link href="/cuenta/datos">
            <Icono nombre="usuario" tam={22} />
            <strong>Mis datos</strong>
            <span>Nombre y celular</span>
          </Link>
        </li>
        <li>
          <Link href="/cuenta/direcciones">
            <Icono nombre="pin" tam={22} />
            <strong>Mis direcciones</strong>
            <span>Dónde recibes tus pedidos</span>
          </Link>
        </li>
        <li>
          <Link href="/cuenta/pedidos">
            <Icono nombre="camion" tam={22} />
            <strong>Mis pedidos</strong>
            <span>Tus compras y su estado</span>
          </Link>
        </li>
        <li>
          <Link href="/cuenta/seguridad">
            <Icono nombre="candado" tam={22} />
            <strong>Seguridad</strong>
            <span>Cambiar contraseña</span>
          </Link>
        </li>
      </ul>
    </>
  )
}
