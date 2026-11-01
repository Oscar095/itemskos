import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle, CheckCircle2, FileText, Info, Paperclip, Route, Send, Upload, X, XCircle,
} from "lucide-react";
import { pedir } from "./api";
import { useAuthStore } from "./store/auth";
import { Aviso, BTN_PRIMARIO, INPUT, Loading, Pill, SELECT, fechaHora } from "./components/ui.jsx";

/** Tamaño legible: un archivo de 37 bytes no debe mostrarse como "0 KB". */
function tamano(bytes) {
  const b = bytes || 0;
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1024 / 1024).toFixed(1)} MB`;
}

// Quien registra cada etapa: modulo cuyo permiso "editar" la habilita.
const MODULO_ETAPA = { 1: "diseno", 2: "diseno", 3: "planeacion", 4: "pedidos", 5: "diseno", 6: "planeacion" };

const SIN_PERMISOS = {};

/** Dato de la ficha, sin caja: etiqueta arriba, valor debajo y una linea fina que lo separa del siguiente. */
function Dato({ label, children, mono, ancho }) {
  return (
    <div className={`border-b border-slate-100 py-2.5 min-w-0 ${ancho ? "col-span-2" : ""}`}>
      <dt className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide">{label}</dt>
      <dd className={`text-sm text-slate-800 mt-0.5 break-words ${mono ? "font-mono" : ""}`}>
        {children}
      </dd>
    </div>
  );
}

function Seccion({ icon: Icon, children }) {
  return (
    <h3 className="flex items-center gap-2 text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
      {Icon && <Icon size={15} className="text-blue-600" />}
      {children}
    </h3>
  );
}

/**
 * Ficha de una solicitud: datos, recorrido por las etapas y adjuntos.
 * Va en cajon lateral, no en modal centrado: en una herramienta de trabajo se
 * consulta un registro sin perder de vista la lista que hay detras.
 */
export default function Detalle({ id, alCerrar, alCambiar }) {
  const [datos, setDatos] = useState(null);
  const [etapas, setEtapas] = useState([]);
  const [nuevaEtapa, setNuevaEtapa] = useState("");
  const [obs, setObs] = useState("");
  const [guardando, setGuardando] = useState(false);
  const [autorizacion, setAutorizacion] = useState(null);   // resultado de aprobar el diseno
  const [errorAdjunto, setErrorAdjunto] = useState("");
  const [subiendo, setSubiendo] = useState(false);

  const permisos = useAuthStore((st) => st.user?.permisos ?? SIN_PERMISOS);
  const puedeEtapa = (etapaId) => !!permisos[MODULO_ETAPA[etapaId]]?.editar;
  const puedeSubir = !!(permisos.seguimiento?.editar || permisos.solicitudes?.crear);

  const cargar = useCallback(() => {
    pedir(`/api/solicitudes/${id}`).then(setDatos).catch(() => {});
  }, [id]);

  useEffect(() => {
    cargar();
    pedir("/api/catalogos/etapas").then(setEtapas).catch(() => {});
  }, [cargar]);

  // Cerrar con Escape, como cualquier panel de herramienta profesional.
  useEffect(() => {
    const esc = (e) => e.key === "Escape" && alCerrar();
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [alCerrar]);

  const avanzar = async () => {
    if (!nuevaEtapa) return;
    setGuardando(true);
    setAutorizacion(null);
    try {
      // pedir() ya revisa r.ok y lanza Error con el `detail` del backend.
      const j = await pedir(`/api/solicitudes/${id}/seguimiento`, {
        method: "POST",
        json: { etapa_id: Number(nuevaEtapa), observacion: obs || null },
      });
      // "Aprobación de Diseño" autoriza la creacion (o dice por que no); el
      // item lo crea despues el cargue del planeador, con sus parametros.
      if (j.autorizacion) setAutorizacion(j.autorizacion);
      setNuevaEtapa(""); setObs("");
      cargar(); alCambiar?.();
    } catch (e) {
      setAutorizacion({ ok: false, mensaje: `No se registró el avance: ${e.message}` });
    } finally {
      setGuardando(false);
    }
  };

  const abrirAdjunto = async (adjuntoId) => {
    try {
      const j = await pedir(`/api/solicitudes/adjuntos/${adjuntoId}/url`);
      window.open(j.url, "_blank", "noopener");
    } catch { /* como antes: si no hay URL no se abre nada */ }
  };

  const subir = async (e) => {
    const archivos = [...e.target.files];
    setErrorAdjunto("");
    setSubiendo(true);
    const fallidos = [];
    for (const f of archivos) {
      const fd = new FormData();
      fd.append("archivo", f);
      try {
        await pedir(`/api/solicitudes/${id}/adjuntos`, { method: "POST", body: fd });
      } catch (err) {
        fallidos.push(`${f.name}: ${err.message}`);
      }
    }
    e.target.value = "";
    setSubiendo(false);
    if (fallidos.length) setErrorAdjunto(`No se pudo subir ${fallidos.join(" · ")}`);
    cargar(); alCambiar?.();
  };

  const s = datos?.solicitud;
  const seguimiento = datos?.seguimiento ?? [];
  const ultima = Math.max(0, ...seguimiento.map((x) => x.etapa_id));
  const etapasRegistrables = etapas.filter((e) => puedeEtapa(e.id));

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm" onClick={alCerrar} />
      <aside className="relative w-full max-w-xl h-full bg-white shadow-2xl flex flex-col border-l border-slate-100">
        <header className="bg-gradient-to-br from-slate-800 via-blue-900 to-blue-800 px-6 py-5 flex items-start justify-between gap-4 shrink-0">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <FileText size={16} className="text-blue-300" />
              <span className="text-blue-300 text-xs font-medium uppercase tracking-widest">Solicitud</span>
            </div>
            <h2 className="text-2xl font-bold text-white font-mono">
              {s ? `SOL-${String(s.id).padStart(5, "0")}` : "…"}
            </h2>
            {s && (
              <p className="text-blue-200 text-sm mt-1 truncate">
                {[s.marca, s.cliente].filter(Boolean).join(" · ")}
              </p>
            )}
          </div>
          <button onClick={alCerrar} aria-label="Cerrar"
                  className="p-1.5 rounded-lg text-white/70 hover:text-white hover:bg-white/10 transition-colors">
            <X size={18} />
          </button>
        </header>

        {!datos ? (
          <div className="flex-1 flex items-center">
            <Loading label="Cargando solicitud..." size="md" fullPanel={false} />
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
            <section className="space-y-3">
              {/* Lista limpia de dos columnas: sin cajas ni fondos, solo lineas finas entre datos. */}
              <dl className="grid grid-cols-2 gap-x-6">
                <Dato label="Item base" mono={!!s.item_base}>
                  {s.item_base || <span className="text-slate-400">sin resolver</span>}
                </Dato>
                <Dato label="Referencia" mono>{s.referencia || "—"}</Dato>
                <Dato label="Marca">{s.marca}</Dato>
                <Dato label="Cliente">{s.cliente}</Dato>
                <Dato label="Calibre" mono>{s.calibre || "—"}</Dato>
                <Dato label="Material">{s.tipo_material}</Dato>
                <Dato label="Cantidad" mono>{s.cantidad?.toLocaleString("es-CO")}</Dato>
                <Dato label="Vendedor">{s.vendedor_nombre}</Dato>
                <Dato label="Estado"><Pill>{s.estado}</Pill></Dato>
                {s.sku_creado && <Dato label="SKU Siesa" mono>{s.sku_creado}</Dato>}
                {s.fecha_autorizacion && (
                  <Dato label="Planeación" ancho>
                    {s.planeacion_estado === "Cargada"
                      ? <>Cargada · ruta <span className="font-mono">{s.ruta_id}</span>, bodega <span className="font-mono">{s.bodega_asignacion}</span></>
                      : s.planeacion_estado === "Error" ? <span className="text-rose-600">Error en parámetros</span>
                      : <span className="text-amber-600">Pendiente del planeador</span>}
                  </Dato>
                )}
              </dl>

              {s.motivo_bloqueo && <Aviso tono="alerta" icon={AlertTriangle}>{s.motivo_bloqueo}</Aviso>}
              {s.observaciones && (
                <dl>
                  <dt className="text-[11px] font-semibold text-slate-400 uppercase tracking-wide">Observaciones</dt>
                  <dd className="text-sm text-slate-800 mt-0.5 whitespace-pre-wrap break-words">{s.observaciones}</dd>
                </dl>
              )}
            </section>

            <section>
              <Seccion icon={Route}>Recorrido</Seccion>
              {/* Las 6 etapas siempre visibles: se ve de un vistazo hasta donde llego
                  y que falta, no solo lo ya ocurrido. */}
              <ol className="relative">
                {etapas.map((e, i) => {
                  const evs = seguimiento.filter((x) => x.etapa_id === e.id);
                  // Tres estados, no dos. Un item migrado desde SharePoint llego con
                  // UN solo evento (su etapa al migrar), asi que las etapas previas
                  // no tienen registro — pero sí las recorrio. Marcarlas como
                  // pendientes seria mentir; marcarlas igual que las registradas
                  // tambien. Van como "transitadas": recorridas, sin detalle.
                  const estado = evs.length ? "hecha" : e.id < ultima ? "transitada" : "pend";
                  const esUltima = e.id === ultima;
                  const punto = {
                    hecha: "bg-emerald-500 border-emerald-500",
                    transitada: "bg-blue-200 border-blue-300",
                    pend: "bg-white border-slate-300",
                  }[estado];
                  const linea = estado === "pend" ? "bg-slate-200" : "bg-emerald-200";
                  return (
                    <li key={e.id} className="relative flex gap-3 pb-4 last:pb-0">
                      {i < etapas.length - 1 && (
                        <span className={`absolute left-[9px] top-5 bottom-0 w-0.5 ${linea}`} aria-hidden />
                      )}
                      <span className={`relative z-10 mt-0.5 w-5 h-5 rounded-full border-2 shrink-0 flex items-center justify-center
                        ${punto} ${esUltima ? "ring-4 ring-emerald-500/20" : ""}`}>
                        {estado === "hecha" && <CheckCircle2 size={12} className="text-white" strokeWidth={3} />}
                      </span>
                      <div className={`flex-1 min-w-0 ${esUltima ? "rounded-xl bg-blue-50/60 border border-blue-100 px-3 py-2 -mt-1.5" : ""}`}>
                        <span className={`text-sm font-semibold ${estado === "pend" ? "text-slate-400" : "text-slate-800"}`}>
                          {e.nombre}
                        </span>
                        {evs.map((ev) => (
                          <div key={ev.id} className="mt-1">
                            {ev.observacion && <p className="text-sm text-slate-600">{ev.observacion}</p>}
                            <p className="text-xs text-slate-400">
                              {ev.usuario_nombre || "—"}
                              {ev.fecha ? ` · ${fechaHora(ev.fecha)}` : ""}
                            </p>
                          </div>
                        ))}
                        {!evs.length && e.id < ultima && (
                          <p className="text-xs text-slate-400 italic mt-0.5">Sin registro — etapa superada</p>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ol>
            </section>

            {etapasRegistrables.length > 0 && (
              <section className="rounded-2xl border border-slate-100 shadow-sm p-4 space-y-3">
                <Seccion icon={Send}>Registrar avance</Seccion>
                <select value={nuevaEtapa} onChange={(e) => setNuevaEtapa(e.target.value)} className={SELECT}>
                  <option value="">Registrar avance…</option>
                  {etapasRegistrables.map((e) => <option key={e.id} value={e.id}>{e.nombre}</option>)}
                </select>
                <div className="flex gap-2">
                  <input type="text" value={obs} placeholder="Observación" className={INPUT}
                         onChange={(e) => setObs(e.target.value)} />
                  <button className={`${BTN_PRIMARIO} shrink-0`} onClick={avanzar} disabled={!nuevaEtapa || guardando}>
                    {guardando ? "Guardando…" : "Registrar"}
                  </button>
                </div>

                {Number(nuevaEtapa) === 2 && !guardando && (
                  <Aviso tono="info" icon={Info}>
                    Al aprobar el diseño la solicitud queda autorizada y pasa a Planeación (“Items listos a
                    crear”): el planeador confirma ruta y bodega y ahí se crea el item en Siesa.
                  </Aviso>
                )}
              </section>
            )}

            {autorizacion && (
              <Aviso tono={autorizacion.ok ? "ok" : "error"} icon={autorizacion.ok ? CheckCircle2 : XCircle}>
                <p className="font-semibold">
                  {!autorizacion.ok ? "No se autorizó"
                    : autorizacion.ya_existia ? "Ya existía en Siesa"
                    : autorizacion.repetida ? "Ya estaba autorizada"
                    : "Autorizado para creación"}
                </p>
                <p className="mt-0.5">{autorizacion.mensaje}</p>
              </Aviso>
            )}

            <section className="space-y-3">
              <Seccion icon={Paperclip}>Adjuntos</Seccion>
              {datos.adjuntos.length === 0 ? (
                <p className="text-sm text-slate-400">Sin adjuntos.</p>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {datos.adjuntos.map((a) => (
                    <li key={a.id}>
                      <button onClick={() => abrirAdjunto(a.id)} title={a.nombre_archivo}
                              className="group w-full flex items-center gap-3 py-2.5 text-left">
                        <Paperclip size={15} className="text-slate-400 shrink-0" />
                        <span className="flex-1 min-w-0 text-sm font-medium text-blue-700 group-hover:text-blue-800 group-hover:underline underline-offset-2 truncate transition-colors">
                          {a.nombre_archivo}
                        </span>
                        <span className="text-xs text-slate-400 font-mono shrink-0">{tamano(a.tamano_bytes)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              {errorAdjunto && <Aviso tono="error" icon={XCircle}>{errorAdjunto}</Aviso>}

              {puedeSubir && (
                <label className={`flex items-center justify-center gap-2 rounded-xl border-2 border-dashed border-slate-200 px-4 py-3 text-sm font-medium text-slate-500 hover:border-blue-300 hover:text-blue-600 hover:bg-blue-50/40 transition-colors cursor-pointer
                  ${subiendo ? "opacity-50 pointer-events-none" : ""}`}>
                  <Upload size={16} />
                  {subiendo ? "Subiendo…" : "Subir archivos"}
                  <input type="file" multiple onChange={subir} className="sr-only" disabled={subiendo} />
                </label>
              )}
            </section>
          </div>
        )}
      </aside>
    </div>
  );
}
