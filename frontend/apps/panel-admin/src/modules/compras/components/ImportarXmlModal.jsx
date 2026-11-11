import { useRef, useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import BuscadorAsincrono from '../../../shared/components/BuscadorAsincrono'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import MaestroModal from '../../mantenimiento/components/MaestroModal'
import { PROVEEDORES } from '../../mantenimiento/maestros'
import { fechaCorta } from '../../almacen/inventario'
import { dinero } from '../compras'

const MAXIMO_BYTES = 2 * 1024 * 1024

/** Segundo paso: lo leído del XML, con cada línea enlazada a un producto del catálogo. */
function Revision({ lectura, onCargar, onCerrar }) {
  const { comprobante, proveedor: leido } = lectura
  const [proveedor, setProveedor] = useState(leido.existente)
  const [creando, setCreando] = useState(false)
  const [lineas, setLineas] = useState(() => lectura.lineas.map((l) => ({ ...l, incluir: true })))
  const cambiar = (numero, cambios) => setLineas((previas) => previas.map((l) => (l.numero === numero ? { ...l, ...cambios } : l)))

  const incluidas = lineas.filter((l) => l.incluir)
  const sinProducto = incluidas.filter((l) => !l.producto).length
  const motivos = [
    lectura.duplicado && 'Este comprobante ya está registrado para ese proveedor.',
    !lectura.tipo_valido && `El tipo de comprobante ${comprobante.tipo_nombre} no está habilitado para compras.`,
    incluidas.length === 0 && 'Deja al menos un producto.',
    sinProducto > 0 && `Elige el producto de ${sinProducto === 1 ? 'una línea' : `${sinProducto} líneas`} o quítalas.`,
  ].filter(Boolean)

  return (
    <>
      <dl className="datos-lista">
        <dt>Comprobante</dt>
        <dd>
          {comprobante.tipo_nombre} {comprobante.serie}-{comprobante.numero} · {fechaCorta(comprobante.fecha_emision)} · {comprobante.moneda === 'USD' ? 'Dólares' : 'Soles'} · {comprobante.forma_pago === 'CREDITO' ? `Crédito (${comprobante.cuotas.length} cuotas)` : 'Contado'}
        </dd>
        <dt>Proveedor</dt>
        <dd>
          {leido.nombre || 'Sin nombre'} ({leido.tipo_documento} {leido.numero_documento}){' '}
          {proveedor ? (
            <span className="pildora" data-tono="verde">Ya registrado</span>
          ) : (
            <button type="button" className="boton-cabecera" onClick={() => setCreando(true)}>
              <Icono nombre="agregar" tam={18} /> Registrarlo ahora
            </button>
          )}
        </dd>
        <dt>Total del XML</dt>
        <dd>{dinero(lectura.totales.total, comprobante.moneda)}</dd>
      </dl>

      {!lectura.receptor_coincide && (
        <p role="alert" className="compra-aviso">El XML está a nombre del RUC {lectura.receptor_documento || '(no indicado)'}, que no es el de esta empresa. Verifica que sea tuyo.</p>
      )}
      {lectura.duplicado && <p role="alert" className="compra-aviso">Ya registraste este comprobante: no se puede cargar de nuevo.</p>}

      <div className="marco-tabla compra-tabla">
        <table className="tabla-datos">
          <thead>
            <tr>
              <th className="centrado">
                <span className="sr-only">Incluir</span>
              </th>
              <th>En el XML</th>
              <th className="num">Cantidad</th>
              <th className="num">Precio unit.</th>
              <th>Producto del catálogo</th>
            </tr>
          </thead>
          <tbody>
            {lineas.map((l) => (
              <tr key={l.numero} className={l.incluir ? undefined : 'anulado'}>
                <td className="centrado">
                  <input type="checkbox" aria-label={`Incluir la línea ${l.numero}`} checked={l.incluir} onChange={(e) => cambiar(l.numero, { incluir: e.target.checked })} />
                </td>
                <td className="col-texto">
                  {l.descripcion || 'Sin descripción'}
                  <span className="sub-texto">{l.codigo ? `Código ${l.codigo}` : 'Sin código'} · IGV {l.afectacion || '—'}</span>
                </td>
                <td className="num">{l.cantidad}</td>
                <td className="num">{dinero(l.precio_unitario, comprobante.moneda)}</td>
                <td className="compra-xml-producto">
                  {l.producto ? (
                    <div className="compra-proveedor-elegido">
                      <div className="compra-proveedor-datos">
                        <strong>{l.producto.nombre}</strong>
                        <span className="sub-texto">{l.producto.codigo}{l.producto.lleva_serie ? ' · lleva serie' : ''}</span>
                      </div>
                      <button type="button" onClick={() => cambiar(l.numero, { producto: null })}>Cambiar</button>
                    </div>
                  ) : (
                    l.incluir && (
                      <BuscadorAsincrono
                        clave="productos-compra"
                        url="/mantenimiento/productos/"
                        parametros={{ tipo: 'BIEN', estado: 'ACTIVO' }}
                        etiqueta={`Producto de la línea ${l.numero}`}
                        placeholder="Busca el producto…"
                        icono="package"
                        onElegir={(p) => cambiar(l.numero, { producto: p })}
                        mostrar={(p) => (
                          <>
                            <strong>{p.nombre}</strong>
                            <span className="sub-texto">{p.codigo} · {p.unidad_abreviatura}</span>
                          </>
                        )}
                      />
                    )
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="celda-suave">Los productos se enlazan solos cuando el código del proveedor coincide con el «código del fabricante», el código de barras o el código de tu catálogo. Los que lleven serie piden escribirlas después.</p>

      {motivos.length > 0 && (
        <ul className="compra-faltan" aria-live="polite">
          {motivos.map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
      )}
      <div className="modal-pie">
        <button type="button" onClick={onCerrar}>Cancelar</button>
        <button type="button" className="primario" disabled={motivos.length > 0} onClick={() => onCargar({ lectura, proveedor, lineas: incluidas })}>
          Cargar en la compra
        </button>
      </div>
      {creando && (
        <MaestroModal
          config={PROVEEDORES}
          valores={{ tipo_documento: leido.tipo_documento, numero_documento: leido.numero_documento, nombre: leido.nombre }}
          onCerrar={() => setCreando(false)}
          alCrear={setProveedor}
        />
      )}
    </>
  )
}

/**
 * Cargar la factura electrónica del proveedor (XML): se lee el archivo (no se guarda), se busca al
 * proveedor por RUC y los productos por código, y todo se precarga en la compra para revisarlo.
 * Nada se registra hasta pulsar «Registrar compra».
 */
export default function ImportarXmlModal({ onCargar, onCerrar }) {
  const { empresaActivaId } = useEmpresas()
  const [lectura, setLectura] = useState(null)
  const [error, setError] = useState('')
  const entrada = useRef(null)

  const leer = useMutacion({
    mutationFn: (archivo) => {
      const cuerpo = new FormData()
      cuerpo.append('empresa', empresaActivaId)
      cuerpo.append('archivo', archivo)
      return api.post('/compras/xml/leer/', cuerpo, { timeout: 30_000 }).then((r) => r.data)
    },
    alExito: setLectura,
    avisarError: false,
  })

  const elegir = (evento) => {
    const archivo = evento.target.files?.[0]
    evento.target.value = '' // permite elegir otra vez el mismo archivo
    setError('')
    if (!archivo || leer.isPending) return
    if (!/\.xml$/i.test(archivo.name)) return setError('Elige el archivo XML de la factura (termina en .xml).')
    if (archivo.size > MAXIMO_BYTES) return setError('El archivo es demasiado grande para ser una factura.')
    leer.mutate(archivo, { onError: (e) => setError(mensajeDeError(e)) })
  }

  return (
    <Modal titulo="Cargar factura del proveedor (XML)" subtitulo="Se lee el archivo para precargar la compra. Tú revisas todo antes de registrar." onCerrar={onCerrar} ancho={980}>
      {lectura ? (
        <Revision lectura={lectura} onCargar={onCargar} onCerrar={onCerrar} />
      ) : (
        <>
          <p>Elige el XML que te envió el proveedor junto a su factura electrónica. No se guarda el archivo: solo se lee su contenido.</p>
          <input ref={entrada} type="file" accept=".xml,text/xml,application/xml" hidden onChange={elegir} />
          <button type="button" className="primario boton-cabecera" disabled={leer.isPending} onClick={() => entrada.current?.click()}>
            <Icono nombre="importar" tam={19} /> {leer.isPending ? 'Leyendo…' : 'Elegir el archivo XML'}
          </button>
          {error && (
            <p role="alert" className="campo-error">
              {error}
            </p>
          )}
          <div className="modal-pie">
            <button type="button" onClick={onCerrar}>Cancelar</button>
          </div>
        </>
      )}
    </Modal>
  )
}
