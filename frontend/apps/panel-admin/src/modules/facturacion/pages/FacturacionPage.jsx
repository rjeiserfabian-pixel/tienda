import { useState } from 'react'
import CabeceraListado from '../../../shared/components/CabeceraListado'
import ConfiguracionFacturacion from '../components/ConfiguracionFacturacion'
import DocumentosElectronicos from '../components/DocumentosElectronicos'
import '../facturacion.css'

const VISTAS = [
  ['documentos', 'Documentos'],
  ['configuracion', 'Configuración'],
]

/** Facturación electrónica: qué documentos se enviaron a SUNAT por la API, y cómo está configurada la empresa. */
export default function FacturacionPage() {
  const [vista, setVista] = useState('documentos')
  return (
    <main className="listado">
      <CabeceraListado icono="file" titulo="Facturación electrónica" descripcion="Envía a SUNAT las facturas, boletas, notas de crédito y guías de remisión por la API de facturación. Revisa el JSON antes de enviar y sigue el estado de cada envío." />
      <div className="segmentos" role="radiogroup" aria-label="Sección">
        {VISTAS.map(([valor, texto]) => (
          <button key={valor} type="button" role="radio" aria-checked={vista === valor} className={vista === valor ? 'activo' : undefined} onClick={() => setVista(valor)}>
            {texto}
          </button>
        ))}
      </div>
      {vista === 'documentos' ? <DocumentosElectronicos /> : <ConfiguracionFacturacion />}
    </main>
  )
}
