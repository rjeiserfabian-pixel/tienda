import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import Interruptor from '../../../shared/components/Interruptor'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useEmpresas } from '../../../shared/contexts/EmpresasContext'
import { usePermisos } from '../../../shared/contexts/PermisosContext'
import { useMutacion } from '../../../shared/hooks/useMutacion'

const REGIMENES = [
  ['NORMAL', 'Normal: se vende con IGV'],
  ['AMAZONIA', 'Beneficio de la Amazonía'],
]

function Formulario({ config, empresaId, puedeEditar }) {
  const [regimen, setRegimen] = useState(config.regimen_igv)
  const [alCosto, setAlCosto] = useState(config.igv_compras_al_costo)
  const [error, setError] = useState('')
  const sinCambios = regimen === config.regimen_igv && alCosto === config.igv_compras_al_costo

  const guardar = useMutacion({
    mutationFn: () => api.patch('/mantenimiento/igv/configuracion/', { empresa: empresaId, regimen_igv: regimen, igv_compras_al_costo: alCosto }).then((r) => r.data),
    invalidar: [['igv-config']],
    exito: 'Régimen del IGV actualizado.',
    avisarError: false,
  })

  const enviar = (evento) => {
    evento.preventDefault()
    if (guardar.isPending || sinCambios || !puedeEditar) return
    setError('')
    guardar.mutate(undefined, { onError: (e) => setError(mensajeDeError(e)) })
  }

  return (
    <form onSubmit={enviar} noValidate>
      <fieldset disabled={!puedeEditar || guardar.isPending} className="sin-borde">
        <Campo etiqueta="Régimen del IGV" icono="calculator" tipo="select">
          {(p) => (
            <select {...p} value={regimen} onChange={(e) => setRegimen(e.target.value)}>
              {REGIMENES.map(([valor, texto]) => (
                <option key={valor} value={valor}>{texto}</option>
              ))}
            </select>
          )}
        </Campo>
        <div className="igv-explicacion" role="note">
          {regimen === 'AMAZONIA' ? (
            <ul>
              <li>Las <strong>ventas a clientes de la región</strong> salen <strong>exoneradas</strong> (precio neto).</li>
              <li>Las ventas a clientes de <strong>fuera de la región</strong> llevan IGV, que se suma al precio.</li>
              <li>Las compras a proveedores de <strong>fuera (Lima)</strong> vienen gravadas; las de proveedores de la región, exoneradas.</li>
              <li>Define la <strong>zona</strong> en la ficha de cada cliente y proveedor. Siempre se puede cambiar en cada operación.</li>
            </ul>
          ) : (
            <p>Todas las operaciones se tratan como gravadas (con IGV), sin importar la zona del cliente o proveedor.</p>
          )}
        </div>
        <Interruptor
          activo={alCosto}
          onCambio={setAlCosto}
          disabled={!puedeEditar || guardar.isPending}
          texto="El IGV de las compras gravadas se suma al costo"
          descripcion="Actívalo si la empresa no usa ese IGV como crédito fiscal (por ejemplo, si vende exonerado). Lo aplica el módulo de Compras. Confirma este punto con tu contador."
        />
      </fieldset>
      {error && <p role="alert" className="campo-error">{error}</p>}
      {puedeEditar && (
        <div className="fila-botones">
          <button type="submit" className="primario boton-cabecera" disabled={guardar.isPending || sinCambios}>
            <Icono nombre="shield" tam={19} /> {guardar.isPending ? 'Guardando…' : 'Guardar cambios'}
          </button>
        </div>
      )}
    </form>
  )
}

/** Régimen del IGV de la empresa activa: cómo se propone el IGV de cada compra y venta. */
export default function RegimenIgv() {
  const { empresaActivaId, empresaActiva } = useEmpresas()
  const { tiene } = usePermisos()
  const puedeEditar = tiene('MANTENIMIENTO.IGV.EDITAR', { organizacion: true })
  const consulta = useQuery({
    queryKey: ['igv-config', empresaActivaId],
    queryFn: ({ signal }) => api.get('/mantenimiento/igv/configuracion/', { params: { empresa: empresaActivaId }, signal }).then((r) => r.data),
    enabled: Boolean(empresaActivaId),
  })
  const nombre = empresaActiva?.nombre_comercial || empresaActiva?.razon_social || 'la empresa activa'

  return (
    <PanelTarjeta id="regimen" icono="building" titulo={`Régimen del IGV de ${nombre}`} descripcion="Cada empresa tiene el suyo. Cambia de empresa arriba para configurar la otra.">
      {consulta.isLoading && <p className="celda-suave" aria-busy="true">Cargando…</p>}
      {consulta.isError && <p role="alert" className="campo-error">{mensajeDeError(consulta.error)}</p>}
      {consulta.data && <Formulario key={JSON.stringify(consulta.data)} config={consulta.data} empresaId={empresaActivaId} puedeEditar={puedeEditar} />}
    </PanelTarjeta>
  )
}
