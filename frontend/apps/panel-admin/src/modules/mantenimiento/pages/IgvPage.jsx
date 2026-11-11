import CabeceraListado from '../../../shared/components/CabeceraListado'
import AfectacionesIgv from '../components/AfectacionesIgv'
import RegimenIgv from '../components/RegimenIgv'
import TasasImpuesto from '../components/TasasImpuesto'
import '../components/igv.css'

/** IGV e impuestos: régimen de la empresa, tasas con vigencia y afectaciones de SUNAT. */
export default function IgvPage() {
  return (
    <main className="listado igv-pagina">
      <CabeceraListado icono="calculator" titulo="IGV e impuestos" descripcion="Cómo se calcula el IGV en tus compras y ventas: régimen de cada empresa, tasas vigentes y tipos de operación." />
      <RegimenIgv />
      <TasasImpuesto />
      <AfectacionesIgv />
    </main>
  )
}
