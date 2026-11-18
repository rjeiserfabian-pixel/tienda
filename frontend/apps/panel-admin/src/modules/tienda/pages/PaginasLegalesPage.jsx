import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api, mensajeDeError } from '../../../core/api/client'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import Campo from '../../../shared/components/Campo'
import EstadoConsulta from '../../../shared/components/EstadoConsulta'
import Interruptor from '../../../shared/components/Interruptor'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { useMutacion } from '../../../shared/hooks/useMutacion'
import { fechaHora } from '../ofertas'
import '../tienda.css'
import '../pagos.css'

const CLAVE = ['tienda', 'paginas']
const MAX = 30000

function Editor({ pagina }) {
  const [contenido, setContenido] = useState(pagina.contenido)
  const [publicada, setPublicada] = useState(pagina.publicada)
  const [error, setError] = useState('')
  useEffect(() => {
    setContenido(pagina.contenido)
    setPublicada(pagina.publicada)
  }, [pagina.contenido, pagina.publicada])

  const guardar = useMutacion({
    mutationFn: () => api.put(`/tienda/admin/paginas/${pagina.slug}/`, { contenido, publicada }).then((r) => r.data),
    invalidar: [CLAVE],
    exito: publicada ? 'Página guardada y publicada.' : 'Borrador guardado.',
    avisarError: false,
    alExito: () => setError(''),
  })
  const cambiado = contenido !== pagina.contenido || publicada !== pagina.publicada

  return (
    <PanelTarjeta
      id={`pagina-${pagina.slug}`}
      icono="file"
      titulo={pagina.titulo}
      descripcion={pagina.publicada ? `Publicada · se ve en /legal/${pagina.slug}` : 'Borrador: todavía no se ve en la tienda.'}
    >
      <form
        noValidate
        className="envios-form"
        onSubmit={(e) => {
          e.preventDefault()
          guardar.mutate(undefined, { onError: (x) => setError(mensajeDeError(x)) })
        }}
      >
        <Campo
          etiqueta="Texto de la página"
          error={error}
          ayuda="Separa los párrafos con una línea en blanco. Una línea que empiece con «# » se muestra como subtítulo. No se acepta HTML."
          contador={{ actual: contenido.length, max: MAX }}
        >
          {(p) => <textarea {...p} name={`contenido-${pagina.slug}`} rows={12} maxLength={MAX} value={contenido} onChange={(e) => setContenido(e.target.value)} />}
        </Campo>
        <Interruptor
          activo={publicada}
          onCambio={setPublicada}
          texto={publicada ? 'Publicada en la tienda' : 'Borrador'}
          descripcion={publicada ? 'Aparece en el pie de la tienda.' : 'Solo tú la ves.'}
        />
        <div className="pagos-pie">
          <button type="submit" className="primario" disabled={!cambiado || guardar.isPending}>
            {guardar.isPending ? 'Guardando…' : 'Guardar'}
          </button>
          {!contenido.trim() && (
            <button type="button" onClick={() => setContenido(pagina.sugerencia)}>
              Usar un esquema para empezar
            </button>
          )}
          {pagina.actualizada && <small className="celda-suave">Última edición: {fechaHora(pagina.actualizada)}</small>}
        </div>
      </form>
    </PanelTarjeta>
  )
}

/** Textos legales de la tienda que el negocio escribe y publica. */
export default function PaginasLegalesPage() {
  const consulta = useQuery({
    queryKey: CLAVE,
    queryFn: ({ signal }) => api.get('/tienda/admin/paginas/', { signal }).then((r) => r.data),
    refetchOnWindowFocus: false,
  })
  return (
    <main className="listado tienda-pagina pagos-pagina">
      <CabeceraListado
        icono="file"
        titulo="Páginas legales"
        descripcion="Términos y condiciones, privacidad, cambios y envíos. El sistema te da un esquema para empezar, pero el contenido debe revisarlo tu asesor legal: es tu responsabilidad ante tus clientes."
      />
      <EstadoConsulta consulta={consulta} hayDatos={Boolean(consulta.data)}>
        <div className="pagos-form">
          {consulta.data?.paginas.map((p) => (
            <Editor key={p.slug} pagina={p} />
          ))}
        </div>
      </EstadoConsulta>
    </main>
  )
}
