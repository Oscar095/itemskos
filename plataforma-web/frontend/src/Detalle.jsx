import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import {
  AlertTriangle, CheckCircle2, FileText, Info, Mail, MessageSquare, Paperclip, Pencil, Route, Send,
  Trash2, Upload, X, XCircle,
} from "lucide-react";
import Comentarios from "./Comentarios.jsx";
import EditarSolicitud from "./EditarSolicitud.jsx";
import { pedir } from "./api";
import { useAuthStore } from "./store/auth";
import {
  Aviso, BTN_PRIMARIO, BTN_SECUNDARIO, INPUT, Loading, Modal, Pill, SELECT, fechaHora,
} from "./components/ui.jsx";

/** Tamaño legible: un archivo de 37 bytes no debe mostrarse como "0 KB". */
function tamano(bytes) {
  const b = bytes || 0;
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1024 / 1024).toFixed(1)} MB`;
}

// Quien registra cada etapa: modulo cuyo permiso "editar" la habilita.
// 7-10 (En Diseño ... Ajuste Arte) van entre la 1 y la 2: el orden es `orden`, no el id.
const MODULO_ETAPA = {
  1: "diseno", 2: "diseno", 3: "planeacion", 4: "pedidos", 5: "diseno", 6: "planeacion",
  7: "diseno", 8: "diseno", 9: "diseno", 10: "diseno",
};

const SIN_PERMISOS = {};

// Correos de avance (items.notificaciones): a quien iba y en que quedo.
const DESTINO_CORREO = { vendedor: "Vendedor", diseno: "Diseño", planeacion: "Planeación", mencion: "Mención" };
const COLOR_CORREO = {
  Enviado: "text-emerald-600", Pendiente: "text-amber-600", Enviando: "text-amber-600",
  Error: "text-rose-600", Vencido: "text-rose-600", Omitido: "text-slate-400",
};

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
 * Ficha de una solicitud: datos, recorrido por las etapas, comentarios y adjuntos.
 * Panel centrado y ancho (pedido del 2026-11-12: el cajon lateral desperdiciaba
 * la pantalla), en dos columnas: a la izquierda los datos y la conversacion, a
 * la derecha lo operativo (registrar avance, recorrido, adjuntos, correos).
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
  const [editando, setEditando] = useState(false);
  const [eliminar, setEliminar] = useState(null);   // null | {motivo, enviando, error}
  const [avisoEdicion, setAvisoEdicion] = useState("");

  const permisos = useAuthStore((st) => st.user?.permisos ?? SIN_PERMISOS);
  const puedeEtapa = (etapaId) => !!permisos[MODULO_ETAPA[etapaId]]?.editar;
  const puedeSubir = !!(permisos.seguimiento?.editar || permisos.solicitudes?.crear);
  const puedeEditar = !!permisos.solicitudes?.editar;
  const puedeEliminar = !!permisos.solicitudes?.eliminar;

  const cargar = useCallback(() => (
    pedir(`/api/solicitudes/${id}`).then(setDatos).catch(() => {})
  ), [id]);

  useEffect(() => {
    cargar();
    pedir("/api/catalogos/etapas").then(setEtapas).catch(() => {});
  }, [cargar]);

  // Cerrar con Escape, como cualquier panel de herramienta profesional.
  useEffect(() => {
    const esc = (e) => e.key === "Escape" && !eliminar && !editando && alCerrar();
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [alCerrar, eliminar, editando]);

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
  // Hasta donde llego (la etapa mas avanzada, por orden) y donde esta ahora (el
  // ultimo evento): no coinciden si, p. ej., tras "Ajuste Arte" vuelve a "En Aprobación".
  const alcanzada = Math.max(0, ...seguimiento.map((x) => x.orden));
  const actual = seguimiento.length ? seguimiento[seguimiento.length - 1].etapa_id : null;
  const etapasRegistrables = etapas.filter((e) => puedeEtapa(e.id));

  const confirmarEliminar = async () => {
    setEliminar((x) => ({ ...x, enviando: true, error: "" }));
    try {
      const q = eliminar.motivo?.trim() ? `?motivo=${encodeURIComponent(eliminar.motivo.trim())}` : "";
      await pedir(`/api/solicitudes/${id}${q}`, { method: "DELETE" });
      alCambiar?.();
      alCerrar();
    } catch (e) {
      setEliminar((x) => ({ ...x, enviando: false, error: e.message }));
    }
  };

  const comentarios = datos?.comentarios ?? [];
  const nComentarios = comentarios.filter((c) => c.tipo === "comentario").length;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-6">
      <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm" onClick={alCerrar} />
      <section role="dialog" aria-modal="true"
               className="relative w-full max-w-6xl max-h-full bg-white rounded-2xl shadow-2xl flex flex-col border border-slate-100 overflow-hidden">
        <header className="bg-gradient-to-br from-slate-800 via-blue-900 to-blue-800 px-6 py-4 flex items-start justify-between gap-4 shrink-0">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <FileText size={16} className="text-blue-300" />
              <span className="text-blue-300 text-xs font-medium uppercase tracking-widest">Solicitud</span>
            </div>
            <div className="flex items-center gap-3 flex-wrap">
              <h2 className="text-2xl font-bold text-white font-mono">
                {s ? `SOL-${String(s.id).padStart(5, "0")}` : "…"}
              </h2>
              {s && <Pill estado={s.estado}>{s.estado}</Pill>}
              {s?.etapa_actual && <span className="text-blue-200 text-sm">{s.etapa_actual}</span>}
            </div>
            {s && (
              <p className="text-blue-200 text-sm mt-1 truncate">
                {[s.item_base || s.referencia, s.marca, s.cliente].filter(Boolean).join(" · ")}
              </p>
            )}
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            {s && puedeEditar && !editando && (
              <button onClick={() => { setEditando(true); setAvisoEdicion(""); }}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium text-white/90 bg-white/10 hover:bg-white/20 transition-colors">
                <Pencil size={14} /> Editar
              </button>
            )}
            {s && puedeEliminar && (
              <button onClick={() => setEliminar({ motivo: "" })}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium text-rose-100 bg-rose-500/20 hover:bg-rose-500/40 transition-colors">
                <Trash2 size={14} /> Eliminar
              </button>
            )}
            <button onClick={alCerrar} aria-label="Cerrar"
                    className="p-1.5 rounded-lg text-white/70 hover:text-white hover:bg-white/10 transition-colors">
              <X size={18} />
            </button>
          </div>
        </header>

        {!datos ? (
          <div className="flex-1 flex items-center py-16">
            <Loading label="Cargando solicitud..." size="md" fullPanel={false} />
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto">
            <div className="grid grid-cols-1 lg:grid-cols-5 lg:divide-x divide-slate-100">
              {/* ── Izquierda: datos y conversacion ── */}
              <div className="lg:col-span-3 px-6 py-5 space-y-6 min-w-0">
                {editando ? (
                  <section>
                    <Seccion icon={Pencil}>Editar solicitud</Seccion>
                    <EditarSolicitud
                      s={s}
                      alCancelar={() => setEditando(false)}
                      alGuardar={() => {
                        setEditando(false);
                        setAvisoEdicion("Cambios guardados. Quedaron registrados en los comentarios.");
                        cargar(); alCambiar?.();
                      }}
                    />
                  </section>
                ) : (
                  <section className="space-y-3">
                    {avisoEdicion && <Aviso tono="ok" icon={CheckCircle2}>{avisoEdicion}</Aviso>}
                    {/* Lista limpia de tres columnas: sin cajas ni fondos, solo lineas finas entre datos. */}
                    <dl className="grid grid-cols-2 md:grid-cols-3 gap-x-6">
                      <Dato label="Item base" mono={!!s.item_base}>
                        {s.item_base || <span className="text-slate-400">sin resolver</span>}
                      </Dato>
                      <Dato label="Referencia" mono>{s.referencia || "—"}</Dato>
                      <Dato label="Marca">{s.marca}</Dato>
                      <Dato label="Cliente">{s.cliente}</Dato>
                      <Dato label="Calibre" mono>{s.calibre || "—"}</Dato>
                      <Dato label="Material">{s.tipo_material}</Dato>
                      <Dato label="T. Impresión">{s.tipo_impresion || <span className="text-slate-400">—</span>}</Dato>
                      <Dato label="Cantidad" mono>{s.cantidad?.toLocaleString("es-CO")}</Dato>
                      <Dato label="Montaje" mono>
                        {s.montaje ?? <span className="font-sans text-slate-400">lo define el planeador</span>}
                      </Dato>
                      <Dato label="Vendedor">{s.vendedor_nombre}</Dato>
                      <Dato label="Tipo de solicitud">{s.tipo_solicitud || <span className="text-slate-400">—</span>}</Dato>
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
                )}

                <section>
                  <Seccion icon={MessageSquare}>
                    Comentarios {nComentarios > 0 && <span className="font-mono text-slate-400">({nComentarios})</span>}
                  </Seccion>
                  <Comentarios solicitudId={id} comentarios={comentarios}
                               alCambiar={() => { alCambiar?.(); return cargar(); }} />
                </section>
              </div>

              {/* ── Derecha: avance, recorrido, adjuntos y correos ── */}
              <div className="lg:col-span-2 px-6 py-5 space-y-6 min-w-0 bg-slate-50/40">
                {etapasRegistrables.length > 0 && (
                  <section className="rounded-2xl border border-slate-100 bg-white shadow-sm p-4 space-y-3">
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

                <section>
                  <Seccion icon={Route}>Recorrido</Seccion>
                  {/* Todas las etapas siempre visibles: se ve de un vistazo hasta donde llego
                      y que falta, no solo lo ya ocurrido. */}
                  <ol className="relative">
                    {etapas.map((e, i) => {
                      const evs = seguimiento.filter((x) => x.etapa_id === e.id);
                      // Tres estados, no dos. Un item migrado desde SharePoint llego con
                      // UN solo evento (su etapa al migrar), asi que las etapas previas
                      // no tienen registro — pero sí las recorrio. Marcarlas como
                      // pendientes seria mentir; marcarlas igual que las registradas
                      // tambien. Van como "transitadas": recorridas, sin detalle.
                      const estado = evs.length ? "hecha" : e.orden < alcanzada ? "transitada" : "pend";
                      const esUltima = e.id === actual;
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
                            {!evs.length && e.orden < alcanzada && (
                              <p className="text-xs text-slate-400 italic mt-0.5">Sin registro — etapa superada</p>
                            )}
                          </div>
                        </li>
                      );
                    })}
                  </ol>
                </section>

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

                {datos.notificaciones?.length > 0 && (
                  <section className="space-y-3">
                    <Seccion icon={Mail}>Correos</Seccion>
                    <ul className="divide-y divide-slate-100">
                      {datos.notificaciones.map((n) => (
                        <li key={n.id} className="py-2.5 min-w-0">
                          <div className="flex items-baseline justify-between gap-3">
                            <p className="text-sm text-slate-800 truncate" title={n.asunto}>{n.asunto}</p>
                            <span className={`text-xs font-semibold shrink-0 ${COLOR_CORREO[n.estado] || "text-slate-500"}`}>
                              {n.estado}
                            </span>
                          </div>
                          <p className="text-xs text-slate-400 truncate" title={n.para || undefined}>
                            {DESTINO_CORREO[n.destino] || n.destino} · {n.para || "sin destinatario"} · {fechaHora(n.enviado || n.creado)}
                          </p>
                          {n.detalle && n.estado !== "Enviado" && (
                            <p className="text-xs text-slate-500 mt-0.5">{n.detalle}</p>
                          )}
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
              </div>
            </div>
          </div>
        )}
      </section>

      {eliminar && (
        <Modal title={`Eliminar SOL-${String(id).padStart(5, "0")}`} onClose={() => !eliminar.enviando && setEliminar(null)}>
          <div className="space-y-4">
            <Aviso tono="alerta" icon={AlertTriangle}>
              La solicitud sale del Seguimiento y de Planeación, y la combinación se puede volver a pedir.
              Su historial (avances, adjuntos, comentarios y correos) queda guardado.
              {s?.estado === "Creado" && " El item ya está creado en Siesa: eliminar la solicitud no lo borra de allá."}
            </Aviso>
            <label className="block space-y-1">
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Motivo (opcional)</span>
              <input className={INPUT} maxLength={500} value={eliminar.motivo} autoFocus
                     placeholder="Duplicada, la pidieron por error…"
                     onChange={(e) => setEliminar((x) => ({ ...x, motivo: e.target.value }))} />
            </label>
            {eliminar.error && <Aviso tono="error" icon={XCircle}>No se eliminó: {eliminar.error}</Aviso>}
            <div className="flex justify-end gap-2">
              <button className={BTN_SECUNDARIO} onClick={() => setEliminar(null)} disabled={eliminar.enviando}>Cancelar</button>
              <button onClick={confirmarEliminar} disabled={eliminar.enviando}
                      className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-white bg-rose-600 hover:bg-rose-700 shadow-sm disabled:opacity-50 transition-colors">
                <Trash2 size={15} /> {eliminar.enviando ? "Eliminando…" : "Sí, eliminar"}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>,
    document.body,
  );
}
