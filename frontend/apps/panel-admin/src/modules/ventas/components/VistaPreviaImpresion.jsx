import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Icono } from '../../../shared/components/IconosPanel'
import Modal from '../../../shared/components/Modal'
import '../ventas.css'

/** Los formatos de impresión: la hoja A4 y el ticket de 80 mm. `raiz` es la clase que solo se ve al imprimir. */
const FORMATOS = {
  A4: { nombre: 'A4 (hoja completa)', raiz: 'documento-raiz', hoja: 'vista-hoja vista-a4' },
  TICKET: { nombre: 'Ticket (80 mm)', raiz: 'ticket-raiz', hoja: 'vista-hoja vista-ticket' },
  ETIQUETA: { nombre: 'Etiqueta del equipo (62 × 38 mm)', raiz: 'etiqueta-raiz', hoja: 'vista-hoja vista-etiqueta' },
}

// El último formato que se usó con cada tipo de documento: es solo una comodidad, puede no haber almacenamiento.
const clave = (tipo) => `impresion_formato_${tipo}`
const recordado = (tipo, disponibles) => {
  try {
    const guardado = localStorage.getItem(clave(tipo))
    return disponibles.includes(guardado) ? guardado : null
  } catch {
    return null
  }
}
const recordar = (tipo, formato) => {
  try {
    localStorage.setItem(clave(tipo), formato)
  } catch {
    /* sin almacenamiento disponible: se ignora */
  }
}

/**
 * Vista previa de un documento antes de imprimirlo: se ve tal como saldrá, en hoja A4 o en ticket.
 * `formatos` trae el documento ya armado en cada formato (`{ A4, TICKET }`; basta con uno). «Imprimir»
 * abre el diálogo de impresión del navegador; para guardarlo como PDF se elige «Guardar como PDF» como
 * impresora. El documento que sale al papel se dibuja aparte, fuera de la pantalla.
 */
export default function VistaPreviaImpresion({ tipo, titulo, subtitulo, formatos, inicial = 'A4', onCerrar }) {
  const disponibles = Object.keys(FORMATOS).filter((f) => formatos[f])
  const [formato, setFormato] = useState(() => recordado(tipo, disponibles) ?? (disponibles.includes(inicial) ? inicial : disponibles[0]))
  const [imprimiendo, setImprimiendo] = useState(false)

  useEffect(() => {
    if (!imprimiendo) return undefined
    const fin = () => setImprimiendo(false)
    const pausa = setTimeout(() => window.print(), 250) // da tiempo a que el documento se dibuje
    window.addEventListener('afterprint', fin)
    return () => {
      clearTimeout(pausa)
      window.removeEventListener('afterprint', fin)
    }
  }, [imprimiendo])

  const elegir = (nuevo) => {
    setFormato(nuevo)
    recordar(tipo, nuevo)
  }
  const actual = FORMATOS[formato]

  return (
    <Modal titulo={titulo} subtitulo={subtitulo} onCerrar={onCerrar} ancho={940}>
      <div className="vista-barra">
        {disponibles.length > 1 ? (
          <label className="vista-formato">
            <span>Formato</span>
            <span className="campo-icono">
              <select value={formato} onChange={(e) => elegir(e.target.value)}>
                {disponibles.map((f) => (
                  <option key={f} value={f}>
                    {FORMATOS[f].nombre}
                  </option>
                ))}
              </select>
              <Icono nombre="chevronAbajo" tam={18} className="icono-der" />
            </span>
          </label>
        ) : (
          <span className="celda-suave">Formato: {actual.nombre}</span>
        )}
        <button type="button" className="primario boton-cabecera" disabled={imprimiendo} onClick={() => setImprimiendo(true)}>
          <Icono nombre="documento" tam={18} /> Imprimir
        </button>
        <button type="button" className="boton-cabecera" onClick={onCerrar}>
          Cerrar
        </button>
      </div>
      <p className="celda-suave">Para guardarlo como PDF, elige «Guardar como PDF» como impresora en la ventana de impresión.</p>
      <div className="vista-lienzo">
        <div className={actual.hoja}>{formatos[formato]}</div>
      </div>
      {imprimiendo && createPortal(<div className={actual.raiz}>{formatos[formato]}</div>, document.body)}
    </Modal>
  )
}
