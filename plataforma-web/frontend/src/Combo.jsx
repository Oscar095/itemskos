import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Info, Loader2, Lock, Plus, Search, X, XCircle } from "lucide-react";
import { pedir } from "./api";
import { Aviso, BTN_PRIMARIO, BTN_SECUNDARIO } from "./components/ui";

// Igual que matcher.norm del backend: "Diseño  nuevo" y "DISENO NUEVO" son la misma.
const norm = (t) =>
  (t || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toUpperCase()
    .replace(/[^A-Z0-9]+/g, " ").trim();

// Mismo aspecto que INPUT de ui.jsx, con hueco a la izquierda para la lupa.
const INPUT_BUSCAR =
  "w-full border border-slate-200 rounded-xl pl-9 pr-3 py-2.5 text-sm text-slate-700 bg-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 shadow-sm";
// Versiones compactas de los botones del sistema (sin pisar clases en conflicto).
const chico = (btn) => btn.replace("px-4 py-2", "px-3 py-1.5").replace("text-sm", "text-xs");
const BTN_PRIMARIO_CHICO = chico(BTN_PRIMARIO);
const BTN_SECUNDARIO_CHICO = chico(BTN_SECUNDARIO);

/**
 * Selector con busqueda contra el backend.
 *
 * Es la pieza central del proyecto: sustituye los campos de texto libre que hoy
 * tiene SharePoint. El vendedor escribe para filtrar, pero SOLO puede quedarse
 * con una opcion real del catalogo de Siesa (salvo que `permitirNuevo` este
 * activo, para clientes que aun no existen alla).
 *
 * Con `crear` ({ vistaPrevia(texto), crear(texto) }) ofrece dar de alta en
 * Siesa lo que no aparece. Pide confirmacion mostrando el codigo que tomaria,
 * porque el alta no se puede deshacer desde aqui.
 *
 * Sin `crear`, `avisoSinAlta` (texto) explica en la lista que hacer cuando lo
 * buscado no existe (p. ej. pedir el alta a alguien con permiso).
 */
export default function Combo({
  etiqueta,
  endpoint,
  campoValor,
  campoTexto,
  valor,
  onChange,
  permitirNuevo = false,
  textoNuevo = "",
  onTextoNuevo = () => {},
  placeholder = "Escribe para buscar…",
  crear = null,
  avisoSinAlta = null,
}) {
  const [consulta, setConsulta] = useState("");
  const [opciones, setOpciones] = useState([]);
  const [abierto, setAbierto] = useState(false);
  const [cargando, setCargando] = useState(false);
  // null | { paso: "revisando" | "confirmar" | "creando" | "error", ... }
  const [alta, setAlta] = useState(null);
  const [creada, setCreada] = useState(null);
  const contenedor = useRef(null);

  const elegir = (o) => {
    onChange(o[campoValor]);
    setOpciones([o]);
    setAbierto(false);
    setConsulta("");
    setAlta(null);
    if (permitirNuevo) onTextoNuevo("");
  };

  const pedirAlta = async () => {
    const texto = consulta.trim();
    setAbierto(false);
    setAlta({ paso: "revisando", texto });
    try {
      setAlta({ paso: "confirmar", texto, ...(await crear.vistaPrevia(texto)) });
    } catch (err) {
      setAlta({ paso: "error", texto, mensaje: err.message });
    }
  };

  const confirmarAlta = async () => {
    setAlta((a) => ({ ...a, paso: "creando" }));
    try {
      const nueva = await crear.crear(alta.texto);
      setCreada(nueva);
      elegir(nueva);
    } catch (err) {
      setAlta((a) => ({ ...a, paso: "error", mensaje: err.message }));
    }
  };

  const hayExacta = opciones.some((o) => norm(o[campoTexto]) === norm(consulta));
  const ofrecerAlta = crear && !cargando && norm(consulta) && !hayExacta;
  const explicarSinAlta = !crear && avisoSinAlta && !cargando && norm(consulta) && !hayExacta;

  // Debounce: no dispara una consulta por cada tecla.
  useEffect(() => {
    if (!abierto) return;
    const t = setTimeout(async () => {
      setCargando(true);
      try {
        setOpciones(await pedir(`${endpoint}?q=${encodeURIComponent(consulta)}`));
      } catch {
        setOpciones([]);
      } finally {
        setCargando(false);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [consulta, abierto, endpoint]);

  // Cerrar al hacer clic afuera
  useEffect(() => {
    const fuera = (e) => {
      if (contenedor.current && !contenedor.current.contains(e.target)) setAbierto(false);
    };
    document.addEventListener("mousedown", fuera);
    return () => document.removeEventListener("mousedown", fuera);
  }, []);

  const seleccionado = valor ? opciones.find((o) => String(o[campoValor]) === String(valor)) : null;

  return (
    <div className="space-y-1" ref={contenedor}>
      <label className="text-xs font-semibold text-slate-500 uppercase tracking-wide">{etiqueta}</label>

      {valor ? (
        <div className="w-full flex items-center justify-between gap-3 border border-blue-200 bg-blue-50/50 rounded-xl px-3 py-2.5 text-sm shadow-sm">
          <div className="flex items-center gap-2 min-w-0">
            <CheckCircle2 size={15} className="text-blue-600 shrink-0" />
            <span className="font-medium text-slate-700 truncate">
              {seleccionado ? seleccionado[campoTexto] : valor}
            </span>
            {seleccionado && (
              <span className="font-mono text-xs text-slate-400 shrink-0">{seleccionado[campoValor]}</span>
            )}
          </div>
          <button type="button" onClick={() => { onChange(null); setCreada(null); }}
                  aria-label="Quitar selección" title="Quitar selección"
                  className="p-1 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-white transition-colors shrink-0">
            <X size={15} />
          </button>
        </div>
      ) : (
        <>
          <div className="relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
            <input
              type="text"
              className={INPUT_BUSCAR}
              value={consulta}
              placeholder={placeholder}
              onFocus={() => setAbierto(true)}
              onChange={(e) => {
                setConsulta(e.target.value);
                setAbierto(true);
                setAlta(null);
                if (permitirNuevo) onTextoNuevo(e.target.value);
              }}
            />
            {abierto && (
              <ul className="absolute z-30 left-0 right-0 top-full mt-1.5 max-h-72 overflow-y-auto bg-white rounded-xl shadow-lg border border-slate-100 py-1">
                {cargando && (
                  <li className="flex items-center gap-2 px-3 py-2.5 text-sm text-slate-400">
                    <Loader2 size={14} className="animate-spin text-blue-600" /> Buscando…
                  </li>
                )}
                {!cargando && opciones.length === 0 && (
                  <li className="px-3 py-2.5 text-sm text-slate-400">
                    {permitirNuevo
                      ? "Sin resultados — se registrará como nuevo"
                      : "Sin resultados en el catálogo de Siesa"}
                  </li>
                )}
                {opciones.map((o) => (
                  <li key={o[campoValor]}>
                    <button type="button" onClick={() => elegir(o)}
                            className="w-full flex items-center justify-between gap-3 px-3 py-2 text-left hover:bg-blue-50/60 transition-colors">
                      <span className="text-sm font-medium text-slate-700 truncate">{o[campoTexto]}</span>
                      <span className="font-mono text-xs text-slate-400 shrink-0">{o[campoValor]}</span>
                    </button>
                  </li>
                ))}
                {ofrecerAlta && (
                  <li className="border-t border-slate-100 mt-1 pt-1">
                    <button type="button" onClick={pedirAlta}
                            className="w-full flex items-center justify-between gap-3 px-3 py-2 text-left hover:bg-blue-50/60 transition-colors">
                      <span className="flex items-center gap-2 text-sm font-semibold text-blue-700 min-w-0">
                        <Plus size={15} className="shrink-0" />
                        <span className="truncate">Crear “{consulta.trim().toUpperCase()}” en Siesa</span>
                      </span>
                      <span className="text-xs text-slate-400 shrink-0">siguiente consecutivo</span>
                    </button>
                  </li>
                )}
                {explicarSinAlta && (
                  <li className="border-t border-slate-100 mt-1 pt-1">
                    <p className="flex items-start gap-2 px-3 py-2 text-xs text-slate-500">
                      <Lock size={14} className="shrink-0 mt-0.5 text-slate-400" />
                      <span>{avisoSinAlta}</span>
                    </p>
                  </li>
                )}
              </ul>
            )}
          </div>

          {alta && (
            <div className="pt-1">
              {alta.paso === "revisando" && (
                <Aviso tono="info">
                  <span className="flex items-center gap-2">
                    <Loader2 size={15} className="animate-spin shrink-0" /> Consultando el consecutivo en Siesa…
                  </span>
                </Aviso>
              )}

              {alta.paso === "confirmar" && alta.existentes?.length > 0 && (
                <Aviso tono="alerta" icon={AlertTriangle}>
                  <p>Ya existe en Siesa con ese nombre. Selecciónala en vez de crear otra:</p>
                  <div className="flex flex-wrap gap-2 mt-2">
                    {alta.existentes.map((o) => (
                      <button type="button" key={o.id} className={BTN_SECUNDARIO_CHICO} onClick={() => elegir(o)}>
                        <span className="font-mono">{o.id}</span> · {o.descripcion}
                      </button>
                    ))}
                    <button type="button" className={BTN_SECUNDARIO_CHICO} onClick={() => setAlta(null)}>Cancelar</button>
                  </div>
                </Aviso>
              )}

              {(alta.paso === "confirmar" || alta.paso === "creando") && !alta.existentes?.length && (
                <Aviso tono="info" icon={Info}>
                  <p>
                    Se creará en Siesa la marca <strong>{alta.descripcion}</strong> con el código{" "}
                    <strong className="font-mono">{alta.id_propuesto}</strong>. Queda disponible para todos y no se puede
                    borrar desde la plataforma.
                  </p>
                  <div className="flex flex-wrap gap-2 mt-2">
                    <button type="button" className={BTN_PRIMARIO_CHICO} onClick={confirmarAlta}
                            disabled={alta.paso === "creando"}>
                      {alta.paso === "creando"
                        ? <><Loader2 size={14} className="animate-spin" /> Creando en Siesa…</>
                        : <><Plus size={14} /> Crear marca</>}
                    </button>
                    <button type="button" className={BTN_SECUNDARIO_CHICO} onClick={() => setAlta(null)}
                            disabled={alta.paso === "creando"}>
                      Cancelar
                    </button>
                  </div>
                </Aviso>
              )}

              {alta.paso === "error" && (
                <Aviso tono="error" icon={XCircle}>
                  <p>No se creó: {alta.mensaje}</p>
                  <div className="flex flex-wrap gap-2 mt-2">
                    <button type="button" className={BTN_SECUNDARIO_CHICO} onClick={pedirAlta}>Reintentar</button>
                    <button type="button" className={BTN_SECUNDARIO_CHICO} onClick={() => setAlta(null)}>Cerrar</button>
                  </div>
                </Aviso>
              )}
            </div>
          )}
        </>
      )}

      {valor && creada && String(creada[campoValor]) === String(valor) && (
        <p className="flex items-center gap-1.5 text-xs text-emerald-600">
          <CheckCircle2 size={14} />
          Creada en Siesa ahora mismo con el código <span className="font-mono font-semibold">{creada[campoValor]}</span>.
        </p>
      )}

      {/* Solo avisar cuando de verdad NO hay coincidencias. Antes se mostraba
          apenas el usuario escribia, aunque el catalogo si tuviera resultados. */}
      {permitirNuevo && !valor && textoNuevo && !cargando && opciones.length === 0 && (
        <p className="flex items-center gap-1.5 text-xs text-amber-700">
          <AlertTriangle size={14} className="shrink-0" />
          "{textoNuevo}" no está en Siesa. Se guardará como pendiente de crear.
        </p>
      )}
    </div>
  );
}
