import { useEmpresas } from '../contexts/EmpresasContext'
import { Icono } from './IconosPanel'

const nombreDe = (e) => e.nombre_comercial || e.razon_social

/** Selector de la empresa que se está viendo. Con una sola empresa muestra una etiqueta. */
export default function ChipsEmpresa() {
  const { empresas, empresaActivaId, elegirEmpresa } = useEmpresas()

  if (empresas.length === 0) return null
  if (empresas.length === 1) {
    return (
      <span className="chip-empresa unica" title={`RUC ${empresas[0].ruc}`}>
        <Icono nombre="building" tam={17} />
        {nombreDe(empresas[0])}
      </span>
    )
  }

  return (
    <div role="group" aria-label="Empresa activa" className="chips-empresa">
      {empresas.map((e) => (
        <button
          key={e.id}
          type="button"
          className={`chip-empresa${e.id === empresaActivaId ? ' activa' : ''}`}
          aria-pressed={e.id === empresaActivaId}
          title={`RUC ${e.ruc}`}
          onClick={() => elegirEmpresa(e.id)}
        >
          {nombreDe(e)}
        </button>
      ))}
    </div>
  )
}
