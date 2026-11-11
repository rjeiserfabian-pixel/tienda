import Campo from '../../../shared/components/Campo'
import Interruptor from '../../../shared/components/Interruptor'
import PanelTarjeta from '../../../shared/components/PanelTarjeta'
import { MAX_AVISO, MAX_PUNTO, TEXTOS } from '../configuracion'
import LogoTienda from './LogoTienda'

/** Un campo de texto con contador, ligado al formulario por su nombre. */
function Texto({ form, errores, cambiar, nombre, etiqueta, ayuda, placeholder, tipo = 'text', area = false }) {
  const max = TEXTOS[nombre]
  const props = {
    name: nombre,
    value: form[nombre],
    maxLength: max,
    placeholder,
    onChange: (e) => cambiar(nombre, e.target.value),
  }
  return (
    <Campo etiqueta={etiqueta} error={errores[nombre]} ayuda={ayuda} contador={{ actual: form[nombre].length, max }}>
      {(p) => (area ? <textarea {...p} {...props} rows={2} /> : <input {...p} {...props} type={tipo} />)}
    </Campo>
  )
}

/** Lista corta de frases (barra superior o puntos del bloque de servicio): una casilla por frase. */
function Frases({ etiqueta, lista, max, error, alCambiar, ayuda }) {
  return (
    <fieldset className="tienda-frases">
      <legend>{etiqueta}</legend>
      {ayuda && <small className="campo-ayuda">{ayuda}</small>}
      {lista.map((valor, i) => (
        <Campo key={i} etiqueta={`${etiqueta} ${i + 1}`} contador={{ actual: valor.length, max }}>
          {(p) => (
            <input {...p} value={valor} maxLength={max} onChange={(e) => alCambiar(lista.map((x, j) => (j === i ? e.target.value : x)))} />
          )}
        </Campo>
      ))}
      {error && (
        <p role="alert" className="campo-error">
          {error}
        </p>
      )}
    </fieldset>
  )
}

const aTexto = (e) => (Array.isArray(e) ? e.flat().join(' ') : e && typeof e === 'object' ? Object.values(e).join(' ') : e)

const ayudaEmpresa = (valor) => (valor ? `Vacío: se usa «${valor}» de la empresa principal.` : undefined)

/** Marca, contacto, redes, textos y legales de la tienda. Lo vacío de contacto usa la empresa principal. */
export default function ContenidoTienda({ datos, form, errores, cambiar, clave }) {
  const emp = datos.empresa_principal
  const t = { form, errores, cambiar }
  const colorValido = /^#[0-9a-fA-F]{6}$/.test(form.color_principal)
  return (
    <>
      <PanelTarjeta
        id="config-marca"
        icono="store"
        titulo="Marca y logo"
        descripcion="Cómo se ve la tienda. Este logo es solo de la tienda (junta a las dos empresas); cada empresa conserva el suyo en sus comprobantes."
      >
        <LogoTienda clave={clave} tieneLogo={datos.tiene_logo} version={datos.logo_version} />
        <div className="tienda-config-interruptor">
          <Interruptor
            activo={form.nombre_junto_al_logo}
            onCambio={(v) => cambiar('nombre_junto_al_logo', v)}
            texto="Mostrar el nombre de la tienda junto al logo"
            descripcion={`Escribe «${datos.nombre || 'el nombre'}» al lado del logo en la cabecera y el pie. Apágalo si tu logo ya trae el nombre.`}
          />
        </div>
        <div className="maestro-campos">
          <Texto
            {...t}
            nombre="descripcion"
            etiqueta="Frase de la tienda"
            area
            ayuda="Sale en el pie de página y ayuda a que Google entienda de qué trata la tienda."
          />
          <div className="tienda-color">
            <Campo
              etiqueta="Color principal"
              error={errores.color_principal}
              ayuda="Botones y detalles. Vacío = el color por defecto. Debe ser oscuro para que el texto blanco se lea."
            >
              {(p) => (
                <input
                  {...p}
                  name="color_principal"
                  value={form.color_principal}
                  maxLength={7}
                  placeholder="#E2372A"
                  onChange={(e) => cambiar('color_principal', e.target.value)}
                />
              )}
            </Campo>
            <input
              type="color"
              className="tienda-color-selector"
              aria-label="Elegir el color principal"
              value={colorValido ? form.color_principal : '#e2372a'}
              onChange={(e) => cambiar('color_principal', e.target.value.toUpperCase())}
            />
            <span className="tienda-color-muestra" style={colorValido ? { background: form.color_principal } : undefined} aria-hidden="true">
              Comprar
            </span>
          </div>
        </div>
      </PanelTarjeta>

      <PanelTarjeta
        id="config-contacto"
        icono="telefono"
        titulo="Contacto"
        descripcion="Lo que el cliente ve para comunicarse. Si dejas vacío teléfono, correo o dirección, se usan los de la empresa principal."
      >
        <div className="maestro-campos">
          <Texto
            {...t}
            nombre="whatsapp"
            etiqueta="WhatsApp de ventas"
            placeholder="987 654 321"
            ayuda="Activa los botones «Comprar por WhatsApp». Si no pones código de país, se asume Perú (51)."
          />
          <Texto {...t} nombre="telefono" etiqueta="Teléfono" placeholder={emp?.telefono || ''} ayuda={ayudaEmpresa(emp?.telefono)} />
          <Texto {...t} nombre="correo" etiqueta="Correo" tipo="email" placeholder={emp?.correo || ''} ayuda={ayudaEmpresa(emp?.correo)} />
          <Texto {...t} nombre="direccion" etiqueta="Dirección de la tienda" placeholder={emp?.direccion || ''} ayuda={ayudaEmpresa(emp?.direccion)} />
          <Texto {...t} nombre="horario" etiqueta="Horario de atención" placeholder="Lunes a sábado, 9:00 a 19:00" />
          <Texto {...t} nombre="mapa_url" etiqueta="Enlace al mapa" placeholder="https://maps.google.com/…" />
        </div>
      </PanelTarjeta>

      <PanelTarjeta id="config-redes" icono="chat" titulo="Redes sociales" descripcion="Opcionales: solo se muestran las que llenes. Escribe el enlace completo.">
        <div className="maestro-campos">
          <Texto {...t} nombre="facebook" etiqueta="Facebook" placeholder="https://facebook.com/…" />
          <Texto {...t} nombre="instagram" etiqueta="Instagram" placeholder="https://instagram.com/…" />
          <Texto {...t} nombre="tiktok" etiqueta="TikTok" placeholder="https://tiktok.com/@…" />
          <Texto {...t} nombre="youtube" etiqueta="YouTube" placeholder="https://youtube.com/@…" />
        </div>
      </PanelTarjeta>

      <PanelTarjeta
        id="config-textos"
        icono="documento"
        titulo="Textos de la tienda"
        descripcion="Los mensajes de la portada y de las fichas. Lo que dejes vacío no se muestra o usa un texto neutro."
      >
        <Frases
          etiqueta="Barra superior"
          ayuda="Hasta 3 frases cortas arriba de todas las páginas (envíos, garantía, etc.)."
          lista={form.avisos}
          max={MAX_AVISO}
          error={aTexto(errores.avisos)}
          alCambiar={(v) => cambiar('avisos', v)}
        />
        <div className="maestro-campos">
          <Texto {...t} nombre="portada_etiqueta" etiqueta="Portada: etiqueta pequeña" />
          <Texto {...t} nombre="portada_titulo" etiqueta="Portada: título" />
          <Texto {...t} nombre="portada_subtitulo" etiqueta="Portada: subtítulo" area />
          <Texto {...t} nombre="garantia_texto" etiqueta="Texto de garantía" area />
          <Texto {...t} nombre="entrega_texto" etiqueta="Texto de envío o recojo" area />
        </div>

        <div className="tienda-config-interruptor">
          <Interruptor
            activo={form.servicio_visible}
            onCambio={(v) => cambiar('servicio_visible', v)}
            texto="Mostrar el bloque de servicio técnico"
            descripcion="Una sección del inicio que invita a reparar equipos. Apágala si tu empresa no da este servicio."
          />
        </div>
        {form.servicio_visible && (
          <>
            <div className="maestro-campos">
              <Texto {...t} nombre="servicio_titulo" etiqueta="Servicio técnico: título" />
              <Texto {...t} nombre="servicio_texto" etiqueta="Servicio técnico: descripción" area />
            </div>
            <Frases
              etiqueta="Servicio técnico: puntos"
              lista={form.servicio_puntos}
              max={MAX_PUNTO}
              error={aTexto(errores.servicio_puntos)}
              alCambiar={(v) => cambiar('servicio_puntos', v)}
              ayuda="Hasta 4 ventajas cortas. Escribe solo las que puedas cumplir."
            />
          </>
        )}
      </PanelTarjeta>

      <PanelTarjeta
        id="config-legales"
        icono="shield"
        titulo="Datos legales"
        descripcion="La razón social y el RUC salen de la ficha de la empresa principal (se cambian en Organización › Empresas)."
      >
        <dl className="tienda-datos-legales">
          <div>
            <dt>Razón social</dt>
            <dd>{emp?.razon_social || '—'}</dd>
          </div>
          <div>
            <dt>RUC</dt>
            <dd>{emp?.ruc || '—'}</dd>
          </div>
        </dl>
        <div className="maestro-campos">
          <Texto
            {...t}
            nombre="libro_reclamaciones_url"
            etiqueta="Libro de reclamaciones (enlace)"
            placeholder="https://…"
            ayuda="En Perú es obligatorio para tiendas en línea."
          />
          <Texto {...t} nombre="terminos_url" etiqueta="Términos y condiciones (enlace)" placeholder="https://…" />
          <Texto {...t} nombre="privacidad_url" etiqueta="Política de privacidad (enlace)" placeholder="https://…" />
        </div>
      </PanelTarjeta>
    </>
  )
}
