import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import Interruptor from '../../../shared/components/Interruptor'
import Modal from '../../../shared/components/Modal'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { ALCANCES, codigoAlAzar, cuerpoDeCupon, cuponDesdeServidor, cuponVacio, revisarCupon, TIPOS } from '../cupones'

const CLAVE = ['tienda', 'cupones']

/** Elegir de una lista (categorías o marcas) marcando casillas. */
function ListaMarcable({ titulo, opciones, elegidas, onCambio }) {
  const alternar = (id) => onCambio(elegidas.includes(id) ? elegidas.filter((x) => x !== id) : [...elegidas, id])
  if (opciones.length === 0) return <p className="celda-suave">No hay {titulo.toLowerCase()} para elegir.</p>
  return (
    <ul className="cupon-opciones" aria-label={titulo}>
      {opciones.map((o) => (
        <li key={o.id}>
          <label>
            <input type="checkbox" checked={elegidas.includes(o.id)} onChange={() => alternar(o.id)} /> {o.nombre}
          </label>
        </li>
      ))}
    </ul>
  )
}

/** Elegir productos: busca entre los publicados en la tienda y los deja como etiquetas. */
function ElegirProductos({ elegidos, onCambio }) {
  const [texto, setTexto] = useState('')
  const q = useDebounce(texto, 300)
  const resultados = useQuery({
    queryKey: ['tienda', 'ofertas-productos', q],
    queryFn: ({ signal }) => api.get('/tienda/admin/ofertas/productos/', { params: { q }, signal }).then((r) => r.data),
    staleTime: 30_000,
  })
  const ids = new Set(elegidos.map((p) => p.id))
  return (
    <div className="cupon-productos">
      {elegidos.length > 0 && (
        <ul className="cupon-etiquetas" aria-label="Productos elegidos">
          {elegidos.map((p) => (
            <li key={p.id}>
              {p.nombre}
              <button type="button" aria-label={`Quitar ${p.nombre}`} onClick={() => onCambio(elegidos.filter((x) => x.id !== p.id))}>
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="oferta-buscador">
        <input type="search" value={texto} placeholder="Busca por nombre o código…" aria-label="Buscar producto de la tienda" onChange={(e) => setTexto(e.target.value)} />
        <ul className="oferta-resultados" aria-label="Productos publicados en la tienda">
          {resultados.isPending && <li className="celda-suave">Buscando…</li>}
          {resultados.data?.length === 0 && <li className="celda-suave">No hay productos publicados con ese nombre.</li>}
          {(resultados.data ?? [])
            .filter((p) => !ids.has(p.id))
            .map((p) => (
              <li key={p.id}>
                <button type="button" onClick={() => onCambio([...elegidos, { id: p.id, codigo: p.codigo, nombre: p.nombre }])}>
                  <span>{p.nombre}</span>
                  <small>Código {p.codigo}</small>
                </button>
              </li>
            ))}
        </ul>
      </div>
    </div>
  )
}

/** Crear o editar un cupón de descuento de la tienda. */
export default function CuponModal({ cupon, onCerrar }) {
  const [form, setForm] = useState(() => (cupon ? cuponDesdeServidor(cupon) : cuponVacio()))
  const [errores, setErrores] = useState({})
  const opciones = useQuery({
    queryKey: ['tienda', 'cupones-opciones'],
    queryFn: ({ signal }) => api.get('/tienda/admin/cupones/opciones/', { signal }).then((r) => r.data),
    staleTime: 60_000,
  })

  const cambiar = (campo, valor) => {
    setForm((f) => ({ ...f, [campo]: valor }))
    setErrores((e) => ({ ...e, [campo]: undefined, _general: undefined }))
  }

  const guardar = useMutacion({
    mutationFn: (cuerpo) => (form.id ? api.patch(`/tienda/admin/cupones/${form.id}/`, cuerpo) : api.post('/tienda/admin/cupones/', cuerpo)).then((r) => r.data),
    invalidar: [CLAVE],
    exito: form.id ? 'Cupón actualizado.' : 'Cupón creado.',
    alExito: onCerrar,
    avisarError: false,
  })

  const alGuardar = (evento) => {
    evento.preventDefault()
    const locales = revisarCupon(form)
    setErrores(locales)
    if (Object.keys(locales).length > 0) return
    guardar.mutate(cuerpoDeCupon(form), {
      onError: (error) => setErrores({ ...erroresDeCampo(error), _general: mensajeDeError(error) }),
    })
  }

  const otroError = errores._general && !Object.keys(errores).some((k) => k !== '_general' && errores[k])

  return (
    <Modal titulo={form.id ? 'Editar cupón' : 'Nuevo cupón'} subtitulo="Un código que tus clientes escriben al comprar para obtener un descuento." onCerrar={onCerrar} ancho={720}>
      <form onSubmit={alGuardar} noValidate className="envios-form">
        <div className="maestro-campos">
          <Campo etiqueta="Código" requerido error={errores.codigo} ayuda="Lo escribe el cliente. Sin espacios; se guarda en mayúsculas.">
            {(p) => (
              <div className="pagos-secreta">
                <input {...p} name="codigo" value={form.codigo} maxLength={30} autoComplete="off" spellCheck={false} placeholder="Ej. VERANO10" onChange={(e) => cambiar('codigo', e.target.value.toUpperCase())} />
                {!form.id && (
                  <button type="button" onClick={() => cambiar('codigo', codigoAlAzar())}>
                    Generar
                  </button>
                )}
              </div>
            )}
          </Campo>
          <Campo etiqueta="Para qué es (opcional)" error={errores.nombre} ayuda="Solo lo ves tú. Ej.: Campaña de verano.">
            {(p) => <input {...p} name="nombre" value={form.nombre} maxLength={100} onChange={(e) => cambiar('nombre', e.target.value)} />}
          </Campo>
        </div>

        <fieldset className="cupon-tipos">
          <legend>Qué descuenta</legend>
          <div className="pagos-modos" role="group" aria-label="Tipo de cupón">
            {Object.entries(TIPOS).map(([valor, t]) => (
              <button key={valor} type="button" className="pagos-modo" aria-pressed={form.tipo === valor} onClick={() => cambiar('tipo', valor)}>
                <strong>{t.texto}</strong>
                <small>{t.detalle}</small>
              </button>
            ))}
          </div>
        </fieldset>

        <div className="maestro-campos">
          {form.tipo !== 'ENVIO_GRATIS' && (
            <Campo etiqueta={form.tipo === 'PORCENTAJE' ? 'Porcentaje de descuento (%)' : 'Monto del descuento (S/)'} requerido error={errores.valor}>
              {(p) => <input {...p} name="valor" inputMode="decimal" value={form.valor} onChange={(e) => cambiar('valor', e.target.value)} />}
            </Campo>
          )}
          {form.tipo === 'PORCENTAJE' && (
            <Campo etiqueta="Máximo a descontar (S/, opcional)" error={errores.tope_descuento} ayuda="Para que un % alto no descuente demasiado en compras grandes.">
              {(p) => <input {...p} name="tope_descuento" inputMode="decimal" value={form.tope_descuento} placeholder="Sin máximo" onChange={(e) => cambiar('tope_descuento', e.target.value)} />}
            </Campo>
          )}
          <Campo etiqueta="Compra mínima en productos (S/)" error={errores.compra_minima} ayuda="Con IGV. 0 = sin mínimo.">
            {(p) => <input {...p} name="compra_minima" inputMode="decimal" value={form.compra_minima} onChange={(e) => cambiar('compra_minima', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Empieza (opcional)" error={errores.inicia_en}>
            {(p) => <input {...p} name="inicia_en" type="datetime-local" value={form.inicia_en} onChange={(e) => cambiar('inicia_en', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Termina (opcional)" error={errores.termina_en} ayuda="Al llegar esta hora ya no se puede usar.">
            {(p) => <input {...p} name="termina_en" type="datetime-local" value={form.termina_en} onChange={(e) => cambiar('termina_en', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Usos en total (opcional)" error={errores.usos_maximos} ayuda="Cuántas veces se puede usar entre todos los clientes. Vacío = sin límite.">
            {(p) => <input {...p} name="usos_maximos" inputMode="numeric" value={form.usos_maximos} placeholder="Sin límite" onChange={(e) => cambiar('usos_maximos', e.target.value)} />}
          </Campo>
          <Campo etiqueta="Usos por cliente" error={errores.usos_por_cliente}>
            {(p) => <input {...p} name="usos_por_cliente" inputMode="numeric" value={form.usos_por_cliente} onChange={(e) => cambiar('usos_por_cliente', e.target.value)} />}
          </Campo>
        </div>

        {form.tipo !== 'ENVIO_GRATIS' && (
          <fieldset className="cupon-alcance">
            <legend>A qué productos aplica</legend>
            <div className="tienda-segmentos" role="group" aria-label="Alcance del cupón">
              {Object.entries(ALCANCES).map(([valor, texto]) => (
                <button key={valor} type="button" aria-pressed={form.alcance === valor} onClick={() => cambiar('alcance', valor)}>
                  {texto}
                </button>
              ))}
            </div>
            {form.alcance === 'CATEGORIAS' && <ListaMarcable titulo="Categorías" opciones={opciones.data?.categorias ?? []} elegidas={form.categorias} onCambio={(v) => cambiar('categorias', v)} />}
            {form.alcance === 'MARCAS' && <ListaMarcable titulo="Marcas" opciones={opciones.data?.marcas ?? []} elegidas={form.marcas} onCambio={(v) => cambiar('marcas', v)} />}
            {form.alcance === 'PRODUCTOS' && <ElegirProductos elegidos={form.productos} onCambio={(v) => cambiar('productos', v)} />}
            {errores.alcance && (
              <p role="alert" className="campo-error">
                {errores.alcance}
              </p>
            )}
          </fieldset>
        )}

        <Interruptor
          activo={form.solo_primera_compra}
          onCambio={(v) => cambiar('solo_primera_compra', v)}
          texto="Solo para la primera compra"
          descripcion="Únicamente clientes que todavía no han comprado en la tienda."
        />
        {form.tipo !== 'ENVIO_GRATIS' && (
          <Interruptor
            activo={form.incluye_ofertas}
            onCambio={(v) => cambiar('incluye_ofertas', v)}
            texto="También en productos en oferta"
            descripcion={form.incluye_ofertas ? 'El descuento se suma a la oferta (nunca baja del precio mínimo).' : 'Recomendado: los productos en oferta ya tienen su precio especial.'}
          />
        )}
        <Interruptor
          activo={form.activo}
          onCambio={(v) => cambiar('activo', v)}
          texto={form.activo ? 'Cupón activo' : 'Cupón pausado'}
          descripcion={form.activo ? 'Se puede usar dentro de las fechas indicadas.' : 'No se puede usar aunque estén las fechas.'}
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
            {guardar.isPending ? 'Guardando…' : 'Guardar cupón'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
