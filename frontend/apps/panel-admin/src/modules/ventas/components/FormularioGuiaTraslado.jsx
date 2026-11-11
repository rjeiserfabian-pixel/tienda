import { useNavigate } from 'react-router-dom'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { fechaCorta } from '../../almacen/inventario'
import { useGuiaTraslado } from '../hooks/useGuiaTraslado'
import CargaGuia from './CargaGuia'
import DatoLectura from './DatoLectura'
import DatosGuia from './DatosGuia'
import LineasTraslado from './LineasTraslado'
import PuntoGuia from './PuntoGuia'
import TransporteGuia from './TransporteGuia'

/**
 * La guía de remisión de un traspaso entre almacenes: motivo, serie y fechas, de qué almacén a cuál, quién lo
 * lleva, el peso de cada producto y la carga. La mercadería y el destinatario (la propia empresa) vienen del
 * traspaso y no se cambian; el servidor revisa todo otra vez.
 */
export default function FormularioGuiaTraslado({ envio: e }) {
  const navegar = useNavigate()
  const g = useGuiaTraslado(e)
  const { f, poner } = g

  return (
    <form onSubmit={g.enviar} noValidate className="pos-layout">
      <div className="compra-layout">
        <div className="compra-principal">
          <PanelTarjeta icono="truck" titulo="Datos de la guía" descripcion="El motivo del traslado, su serie y sus fechas.">
            <DatosGuia f={f} poner={poner} motivos={e.motivos} series={e.series} serie={g.serie} onSerie={g.setSerieElegida} disabled={g.enviando} />
          </PanelTarjeta>

          <PanelTarjeta icono="swap" titulo="Traspaso del que sale" descripcion="La guía acompaña lo que ya se traspasó; el stock no vuelve a moverse.">
            <div className="fila-campos">
              <DatoLectura etiqueta="Traspaso N°" valor={String(e.numero).padStart(6, '0')} />
              <DatoLectura etiqueta="Fecha del traspaso" valor={fechaCorta(e.fecha)} />
              <DatoLectura etiqueta="Sale de" valor={e.almacen_origen.nombre} />
              <DatoLectura etiqueta="Llega a" valor={e.almacen_destino.nombre} />
            </div>
          </PanelTarjeta>

          <PanelTarjeta icono="user" titulo="Remitente y destinatario" descripcion="Es un traslado entre establecimientos de la misma empresa: envía y recibe la propia empresa.">
            <div className="fila-campos">
              <DatoLectura etiqueta="Remitente" valor={e.remitente.nombre} />
              <DatoLectura etiqueta="RUC" valor={e.remitente.ruc} />
              <DatoLectura etiqueta="Destinatario" valor={e.destinatario.nombre} />
            </div>
          </PanelTarjeta>

          <PanelTarjeta icono="ubicacion" titulo="Punto de partida y de llegada" descripcion="Se proponen con la dirección de cada almacén; puedes corregirlas. El ubigeo es opcional por ahora.">
            <div className="fila-campos">
              <PuntoGuia titulo="partida" direccion={f.partida} ubigeo={f.ubigeoPartida} disabled={g.enviando} onDireccion={(v) => poner('partida', v)} onUbigeo={(v) => poner('ubigeoPartida', v)} />
              <PuntoGuia titulo="llegada" direccion={f.llegada} ubigeo={f.ubigeoLlegada} disabled={g.enviando} onDireccion={(v) => poner('llegada', v)} onUbigeo={(v) => poner('ubigeoLlegada', v)} />
            </div>
          </PanelTarjeta>

          <PanelTarjeta icono="truck" titulo="Transporte" descripcion="Quién lleva la mercadería: elige de las listas de Mantenimiento o registra uno nuevo con «+».">
            <TransporteGuia f={f} poner={poner} remitente={e.remitente} disabled={g.enviando} onAgregarSecundario={g.agregarSecundario} onQuitarSecundario={g.quitarSecundario} />
          </PanelTarjeta>

          <PanelTarjeta icono="package" titulo="Productos" descripcion="Viaja todo lo traspasado. Escribe el peso de cada producto.">
            <LineasTraslado lineas={e.lineas} pesos={g.pesos} disabled={g.enviando} onPeso={g.ponerPeso} />
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
              <dd>{e.lineas.length}</dd>
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
          <button type="submit" className="primario pos-generar" disabled={g.enviando}>
            <Icono nombre="documento" tam={20} />
            {g.enviando ? 'Emitiendo…' : 'Emitir guía de remisión'}
          </button>
          <button type="button" className="boton-cabecera" disabled={g.enviando} onClick={() => navegar('/almacen/movimientos')}>
            Cancelar
          </button>
          <small className="celda-suave">La guía acompaña la mercadería: no mueve stock. Una guía no se edita; si hay un error, se anula y se emite otra.</small>
        </aside>
      </div>
    </form>
  )
}
