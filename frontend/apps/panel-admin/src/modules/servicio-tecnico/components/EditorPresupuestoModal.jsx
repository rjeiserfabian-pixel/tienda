import { useQuery } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api, erroresDeCampo, mensajeDeError } from '../../../core/api/client'
import BuscadorAsincrono from '../../../shared/components/BuscadorAsincrono'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { cuerpoPresupuesto, lineaDeFicha, lineasDePresupuesto, validarPresupuesto } from '../servicio'

const VACIO = []

const stockDe = (linea) => (linea.stock ? linea.stock.filter((s) => s.empresa === linea.empresa).reduce((suma, s) => suma + Number(s.cantidad), 0) : null)

/** Arma o rehace el presupuesto: servicios y repuestos del catálogo de venta, con su precio de lista. */
export default function EditorPresupuestoModal({ orden, onCerrar }) {
  const [lineas, setLineas] = useState(() => (orden.presupuesto ? lineasDePresupuesto(orden.presupuesto) : []))
  const [validez, setValidez] = useState('15')
  const [condiciones, setCondiciones] = useState('')
  const [error, setError] = useState('')
  const entrada = useRef(null)

  // La lista de precios principal y las empresas que pueden surtir (una sola consulta liviana).
  const base = useQuery({
    queryKey: ['servicio', 'catalogo-base', orden.empresa],
    queryFn: ({ signal }) => api.get('/servicio-tecnico/catalogo/', { params: { empresa: orden.empresa }, signal }).then((r) => r.data),
    staleTime: 60_000,
  })
  const empresas = base.data?.empresas ?? VACIO
  const lista = base.data?.lista_principal ?? null

  const guardar = useMutacion({
    mutationFn: (cuerpo) => api.post(`/servicio-tecnico/ordenes/${orden.id}/presupuesto/`, cuerpo).then((r) => r.data),
    invalidar: [['servicio']],
    exito: 'Presupuesto guardado.',
    alExito: onCerrar,
    avisarError: false,
  })

  const agregar = (ficha) => setLineas((previas) => [...previas, lineaDeFicha(ficha, orden.empresa, lista)])
  const cambiar = (clave, campo, valor) => setLineas((previas) => previas.map((l) => (l.clave === clave ? { ...l, [campo]: valor } : l)))

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending) return
    const malo = validarPresupuesto(lineas)
    if (malo) return setError(malo)
    setError('')
    guardar.mutate(cuerpoPresupuesto(lineas, validez, condiciones), {
      onError: (e) => {
        const campos = erroresDeCampo(e)
        setError(campos.lineas || campos.validez_dias || mensajeDeError(e))
      },
    })
  }

  return (
    <Modal titulo={orden.presupuesto ? 'Rehacer el presupuesto' : 'Armar el presupuesto'} subtitulo={`Orden ${orden.codigo} · ${orden.cliente_nombre}`} onCerrar={onCerrar} ancho={900}>
      <form onSubmit={enviar} noValidate>
        {orden.presupuesto && <p className="compra-aviso">Al guardar se crea una versión nueva y la anterior queda anulada.</p>}
        <div className="compra-proveedor-buscar">
          <BuscadorAsincrono
            clave="presupuesto-catalogo"
            url="/servicio-tecnico/catalogo/"
            parametros={{ empresa: orden.empresa }}
            etiqueta="Buscar servicio o repuesto"
            placeholder="Busca un servicio o repuesto por nombre o código…"
            icono="buscar"
            inputRef={entrada}
            disabled={guardar.isPending}
            onElegir={agregar}
            mostrar={(f) => (
              <>
                <strong>{f.nombre}</strong>
                <span className="sub-texto">
                  {f.codigo} · {f.tipo === 'SERVICIO' ? 'Servicio' : f.controla_stock ? `Stock: ${(f.stock ?? []).reduce((s, x) => s + Number(x.cantidad), 0)}` : 'Sin control de stock'}
                  {lista && f.precios?.find((p) => p.lista === lista) ? ` · S/ ${Number(f.precios.find((p) => p.lista === lista).precio).toFixed(2)} (sin IGV)` : ''}
                </span>
              </>
            )}
          />
        </div>
        {lineas.length === 0 ? (
          <p className="estado-vacio">Busca arriba el servicio (mano de obra) y los repuestos que llevará.</p>
        ) : (
          <ul className="servicio-lineas" aria-label="Líneas del presupuesto">
            {lineas.map((l) => {
              const stock = stockDe(l)
              const esRepuesto = l.tipo !== 'SERVICIO'
              return (
                <li key={l.clave}>
                  <span className="servicio-linea-nombre">
                    <strong>{l.nombre}</strong>
                    <span className="sub-texto">
                      {l.codigo} · {esRepuesto ? 'Repuesto' : 'Servicio'}
                      {esRepuesto && stock !== null && (Number(l.cantidad) > stock ? ` · Solo hay ${stock} en stock` : ` · Stock: ${stock}`)}
                    </span>
                  </span>
                  {esRepuesto && empresas.length > 1 ? (
                    <select aria-label={`Empresa que surte ${l.nombre}`} value={l.empresa} disabled={guardar.isPending} onChange={(e) => cambiar(l.clave, 'empresa', Number(e.target.value))}>
                      {empresas.map((e) => (
                        <option key={e.id} value={e.id}>
                          {e.nombre}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span />
                  )}
                  <input inputMode="decimal" aria-label={`Cantidad de ${l.nombre}`} value={l.cantidad} disabled={guardar.isPending} onChange={(e) => cambiar(l.clave, 'cantidad', e.target.value)} />
                  <input inputMode="decimal" aria-label={`Precio de ${l.nombre} sin IGV`} placeholder={l.precioLista ? `Lista ${Number(l.precioLista).toFixed(2)}` : 'Precio'} value={l.precio} disabled={guardar.isPending} onChange={(e) => cambiar(l.clave, 'precio', e.target.value)} />
                  <button type="button" className="accion-icono peligro-suave" aria-label={`Quitar ${l.nombre}`} title="Quitar" disabled={guardar.isPending} onClick={() => setLineas((previas) => previas.filter((x) => x.clave !== l.clave))}>
                    <Icono nombre="papelera" tam={18} />
                  </button>
                </li>
              )
            })}
          </ul>
        )}
        <p className="celda-suave">Los precios son sin IGV: el IGV se calcula solo. Deja el precio vacío para usar el de la lista principal.</p>
        <div className="fila-campos">
          <Campo etiqueta="Válido por (días)">
            {(p) => <input {...p} type="number" min={1} max={60} value={validez} disabled={guardar.isPending} onChange={(e) => setValidez(e.target.value)} />}
          </Campo>
          <Campo etiqueta="Condiciones" contador={{ actual: condiciones.length, max: 300 }}>
            {(p) => <input {...p} maxLength={300} placeholder="Opcional. Ej. Incluye 30 días de garantía." value={condiciones} disabled={guardar.isPending} onChange={(e) => setCondiciones(e.target.value)} />}
          </Campo>
        </div>
        {error && (
          <p role="alert" className="campo-error">
            {error}
          </p>
        )}
        <div className="modal-pie">
          <button type="button" onClick={onCerrar} disabled={guardar.isPending}>
            Cancelar
          </button>
          <button type="submit" className="primario" disabled={guardar.isPending}>
            {guardar.isPending ? 'Guardando…' : 'Guardar presupuesto'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
