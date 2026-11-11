import { useQuery } from '@tanstack/react-query'
import { api, mensajeDeError } from '../../../core/api/client'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Interruptor from '../../../shared/components/Interruptor'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import '../../almacen/inventario.css'
import '../servicio-tecnico.css'

const EVENTOS = [
  ['aviso_recibido', 'RECIBIDO', 'Al recibir el equipo', 'Confirma el ingreso y le envía el enlace para ver el avance.'],
  ['aviso_presupuesto', 'PRESUPUESTO', 'Cuando hay presupuesto por aprobar', 'Le pide que se comunique para aprobarlo. No incluye precios.'],
  ['aviso_listo', 'LISTO', 'Cuando el equipo está listo', 'Le avisa que ya puede recogerlo.'],
  ['aviso_entregado', 'ENTREGADO', 'Al entregarlo', 'Le agradece y le envía el resumen con su garantía.'],
]

/** Qué avisos automáticos por WhatsApp manda el taller. Todo empieza apagado. */
export default function AvisosWhatsappPage() {
  const { empresaActivaId } = useEmpresas()
  const consulta = useQuery({
    queryKey: ['servicio', 'avisos-config', empresaActivaId],
    queryFn: ({ signal }) => api.get('/servicio-tecnico/avisos/configuracion/', { params: { empresa: empresaActivaId }, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId),
  })
  const guardar = useMutacion({
    mutationFn: (cambio) => api.put('/servicio-tecnico/avisos/configuracion/', cambio, { params: { empresa: empresaActivaId } }).then((r) => r.data),
    invalidar: [['servicio', 'avisos-config']],
    exito: 'Configuración guardada.',
  })
  const d = consulta.data
  const c = d?.configuracion
  const p = d?.proveedor

  return (
    <main className="listado">
      <CabeceraListado icono="chat" titulo="Avisos por WhatsApp" descripcion="Mensajes automáticos al cliente cuando su equipo avanza. Solo se envían si el cliente aceptó recibirlos al dejar su equipo." />
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(d)}>
        {d && (
          <>
            <PanelTarjeta icono="settings" titulo="Conexión con WhatsApp" descripcion="Se configura en el servidor, no desde aquí.">
              <p>
                Proveedor: <strong>{p.nombre === 'meta' ? 'WhatsApp Cloud API (Meta)' : p.nombre === 'consola' ? 'Solo pruebas (no envía mensajes reales)' : 'Apagado'}</strong>
                {' · '}
                <span className="pildora" data-tono={p.configurado ? 'verde' : 'ambar'}>
                  {p.configurado ? 'Listo para enviar' : 'Sin configurar'}
                </span>
              </p>
              {Object.keys(p.faltantes).length > 0 && (
                <ul className="celda-suave">
                  {Object.entries(p.faltantes).map(([evento, texto]) => (
                    <li key={evento}>
                      {EVENTOS.find((e) => e[1] === evento)?.[2] ?? evento}: {texto}
                    </li>
                  ))}
                </ul>
              )}
              <p className="celda-suave">Para enviar con Meta hace falta una cuenta de WhatsApp Business y una plantilla aprobada por cada aviso. Mientras tanto puedes avisar a mano desde la ficha de cada orden con el botón «Abrir WhatsApp».</p>
              <p className="celda-suave">Los clientes ven el estado en: {p.url_publica}/estado/…</p>
            </PanelTarjeta>

            <PanelTarjeta icono="bell" titulo="Avisos de esta empresa" descripcion="Elige cuáles se envían solos.">
              <div className="servicio-interruptores">
                <Interruptor activo={c.whatsapp_activo} disabled={guardar.isPending} texto="Enviar avisos automáticos por WhatsApp" descripcion="Apagado: no se envía nada, aunque el cliente lo haya aceptado." onCambio={(v) => guardar.mutate({ whatsapp_activo: v })} />
                {EVENTOS.map(([campo, , texto, descripcion]) => (
                  <Interruptor key={campo} activo={c[campo]} disabled={guardar.isPending || !c.whatsapp_activo} texto={texto} descripcion={descripcion} onCambio={(v) => guardar.mutate({ [campo]: v })} />
                ))}
              </div>
              {guardar.isError && (
                <p role="alert" className="campo-error">
                  {mensajeDeError(guardar.error)}
                </p>
              )}
            </PanelTarjeta>
          </>
        )}
      </EstadoConsulta>
    </main>
  )
}
