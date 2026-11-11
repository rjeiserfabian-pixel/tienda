import { useQuery } from '@tanstack/react-query'
import { api } from '../../../core/api/client'
import Campo from '../../../shared/components/Campo'
import { Icono } from '../../../shared/components/IconosPanel'
import Interruptor from '../../../shared/components/Interruptor'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'

export const MAX_PUNTOS = 8
export const MAX_DESCRIPCION_WEB = 4000
const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/
const DECIMAL = (decimales) => new RegExp(`^\\d+([.,]\\d{1,${decimales}})?$`)

/** «Laptop Lenovo IdeaPad 15.3"» → «laptop-lenovo-ideapad-153»: minúsculas, números y guiones. */
export const aDireccionWeb = (texto) =>
  String(texto ?? '')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 180)
    .replace(/-+$/g, '')

/** Revisa en el navegador lo que se escribió para la tienda; el servidor valida otra vez. */
export function revisarTienda(f) {
  const e = {}
  if (f.slug.trim() && !SLUG.test(f.slug.trim())) e.slug = 'Usa solo letras minúsculas, números y guiones (ej. laptop-lenovo-i5).'
  if (f.garantia_meses !== '' && !/^\d{1,3}$/.test(String(f.garantia_meses).trim())) e.garantia_meses = 'Escribe los meses como número entero (de 0 a 240).'
  else if (f.garantia_meses !== '' && Number(f.garantia_meses) > 240) e.garantia_meses = 'La garantía admite hasta 240 meses.'
  if (f.peso_kg !== '' && !DECIMAL(3).test(String(f.peso_kg).trim())) e.peso_kg = 'Escribe el peso en kilos (hasta 3 decimales).'
  for (const campo of ['largo_cm', 'ancho_cm', 'alto_cm']) {
    if (f[campo] !== '' && !DECIMAL(2).test(String(f[campo]).trim())) e[campo] = 'Escribe la medida en centímetros (hasta 2 decimales).'
  }
  if (f.puntos_destacados.filter((p) => p.trim()).length > MAX_PUNTOS) e.puntos_destacados = `Admite hasta ${MAX_PUNTOS} puntos destacados.`
  return e
}

/** Lo que va en el PATCH del producto, ya limpio. */
export const datosDeTienda = (f, nuevo) => ({
  publicado_web: nuevo ? false : f.publicado_web,
  destacado: f.destacado,
  es_nuevo: f.es_nuevo,
  descripcion_web: f.descripcion_web.trim(),
  puntos_destacados: f.puntos_destacados.map((p) => p.trim()).filter(Boolean),
  slug: f.slug.trim(),
  garantia_meses: f.garantia_meses === '' ? null : Number(f.garantia_meses),
  peso_kg: f.peso_kg === '' ? null : String(f.peso_kg).trim().replace(',', '.'),
  largo_cm: f.largo_cm === '' ? null : String(f.largo_cm).trim().replace(',', '.'),
  ancho_cm: f.ancho_cm === '' ? null : String(f.ancho_cm).trim().replace(',', '.'),
  alto_cm: f.alto_cm === '' ? null : String(f.alto_cm).trim().replace(',', '.'),
})

/** Qué impide mostrar el producto en la tienda (vacío si se puede). */
function motivoSinPublicar({ registro, fotos }) {
  if (!registro) return 'Primero registra el producto y súbele al menos una foto.'
  if (registro.estado !== 'ACTIVO') return 'El producto debe estar activo para mostrarse en la tienda.'
  if (fotos.length === 0) return 'Sube al menos una foto del producto (en la sección Fotos, más abajo).'
  return ''
}

/**
 * Lo que la tienda virtual muestra del producto: si se publica, sus etiquetas, la dirección web,
 * la descripción, los puntos destacados, la garantía y las medidas para calcular el envío.
 */
export default function ParaLaTienda({ f, cambiar, errores, registro }) {
  const fotosConsulta = useQuery({
    queryKey: ['productos', 'fotos', registro?.id],
    queryFn: ({ signal }) => api.get(`/mantenimiento/productos/${registro.id}/fotos/`, { signal }).then((r) => r.data),
    enabled: Boolean(registro),
  })
  const fotos = fotosConsulta.data ?? []
  const motivo = motivoSinPublicar({ registro, fotos })
  const puntos = f.puntos_destacados

  const cambiarPunto = (indice, valor) => cambiar('puntos_destacados', puntos.map((p, i) => (i === indice ? valor : p)))

  return (
    <PanelTarjeta id="tienda" icono="store" titulo="Para la tienda" descripcion="Cómo se presenta este producto a los clientes en la tienda virtual.">
      <div className="tienda-publicar">
        <Interruptor
          activo={f.publicado_web}
          disabled={Boolean(motivo) && !f.publicado_web}
          onCambio={(v) => cambiar('publicado_web', v)}
          texto="Mostrar en la tienda"
          descripcion={f.publicado_web ? 'Los clientes pueden ver y comprar este producto.' : 'Oculto: solo lo ves tú en el sistema.'}
        />
        {motivo && !f.publicado_web && <p className="tienda-motivo" role="status">{motivo}</p>}
        {errores.publicado_web && <p role="alert" className="campo-error">{errores.publicado_web}</p>}
      </div>

      <div className="control-grilla tienda-etiquetas">
        <Interruptor activo={f.destacado} onCambio={(v) => cambiar('destacado', v)} texto="Destacado" descripcion="Aparece en las secciones destacadas de la tienda." />
        <Interruptor activo={f.es_nuevo} onCambio={(v) => cambiar('es_nuevo', v)} texto="Novedad" descripcion="Lleva la etiqueta «Nuevo»." />
      </div>

      <div className="maestro-campos">
        <div className="completo">
          <Campo
            etiqueta="Dirección web"
            icono="documento"
            error={errores.slug}
            ayuda="Es la parte final del enlace del producto. Solo letras minúsculas, números y guiones. Si la dejas vacía se crea sola al publicar."
            derecha={
              <button type="button" className="boton-consultar tienda-proponer" onClick={() => cambiar('slug', aDireccionWeb(f.nombre))} disabled={!f.nombre.trim()}>
                Proponer
              </button>
            }
          >
            {(p) => <input {...p} name="slug" value={f.slug} maxLength={200} placeholder="ej. laptop-lenovo-ideapad-15" onChange={(e) => cambiar('slug', e.target.value.toLowerCase())} />}
          </Campo>
        </div>
        <div className="completo">
          <Campo etiqueta="Descripción para la tienda" error={errores.descripcion_web} contador={{ actual: f.descripcion_web.length, max: MAX_DESCRIPCION_WEB }} ayuda="El texto que lee el cliente en la ficha del producto. Si la dejas vacía se usa la descripción interna.">
            {(p) => <textarea {...p} name="descripcion_web" rows={5} value={f.descripcion_web} maxLength={MAX_DESCRIPCION_WEB} placeholder="Cuenta para qué sirve, qué la hace especial y qué incluye." onChange={(e) => cambiar('descripcion_web', e.target.value)} />}
          </Campo>
        </div>
      </div>

      <div className="tienda-puntos">
        <div className="tienda-puntos-cab">
          <strong id="tienda-puntos-titulo">Puntos destacados</strong>
          <small className="celda-suave">Frases cortas que resumen lo mejor del producto (hasta {MAX_PUNTOS}).</small>
        </div>
        <ul aria-labelledby="tienda-puntos-titulo">
          {puntos.map((punto, i) => (
            <li key={i}>
              <input
                value={punto}
                maxLength={120}
                aria-label={`Punto destacado ${i + 1}`}
                placeholder="Ej. Pantalla IPS antirreflejo de 15.3 pulgadas"
                onChange={(e) => cambiarPunto(i, e.target.value)}
              />
              <button type="button" className="accion-icono peligro-suave" aria-label={`Quitar el punto destacado ${i + 1}`} onClick={() => cambiar('puntos_destacados', puntos.filter((_, j) => j !== i))}>
                <Icono nombre="papelera" tam={18} />
              </button>
            </li>
          ))}
        </ul>
        {puntos.length < MAX_PUNTOS && (
          <button type="button" onClick={() => cambiar('puntos_destacados', [...puntos, ''])}>
            <Icono nombre="agregar" tam={16} /> Agregar punto
          </button>
        )}
        {errores.puntos_destacados && <p role="alert" className="campo-error">{errores.puntos_destacados}</p>}
      </div>

      <div className="maestro-campos tienda-medidas">
        <Campo etiqueta="Garantía (meses)" error={errores.garantia_meses} ayuda="Se muestra en la ficha.">
          {(p) => <input {...p} name="garantia_meses" inputMode="numeric" value={f.garantia_meses} maxLength={3} placeholder="12" onChange={(e) => cambiar('garantia_meses', e.target.value.replace(/\D/g, ''))} />}
        </Campo>
        <Campo etiqueta="Peso (kg)" error={errores.peso_kg} ayuda="Con el embalaje, para calcular el envío.">
          {(p) => <input {...p} name="peso_kg" inputMode="decimal" value={f.peso_kg} maxLength={10} placeholder="1.6" onChange={(e) => cambiar('peso_kg', e.target.value)} />}
        </Campo>
        <Campo etiqueta="Largo (cm)" error={errores.largo_cm}>
          {(p) => <input {...p} name="largo_cm" inputMode="decimal" value={f.largo_cm} maxLength={9} placeholder="35" onChange={(e) => cambiar('largo_cm', e.target.value)} />}
        </Campo>
        <Campo etiqueta="Ancho (cm)" error={errores.ancho_cm}>
          {(p) => <input {...p} name="ancho_cm" inputMode="decimal" value={f.ancho_cm} maxLength={9} placeholder="25" onChange={(e) => cambiar('ancho_cm', e.target.value)} />}
        </Campo>
        <Campo etiqueta="Alto (cm)" error={errores.alto_cm}>
          {(p) => <input {...p} name="alto_cm" inputMode="decimal" value={f.alto_cm} maxLength={9} placeholder="3" onChange={(e) => cambiar('alto_cm', e.target.value)} />}
        </Campo>
      </div>
    </PanelTarjeta>
  )
}
