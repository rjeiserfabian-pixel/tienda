'use client'

import { useEffect, useState } from 'react'
import { ErrorTienda, llamar } from '@/lib/cliente'
import Icono from '../Icono'
import { useCuenta } from '../Proveedores'
import DireccionForm from './DireccionForm'

const MAXIMO = 10

export default function SeccionDirecciones() {
  const { perfil } = useCuenta()
  const [lista, setLista] = useState(null)
  const [fallo, setFallo] = useState(null)
  const [modo, setModo] = useState(null) // null | 'nueva' | id de la dirección que se edita
  const [porBorrar, setPorBorrar] = useState(null)
  const [borrando, setBorrando] = useState(false)

  useEffect(() => {
    llamar('cuenta/direcciones')
      .then(setLista)
      .catch((err) => setFallo(err instanceof ErrorTienda ? err.message : 'No pudimos cargar tus direcciones.'))
  }, [])

  async function borrar(id) {
    setBorrando(true)
    setFallo(null)
    try {
      setLista(await llamar(`cuenta/direcciones/${id}`, { metodo: 'DELETE' }))
      setPorBorrar(null)
    } catch (err) {
      setFallo(err instanceof ErrorTienda ? err.message : 'No pudimos eliminar la dirección.')
    } finally {
      setBorrando(false)
    }
  }

  const guardada = (nuevaLista) => {
    setLista(nuevaLista)
    setModo(null)
  }

  return (
    <>
      <h1>Mis direcciones</h1>
      <p className="cta-sub">Guarda hasta {MAXIMO} direcciones para recibir tus pedidos más rápido.</p>
      {fallo && (
        <p className="alerta error" role="alert">
          {fallo}
        </p>
      )}
      {lista === null && !fallo && <div className="cta-esqueleto" aria-busy="true" />}
      {lista && lista.length === 0 && modo !== 'nueva' && (
        <p className="alerta">Todavía no tienes direcciones guardadas.</p>
      )}
      {lista && (
        <ul className="cta-direcciones">
          {lista.map((d) =>
            modo === d.id ? (
              <li key={d.id} className="cta-direccion editando">
                <DireccionForm inicial={d} alGuardar={guardada} alCancelar={() => setModo(null)} />
              </li>
            ) : (
              <li key={d.id} className="cta-direccion">
                <Icono nombre="pin" tam={22} />
                <div className="cta-direccion-texto">
                  <p>
                    <strong>{d.etiqueta || 'Dirección'}</strong>
                    {d.es_principal && <span className="insignia ok">Principal</span>}
                  </p>
                  <p>{d.direccion}</p>
                  <p className="cta-tenue">{d.ubicacion}</p>
                  {d.referencia && <p className="cta-tenue">Ref.: {d.referencia}</p>}
                  <p className="cta-tenue">
                    Recibe {d.receptor} · {d.celular}
                  </p>
                </div>
                <div className="cta-direccion-acciones">
                  {porBorrar === d.id ? (
                    <>
                      <span>¿Eliminar?</span>
                      <button type="button" className="boton chico" onClick={() => borrar(d.id)} disabled={borrando}>
                        {borrando ? '…' : 'Sí, eliminar'}
                      </button>
                      <button type="button" className="boton secundario chico" onClick={() => setPorBorrar(null)} disabled={borrando}>
                        No
                      </button>
                    </>
                  ) : (
                    <>
                      <button type="button" className="boton secundario chico" onClick={() => setModo(d.id)}>
                        Editar
                      </button>
                      <button type="button" className="boton fantasma chico" onClick={() => setPorBorrar(d.id)} aria-label={`Eliminar ${d.etiqueta || 'dirección'}`}>
                        <Icono nombre="basura" tam={16} /> Eliminar
                      </button>
                    </>
                  )}
                </div>
              </li>
            ),
          )}
        </ul>
      )}
      {lista && modo === 'nueva' && (
        <div className="cta-direccion editando">
          <h2>Nueva dirección</h2>
          <DireccionForm celularSugerido={perfil.celular ?? ''} nombreSugerido={`${perfil.nombres} ${perfil.apellidos}`.trim()} alGuardar={guardada} alCancelar={() => setModo(null)} />
        </div>
      )}
      {lista && modo === null && (
        <div className="form-acciones" style={{ marginTop: 16 }}>
          {lista.length >= MAXIMO ? (
            <p className="alerta">Llegaste al máximo de {MAXIMO} direcciones. Elimina alguna para agregar otra.</p>
          ) : (
            <button type="button" className="boton" onClick={() => setModo('nueva')}>
              <Icono nombre="mas" tam={18} /> Agregar dirección
            </button>
          )}
        </div>
      )}
    </>
  )
}
