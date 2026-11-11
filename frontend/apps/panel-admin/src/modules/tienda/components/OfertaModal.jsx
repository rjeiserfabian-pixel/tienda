import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Interruptor from '../../../shared/components/Interruptor'
import Modal from '../../../shared/components/Modal'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { ahorroPct, cuerpoDeOferta, ofertaDesdeServidor, ofertaVacia, revisarOferta, soles } from '../ofertas'

const CLAVE = ['tienda', 'ofertas']

/** Elegir el producto de la oferta: busca entre los publicados en la tienda. */
function BuscadorProducto({ producto, onElegir, error }) {
  const [texto, setTexto] = useState('')
  const q = useDebounce(texto, 300)
  const resultados = useQuery({
    queryKey: ['tienda', 'ofertas-productos', q],
    queryFn: ({ signal }) => api.get('/tienda/admin/ofertas/productos/', { params: { q }, signal }).then((r) => r.data),
    enabled: !producto,
    staleTime: 30_000,
  })
  if (producto) {
    return (
      <div className="oferta-producto-elegido">
        <div>
          <strong>{producto.nombre}</strong>
          <small>
            Código {producto.codigo} · Precio normal {soles(producto.precio_normal)} sin IGV
          </small>
        </div>
        <button type="button" className="boton-cabecera" onClick={() => onElegir(null)}>
          Cambiar
        </button>
      </div>
    )
  }
  return (
    <div className="oferta-buscador">
      <input
        type="search"
        value={texto}
        placeholder="Busca por nombre o código…"
        aria-label="Buscar producto de la tienda"
        aria-invalid={error ? 'true' : undefined}
        onChange={(e) => setTexto(e.target.value)}
      />
      <ul className="oferta-resultados" aria-label="Productos publicados en la tienda">
        {resultados.isPending && <li className="celda-suave">Buscando…</li>}
        {resultados.data?.length === 0 && <li className="celda-suave">No hay productos publicados con ese nombre.</li>}
        {(resultados.data ?? []).map((p) => (
          <li key={p.id}>
            <button type="button" disabled={!p.precio_normal} onClick={() => onElegir(p)}>
              <span>{p.nombre}</span>
              <small>{p.precio_normal ? soles(p.precio_normal) : 'Sin precio en la lista de la tienda'}</small>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Crear o editar una oferta (precio especial de la tienda con fechas de inicio y fin). */
export default function OfertaModal({ oferta, onCerrar }) {
  const [form, setForm] = useState(() => (oferta ? ofertaDesdeServidor(oferta) : ofertaVacia()))
  const [errores, setErrores] = useState({})

  const cambiar = (campo, valor) => {
    setForm((f) => ({ ...f, [campo]: valor }))
    setErrores((e) => ({ ...e, [campo]: undefined }))
  }

  const guardar = useMutacion({
    mutationFn: (cuerpo) => (form.id ? api.patch(`/tienda/admin/ofertas/${form.id}/`, cuerpo) : api.post('/tienda/admin/ofertas/', cuerpo)).then((r) => r.data),
    invalidar: [CLAVE],
    exito: form.id ? 'Oferta actualizada.' : 'Oferta creada.',
    alExito: onCerrar,
    avisarError: false,
  })

  const alGuardar = (evento) => {
    evento.preventDefault()
    const locales = revisarOferta(form)
    setErrores(locales)
    if (Object.keys(locales).length > 0) return
    guardar.mutate(cuerpoDeOferta(form), {
      onError: (error) => setErrores({ ...erroresDeCampo(error), _general: mensajeDeError(error) }),
    })
  }

  const ahorro = ahorroPct(form.producto?.precio_normal, form.precio_oferta)
  const otroError = errores._general && !Object.keys(errores).some((k) => k !== '_general' && errores[k])

  return (
    <Modal titulo={form.id ? 'Editar oferta' : 'Nueva oferta'} subtitulo="Un precio especial SOLO para la tienda en línea, con fecha de inicio y de fin." onCerrar={onCerrar} ancho={680}>
      <form onSubmit={alGuardar} noValidate className="envios-form">
        <Campo etiqueta="Producto" requerido error={errores.producto}>
          {() => <BuscadorProducto producto={form.producto} error={errores.producto} onElegir={(p) => cambiar('producto', p)} />}
        </Campo>

        <div className="maestro-campos">
          <Campo
            etiqueta="Precio de oferta (sin IGV)"
            requerido
            error={errores.precio_oferta}
            ayuda={
              ahorro
                ? `Los clientes ahorran ${ahorro} %. El IGV se suma al mostrarlo, como en los demás precios.`
                : 'Debe ser menor que el precio normal y no bajar del mínimo que permiten tus listas de precios.'
            }
          >
            {(p) => (
              <input {...p} name="precio_oferta" inputMode="decimal" value={form.precio_oferta} placeholder="0.00" onChange={(e) => cambiar('precio_oferta', e.target.value)} />
            )}
          </Campo>
          <Campo etiqueta="Etiqueta (opcional)" error={errores.etiqueta} ayuda="Ej.: Cyber, Liquidación. Se muestra junto al descuento.">
            {(p) => <input {...p} name="etiqueta" value={form.etiqueta} maxLength={30} onChange={(e) => cambiar('etiqueta', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Empieza" requerido error={errores.desde}>
            {(p) => <input {...p} name="desde" type="datetime-local" value={form.desde} onChange={(e) => cambiar('desde', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Termina" requerido error={errores.hasta} ayuda="Al llegar esta hora el precio vuelve al normal solo.">
            {(p) => <input {...p} name="hasta" type="datetime-local" value={form.hasta} onChange={(e) => cambiar('hasta', e.target.value)} />}
          </Campo>
        </div>

        <Interruptor
          activo={form.activa}
          onCambio={(v) => cambiar('activa', v)}
          texto={form.activa ? 'Oferta activa' : 'Oferta pausada'}
          descripcion={form.activa ? 'Se aplica entre las fechas indicadas.' : 'No se aplica aunque estén las fechas.'}
        />

        {otroError && (
          <p role="alert" className="campo-error">
            {errores._general}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={guardar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={guardar.isPending}>
            {guardar.isPending ? 'Guardando…' : 'Guardar oferta'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
