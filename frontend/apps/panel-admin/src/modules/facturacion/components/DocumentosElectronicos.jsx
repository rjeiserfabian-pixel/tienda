import { useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import { Buscador } from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import { FilaVacia } from '../../../shared/components/EstadoVacio'
import { Icono } from '../../../shared/components/IconosPanel'
import Paginacion from '../../../shared/components/Paginacion'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useNotificar } from '../../../shared/contexts/NotificacionesContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useDebounce } from '../../../shared/hooks/useDebounce'
import { useListado } from '../../../shared/hooks/useListado'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { ESTADOS_ENVIO, FILTROS_ENVIO, fechaCorta, importe, ORIGENES } from '../facturacion'
import '../facturacion.css'
import VistaPreviaJsonModal from './VistaPreviaJsonModal'

/** Los documentos electrónicos con el estado de su envío a SUNAT, y las acciones para verlos y enviarlos. */
export default function DocumentosElectronicos() {
  const { empresaActivaId } = useEmpresas()
  const { tiene } = usePermisos()
  const notificar = useNotificar()
  const puedeEnviar = tiene('FACTURACION.ENVIAR_SUNAT')
  const [origen, setOrigen] = useState('COMPROBANTE')
  const [envio, setEnvio] = useState('')
  const [busqueda, setBusqueda] = useState('')
  const [pagina, setPagina] = useState(1)
  const [tamano, setTamano] = useState(25)
  const [viendo, setViendo] = useState(null)
  const q = useDebounce(busqueda, 400)

  const consulta = useListado(['facturacion', 'documentos'], '/facturacion/documentos/', { empresa: empresaActivaId, origen, envio, q, page: pagina, page_size: tamano }, { enabled: Boolean(empresaActivaId) })
  const filas = consulta.data?.results ?? []

  const enviar = useMutacion({
    mutationFn: ({ origen: o, id }) => api.post('/facturacion/enviar/', { origen: o, id }, { timeout: 60_000 }).then((r) => r.data),
    invalidar: [['facturacion']],
    avisarError: false,
    alExito: (datos) => {
      if (datos.estado === 'ENVIADO') notificar('exito', datos.mensaje || 'Enviado a la API.')
      else notificar('error', datos.mensaje || 'La API no pudo recibir el documento.')
    },
  })
  const enviando = enviar.isPending ? enviar.variables : null

  const cambiar = (poner) => (valor) => {
    poner(valor)
    setPagina(1)
  }

  const pedirEnvio = (doc) => {
    if (enviar.isPending) return
    enviar.mutate({ origen: doc.origen, id: doc.id }, { onError: (e) => notificar('error', mensajeDeError(e)) })
  }

  return (
    <section aria-label="Documentos electrónicos">
      <div className="barra-fe">
        <div className="segmentos" role="radiogroup" aria-label="Tipo de documento">
          {Object.entries(ORIGENES).map(([valor, texto]) => (
            <button key={valor} type="button" role="radio" aria-checked={origen === valor} className={origen === valor ? 'activo' : undefined} onClick={() => cambiar(setOrigen)(valor)}>
              {texto}
            </button>
          ))}
        </div>
        <Buscador valor={busqueda} onCambio={cambiar(setBusqueda)} etiqueta="Buscar un documento" placeholder="Serie o número…" />
        <select className="boton-cabecera" aria-label="Estado del envío" value={envio} onChange={(e) => cambiar(setEnvio)(e.target.value)}>
          {FILTROS_ENVIO.map(([valor, texto]) => (
            <option key={valor} value={valor}>
              {texto}
            </option>
          ))}
        </select>
      </div>

      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="marco-tabla">
          <table className="tabla-datos">
            <thead>
              <tr>
                <th>Documento</th>
                <th>Fecha</th>
                <th>{origen === 'GUIA' ? 'Destinatario' : 'Cliente'}</th>
                {origen !== 'GUIA' && <th className="num">Total</th>}
                <th>Envío a SUNAT</th>
                <th className="centrado">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filas.length === 0 && <FilaVacia columnas={origen === 'GUIA' ? 5 : 6} icono="file" titulo="No hay documentos con esos filtros" descripcion="Solo aparecen los documentos con serie electrónica (facturas, boletas, notas de crédito y guías)." />}
              {filas.map((d) => {
                const estado = d.envio ? ESTADOS_ENVIO[d.envio.estado] : null
                const ocupado = enviando?.id === d.id && enviando?.origen === d.origen
                const yaEnviado = d.envio?.estado === 'ENVIADO'
                return (
                  <tr key={`${d.origen}-${d.id}`} className={d.estado === 'ANULADO' ? 'anulado' : undefined}>
                    <td>
                      <strong>{d.numero}</strong>
                      <span className="sub-texto">{d.tipo_nombre}</span>
                    </td>
                    <td>{fechaCorta(d.fecha)}</td>
                    <td>{d.cliente}</td>
                    {origen !== 'GUIA' && <td className="num">{importe(d.total)}</td>}
                    <td>
                      {d.estado === 'ANULADO' ? (
                        <span className="pildora" data-tono="gris">Anulado</span>
                      ) : estado ? (
                        <>
                          <span className="pildora" data-tono={estado.tono}>{estado.texto}</span>
                          {d.envio.mensaje && <span className="sub-texto fe-mensaje" title={d.envio.mensaje}>{d.envio.mensaje}</span>}
                        </>
                      ) : (
                        <span className="pildora" data-tono="gris">Sin enviar</span>
                      )}
                    </td>
                    <td className="centrado">
                      <span className="acciones-fila">
                        <button type="button" className="accion-icono ver" aria-label={`Ver el JSON de ${d.numero}`} title="Ver el JSON que se enviaría" onClick={() => setViendo(d)}>
                          <Icono nombre="ojo" tam={19} />
                        </button>
                        {puedeEnviar && d.estado !== 'ANULADO' && !yaEnviado && (
                          <button type="button" className="accion-icono editar" aria-label={`${d.envio ? 'Reintentar el envío de' : 'Enviar a SUNAT'} ${d.numero}`} title={d.envio ? 'Reintentar el envío' : 'Enviar a SUNAT'} disabled={enviar.isPending} onClick={() => pedirEnvio(d)}>
                            {ocupado ? '…' : <Icono nombre="exportar" tam={19} />}
                          </button>
                        )}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </EstadoConsulta>
      <Paginacion pagina={pagina} tamano={tamano} total={consulta.data?.count ?? 0} onPagina={setPagina} onTamano={cambiar(setTamano)} />
      {viendo && <VistaPreviaJsonModal documento={viendo} onCerrar={() => setViendo(null)} />}
    </section>
  )
}
