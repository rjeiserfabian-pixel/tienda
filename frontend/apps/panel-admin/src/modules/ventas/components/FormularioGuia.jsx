import { useNavigate } from 'react-router-dom'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { fechaCorta } from '../../almacen/inventario'
import { useGuiaRemision } from '../hooks/useGuiaRemision'
import { MOTIVOS_GUIA } from '../ventas'
import CargaGuia from './CargaGuia'
import DatoLectura from './DatoLectura'
import DatosGuia from './DatosGuia'
import DestinatarioGuia from './DestinatarioGuia'
import LineasGuia from './LineasGuia'
import PuntoGuia from './PuntoGuia'
import TransporteGuia from './TransporteGuia'

/**
 * La guía de remisión de un comprobante ya elegido: motivo, serie y fechas, destinatario, de dónde a
 * dónde, quién lo lleva, qué productos y cuántos kilos. El servidor revisa todo otra vez.
 */
export default function FormularioGuia({ envio: e, onBuscar }) {
  const navegar = useNavigate()
  const g = useGuiaRemision(e)
  const { f, poner } = g
  const quedan = e.lineas.some((l) => Number(l.pendiente) > 0)

  return (
    <form onSubmit={g.enviar} noValidate className="pos-layout">
      <div className="compra-layout">
        <div className="compra-principal">
          <PanelTarjeta icono="truck" titulo="Datos de la guía" descripcion="El motivo del traslado, su serie y sus fechas.">
            <DatosGuia f={f} poner={poner} motivos={MOTIVOS_GUIA} series={e.series} serie={g.serie} onSerie={g.setSerieElegida} disabled={g.enviando} />
          </PanelTarjeta>

          <PanelTarjeta icono="documento" titulo="Venta de la que sale" descripcion="Los datos se llenan solos al buscar el comprobante.">
            <div className="fila-campos">
              <button type="button" className="primario nota-buscar" disabled={g.enviando} onClick={onBuscar}>
                <Icono nombre="buscar" tam={18} /> Buscar venta
              </button>
              <DatoLectura etiqueta="Fecha de emisión" valor={fechaCorta(e.fecha)} />
              <DatoLectura etiqueta="Comprobante de referencia" valor={e.tipo_nombre} />
              <DatoLectura etiqueta="Nro." valor={e.numero_completo} />
            </div>
          </PanelTarjeta>

          <PanelTarjeta icono="user" titulo="Remitente y destinatario" descripcion="Quién envía y a quién va la mercadería.">
            <div className="pos-bloques">
              <div className="fila-campos">
                <DatoLectura etiqueta="Remitente" valor={e.remitente.nombre} />
                <DatoLectura etiqueta="RUC" valor={e.remitente.ruc} />
              </div>
              <DestinatarioGuia original={e.destinatario_datos} elegido={g.destinatario} onElegir={g.elegirDestinatario} disabled={g.enviando} />
            </div>
          </PanelTarjeta>

          <PanelTarjeta icono="ubicacion" titulo="Punto de partida y de llegada" descripcion="De dónde sale y a dónde llega. El ubigeo es opcional por ahora.">
            <div className="fila-campos">
              <PuntoGuia titulo="partida" direccion={f.partida} ubigeo={f.ubigeoPartida} disabled={g.enviando} onDireccion={(v) => poner('partida', v)} onUbigeo={(v) => poner('ubigeoPartida', v)} />
              <PuntoGuia titulo="llegada" direccion={f.llegada} ubigeo={f.ubigeoLlegada} disabled={g.enviando} onDireccion={(v) => poner('llegada', v)} onUbigeo={(v) => poner('ubigeoLlegada', v)} />
            </div>
            <DatoLectura etiqueta="Almacén de origen" valor={e.almacen_origen?.nombre ?? 'Sin definir (la mercadería salió de varios almacenes)'} />
          </PanelTarjeta>

          <PanelTarjeta icono="truck" titulo="Transporte" descripcion="Quién lleva la mercadería: elige de las listas de Mantenimiento o registra uno nuevo con «+».">
            <TransporteGuia f={f} poner={poner} remitente={e.remitente} disabled={g.enviando} onAgregarSecundario={g.agregarSecundario} onQuitarSecundario={g.quitarSecundario} />
          </PanelTarjeta>

          <PanelTarjeta icono="package" titulo="Productos" descripcion={quedan ? 'Lo que viaja: por defecto todo lo que falta enviar. Escribe el peso de cada producto.' : 'Este comprobante ya se envió por completo.'}>
            <LineasGuia lineas={e.lineas} cantidades={g.cantidades} pesos={g.pesos} disabled={g.enviando} onCantidad={g.ponerCantidad} onPeso={g.ponerPeso} onQuitar={g.quitarLinea} />
          </PanelTarjeta>

          <PanelTarjeta icono="boxes" titulo="Carga" descripcion="Bultos, peso total y observaciones.">
            <CargaGuia f={f} poner={poner} pesoSugerido={g.pesoSugerido} disabled={g.enviando} />
          </PanelTarjeta>
        </div>

        <aside className="compra-resumen" aria-label="Resumen de la guía">
          <h3>Resumen</h3>
          <dl className="compra-totales">
            <div>
              <dt>Productos</dt>
              <dd>{e.lineas.filter((l) => Number(g.cantidades[l.id]) > 0).length}</dd>
            </div>
            <div>
              <dt>Bultos</dt>
              <dd>{f.bultos || '—'}</dd>
            </div>
            <div className="compra-total">
              <dt>Peso</dt>
              <dd>{(f.pesoEscrito.trim() ? Number(f.pesoEscrito) || 0 : g.pesoSugerido).toFixed(3)} kg</dd>
            </div>
          </dl>
          {g.intento && g.errores.length > 0 && (
            <div className="compra-faltan">
              <strong>Para emitir falta:</strong>
              <ul>
                {[...new Set(g.errores)].map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
            </div>
          )}
          {g.error && (
            <p role="alert" className="campo-error">
              {g.error}
            </p>
          )}
          <button type="submit" className="primario pos-generar" disabled={g.enviando || !quedan}>
            <Icono nombre="documento" tam={20} />
            {g.enviando ? 'Emitiendo…' : 'Emitir guía de remisión'}
          </button>
          <button type="button" className="boton-cabecera" disabled={g.enviando} onClick={() => navegar('/ventas/guias-remision')}>
            Cancelar
          </button>
          <small className="celda-suave">La guía acompaña la mercadería: no mueve stock. Una guía no se edita; si hay un error, se anula y se emite otra.</small>
        </aside>
      </div>
    </form>
  )
}
