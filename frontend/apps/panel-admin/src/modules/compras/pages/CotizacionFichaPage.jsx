import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import BotonVolver from '../../../shared/components/BotonVolver'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Can from '../../../shared/components/Can'
import ConfirmarModal from '../../../shared/components/ConfirmarModal'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { Icono } from '../../../shared/components/IconosPanel'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { fechaHora } from '../../../shared/utils/fechas'
import { cantidad as formatoCantidad, fechaCorta } from '../../almacen/inventario'
import VistaPreviaImpresion from '../../ventas/components/VistaPreviaImpresion'
import AccionCotizacionModal from '../components/AccionCotizacionModal'
import AdjudicarCotizacion, { ResultadoAdjudicacion } from '../components/AdjudicarCotizacion'
import ComparativoCotizacion from '../components/ComparativoCotizacion'
import CotizacionA4 from '../components/CotizacionA4'
import ImportarRespuestaModal from '../components/ImportarRespuestaModal'
import ProveedoresCotizacion, { useQuitarProveedor } from '../components/ProveedoresCotizacion'
import RespuestaManualModal from '../components/RespuestaManualModal'
import { accionesDe, ESTADOS_COTIZACION, sePuedeEditar } from '../cotizaciones'
import { useCotizacion } from '../hooks/useCotizaciones'
import '../../almacen/inventario.css'
import '../compras.css'
import '../cotizaciones.css'

const RUTA = '/compras/cotizaciones'

/** Datos generales de la cotización. */
function DatosCotizacion({ c }) {
  return (
    <dl className="datos-lista">
      <dt>Almacén de destino</dt>
      <dd>{c.almacen_nombre}</dd>
      <dt>Fecha</dt>
      <dd>{fechaCorta(c.fecha)}</dd>
      {c.fecha_limite && (
        <>
          <dt>Responder hasta</dt>
          <dd>{fechaCorta(c.fecha_limite)}</dd>
        </>
      )}
      <dt>Moneda y precios</dt>
      <dd>
        {c.moneda === 'USD' ? 'Dólares' : 'Soles'} · {c.precios_incluyen_igv ? 'con IGV incluido' : 'sin IGV'}
      </dd>
      {c.adjudicada_en && (
        <>
          <dt>Adjudicada</dt>
          <dd>{fechaHora(c.adjudicada_en)}</dd>
        </>
      )}
      {c.observacion && (
        <>
          <dt>Observación</dt>
          <dd>{c.observacion}</dd>
        </>
      )}
    </dl>
  )
}

function Ficha({ cotizacion: c }) {
  const navegar = useNavigate()
  const [dialogo, setDialogo] = useState(null) // null | 'anular' | 'imprimir' | {tipo, proveedor}
  const quitar = useQuitarProveedor(c.id)
  const estado = ESTADOS_COTIZACION[c.estado] ?? { texto: c.estado_nombre, tono: 'gris' }
  const acciones = accionesDe(c.estado)
  // El selector de ganadores se reinicia cuando cambian las respuestas.
  const huella = JSON.stringify(c.comparativo.proveedores.map((p) => [p.respuesta, p.estado, p.total]))
  const hayRespuestas = c.comparativo.proveedores.some((p) => p.estado === 'RESPONDIDA')
  const cierre = () => setDialogo(null)
  const proveedorDe = typeof dialogo === 'object' && dialogo ? dialogo.proveedor : null

  return (
    <>
      <CabeceraListado icono="cotizacion" titulo={`Cotización ${c.codigo}`} descripcion={`${c.almacen_nombre} · ${fechaCorta(c.fecha)}`}>
        <span className="pildora" data-tono={estado.tono}>
          {estado.texto}
        </span>
        <button type="button" className="boton-cabecera" onClick={() => setDialogo('imprimir')}>
          <Icono nombre="documento" tam={19} /> Imprimir
        </button>
        <Can permiso="COTIZACIONES_COMPRA.CREAR">
          {sePuedeEditar(c) && (
            <button type="button" className="boton-cabecera" onClick={() => navegar(`${RUTA}/${c.id}/editar`)}>
              <Icono nombre="lapiz" tam={19} /> Editar
            </button>
          )}
          {acciones.anular && (
            <button type="button" className="peligro boton-cabecera" onClick={() => setDialogo('anular')}>
              <Icono nombre="cerrar" tam={19} /> Anular
            </button>
          )}
        </Can>
      </CabeceraListado>

      {c.estado === 'ANULADA' && (
        <p role="status" className="modal-aviso">
          <strong>Anulada:</strong> {c.motivo_anulacion}
          {c.anulada_en ? ` (${fechaHora(c.anulada_en)})` : ''}
        </p>
      )}

      <PanelTarjeta icono="documento" titulo="Datos de la cotización">
        <DatosCotizacion c={c} />
      </PanelTarjeta>

      <PanelTarjeta icono="package" titulo="Productos pedidos" descripcion="Lo que se pidió cotizar. Los precios están en el comparativo.">
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th className="centrado">#</th>
                <th>Producto</th>
                <th>Unidad</th>
                <th className="num">Cantidad</th>
              </tr>
            </thead>
            <tbody>
              {c.lineas.map((l) => (
                <tr key={l.id}>
                  <td className="centrado celda-suave">{l.posicion}</td>
                  <td className="col-texto">
                    {l.producto_nombre}
                    <span className="sub-texto">{l.producto_codigo}</span>
                  </td>
                  <td className="celda-suave">{l.unidad}</td>
                  <td className="num">{formatoCantidad(l.cantidad)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </PanelTarjeta>

      <PanelTarjeta icono="handshake" titulo="Proveedores" descripcion="Envíales la solicitud por WhatsApp o correo (sin precios), y registra lo que respondan a mano o importando el Excel de la plantilla.">
        <ProveedoresCotizacion cotizacion={c} onAccion={setDialogo} />
      </PanelTarjeta>

      <PanelTarjeta icono="chart" titulo="Comparativo" descripcion="Precios lado a lado. El mejor precio de cada producto y el mejor total se marcan solos.">
        <ComparativoCotizacion cotizacion={c} />
      </PanelTarjeta>

      {acciones.adjudicar && hayRespuestas && (
        <Can permiso="COTIZACIONES_COMPRA.ADJUDICAR">
          <PanelTarjeta icono="checklist" titulo="Elegir ganadores" descripcion="Elige quién te vende cada producto (pueden ser proveedores distintos). Se crea una orden de compra en borrador por cada proveedor ganador.">
            <AdjudicarCotizacion key={huella} cotizacion={c} />
          </PanelTarjeta>
        </Can>
      )}

      {c.estado === 'ADJUDICADA' && (
        <PanelTarjeta icono="checklist" titulo="Resultado de la adjudicación" descripcion="Quién ganó cada producto y las órdenes de compra que salieron.">
          <ResultadoAdjudicacion cotizacion={c} />
        </PanelTarjeta>
      )}

      {dialogo === 'anular' && <AccionCotizacionModal cotizacion={c} accion="anular" onCerrar={cierre} />}
      {proveedorDe && dialogo.tipo === 'declinar' && <AccionCotizacionModal cotizacion={c} accion="declinar" respuesta={proveedorDe.respuesta} nombreProveedor={proveedorDe.nombre} onCerrar={cierre} />}
      {proveedorDe && dialogo.tipo === 'respuesta' && <RespuestaManualModal cotizacion={c} respuesta={proveedorDe.respuesta} nombreProveedor={proveedorDe.nombre} onCerrar={cierre} />}
      {proveedorDe && dialogo.tipo === 'importar' && <ImportarRespuestaModal cotizacion={c} respuesta={proveedorDe.respuesta} nombreProveedor={proveedorDe.nombre} onCerrar={cierre} />}
      {proveedorDe && dialogo.tipo === 'quitar' && (
        <ConfirmarModal
          titulo="Quitar proveedor"
          mensaje={`¿Quitar a ${proveedorDe.nombre} de esta cotización? Todavía no respondió.`}
          textoConfirmar="Quitar"
          enviando={quitar.isPending}
          onConfirmar={() => quitar.mutate(proveedorDe.respuesta, { onSuccess: cierre })}
          onCerrar={cierre}
        />
      )}
      {dialogo === 'imprimir' && <VistaPreviaImpresion tipo="cotizacion-compra" titulo={`Cotización ${c.codigo}`} subtitulo="Solicitud sin precios" formatos={{ A4: <CotizacionA4 datos={c} /> }} onCerrar={cierre} />}
    </>
  )
}

/** Ficha de una cotización: datos, proveedores con sus respuestas, comparativo y elección de ganadores. */
export default function CotizacionFichaPage() {
  const { id } = useParams()
  const consulta = useCotizacion(id)
  return (
    <main className="listado">
      <BotonVolver ruta={RUTA} texto="Volver a Cotizaciones" />
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)} vacio="La cotización no existe.">
        {consulta.data && <Ficha cotizacion={consulta.data} />}
      </EstadoConsulta>
    </main>
  )
}
