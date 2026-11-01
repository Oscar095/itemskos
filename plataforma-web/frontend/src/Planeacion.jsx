import { useCallback, useEffect, useRef, useState } from "react";
import {
  PackageCheck, ListChecks, History, AlertTriangle, AlertCircle, CheckCircle2, XCircle,
  Upload, ArrowLeft, Warehouse, Filter, ExternalLink, Circle,
} from "lucide-react";
import { pedir } from "./api";
import { usePermiso } from "./store/auth";
import {
  Aviso, BTN_PRIMARIO, BTN_SECUNDARIO, CARD, HeroTabs, Loading, Modal,
  PageBody, PageHero, Pill, TH, Vacio, fechaHora,
} from "./components/ui";

const fecha = (f) => fechaHora(f);
const sol = (id) => `SOL-${String(id).padStart(5, "0")}`;

// Version compacta de INPUT / SELECT para editar dentro de la tabla.
const CELDA =
  "border border-slate-200 rounded-lg px-2 py-1.5 text-xs text-slate-700 placeholder-slate-400 bg-white shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-slate-50 disabled:text-slate-400 disabled:cursor-not-allowed";
const CHECK = "w-4 h-4 accent-blue-600 cursor-pointer disabled:cursor-not-allowed disabled:opacity-40";
const TD = "px-4 py-3 align-top";

/**
 * Pantalla del planeador. Las solicitudes llegan aqui al aprobarse el diseno;
 * el planeador confirma ruta y bodega de asignacion y lanza el cargue, que
 * crea el item y le asocia sus parametros de planeacion en Siesa. El cargue
 * queda a nombre del usuario de la sesion (lo pone el backend).
 */
export default function Planeacion() {
  const [pestana, setPestana] = useState("listos");
  const [cargueAbierto, setCargueAbierto] = useState(null);
  const [nListos, setNListos] = useState(null);

  const verCargue = (id) => { setCargueAbierto(id); setPestana("historial"); };
  const cambiarPestana = (k) => {
    setPestana(k);
    if (k === "historial") setCargueAbierto(null);
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <PageHero
        icon={PackageCheck} eyebrow="Planeación" title="Creación de items en Siesa"
        subtitle="Confirma ruta y bodega de asignación y carga los items autorizados por Diseño"
      >
        <HeroTabs
          value={pestana} onChange={cambiarPestana}
          tabs={[
            { key: "listos", label: `Items listos a crear${nListos != null ? ` (${nListos})` : ""}`, icon: <ListChecks size={14} /> },
            { key: "historial", label: "Historial de cargues", icon: <History size={14} /> },
          ]}
        />
      </PageHero>

      <PageBody>
        {pestana === "listos"
          ? <Listos alContar={setNListos} alTerminar={verCargue} />
          : <Historial abierto={cargueAbierto} alAbrir={setCargueAbierto} />}
      </PageBody>
    </div>
  );
}

function Listos({ alContar, alTerminar }) {
  const permiso = usePermiso("planeacion");
  const [filas, setFilas] = useState([]);
  const [opciones, setOpciones] = useState({ rutas: [], bodegas: [] });
  const [errorRutas, setErrorRutas] = useState("");
  const [sel, setSel] = useState(new Set());
  const [cargando, setCargando] = useState(true);
  const [confirmar, setConfirmar] = useState(false);
  const [envio, setEnvio] = useState(null);   // {cargue, error, cargueId, enviando}
  const filasRef = useRef(filas);
  filasRef.current = filas;
  const vivo = useRef(true);   // el seguimiento del cargue se corta si se sale de la pantalla
  // Se vuelve a poner en true al montar: StrictMode desmonta y monta en desarrollo.
  useEffect(() => { vivo.current = true; return () => { vivo.current = false; }; }, []);

  const cargar = useCallback(() => {
    setCargando(true);
    pedir("/api/planeacion/listos")
      .then((f) => {
        setFilas(f);
        alContar(f.length);
        // Lo que ya no esta (o entro a otro cargue) sale de la seleccion.
        const libres = new Set(f.filter((x) => !x.en_cargue).map((x) => x.id));
        setSel((s) => new Set([...s].filter((id) => libres.has(id))));
      })
      .catch(() => {})
      .finally(() => setCargando(false));
  }, [alContar]);

  useEffect(() => {
    cargar();
    pedir("/api/planeacion/opciones").then(setOpciones).catch((e) => setErrorRutas(e.message));
  }, [cargar]);

  const cambiar = (id, campo, valor, guardar = true) => {
    // Se lee y escribe el ref, no `filas`: al aplicar la bodega a varios
    // seleccionados cada llamada debe ver lo que dejo la anterior.
    const f = filasRef.current.find((x) => x.id === id);
    if (!f) return;
    // El codigo es del item base: vale para todas las filas de esa referencia.
    const afecta = (x) => x.id === id || (campo === "item_codigo" && x.referencia === f.referencia);
    filasRef.current = filasRef.current.map((x) => (afecta(x) ? { ...x, [campo]: valor } : x));
    setFilas(filasRef.current);
    if (!guardar) return;
    const cuerpo = { ruta_id: f.ruta_id, bodega_asignacion: f.bodega_asignacion, [campo]: valor || null };
    pedir(`/api/planeacion/listos/${id}`, { method: "PATCH", json: cuerpo })
      .catch((e) => setEnvio({ error: `No se guardó el cambio de ${sol(id)}: ${e.message}` }));
  };

  const bodegaEnSeleccion = (b) => {
    for (const id of sel) cambiar(id, "bodega_asignacion", b);
  };

  const completa = (f) => f.ruta_id && f.bodega_asignacion && f.item_codigo && !f.en_cargue;
  const elegibles = filas.filter((f) => !f.en_cargue);
  const seleccion = filas.filter((f) => sel.has(f.id));
  const incompletas = seleccion.filter((f) => !completa(f));
  const puedeLanzar = seleccion.length > 0 && incompletas.length === 0;

  const alternar = (id) => setSel((s) => {
    const n = new Set(s);
    n.has(id) ? n.delete(id) : n.add(id);
    return n;
  });
  const todas = elegibles.length > 0 && elegibles.every((f) => sel.has(f.id));

  const lanzar = async () => {
    setEnvio({ enviando: true });
    let id;
    try {
      ({ id } = await pedir("/api/planeacion/cargues", {
        method: "POST",
        json: {
          items: seleccion.map((f) => ({
            solicitud_id: f.id, ruta_id: f.ruta_id, bodega: f.bodega_asignacion,
            item_codigo: f.item_codigo ? Number(f.item_codigo) : null,
          })),
        },
      }));
    } catch (e) {
      setEnvio({ error: `No se inició el cargue: ${e.message}` });
      cargar();
      return;
    }
    setConfirmar(false);
    setSel(new Set());
    // El cargue corre en el servidor; aqui solo se sigue su avance. Un fallo de
    // red al consultar no significa que el cargue fallo: se reintenta y, si
    // persiste, se manda al historial en vez de decir "no se inicio".
    let fallos = 0;
    while (vivo.current) {
      try {
        const d = await pedir(`/api/planeacion/cargues/${id}`);
        fallos = 0;
        if (!vivo.current) return;
        setEnvio({ enviando: true, cargue: d.cargue, filas: d.filas });
        if (d.cargue.estado !== "En proceso") break;
      } catch {
        if (++fallos >= 5) {
          setEnvio({ cargueId: id, error: `Se perdió el seguimiento del cargue #${id}; sigue corriendo en el servidor.` });
          cargar();
          return;
        }
      }
      await new Promise((r) => setTimeout(r, 1500));
    }
    if (!vivo.current) return;
    cargar();
    setEnvio(null);
    alTerminar(id);
  };

  if (envio?.enviando) {
    const hechas = (envio.filas || []).filter((f) => f.estado !== "En cola").length;
    const total = envio.cargue?.total || seleccion.length;
    const pct = total ? (hechas / total) * 100 : 0;
    return (
      <div className={`${CARD} p-6 space-y-4`}>
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-xl bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center shrink-0 shadow-sm">
            <Upload size={20} className="text-white" />
          </div>
          <div className="min-w-0">
            <h2 className="font-semibold text-slate-800">
              {envio.cargue ? `Cargue #${envio.cargue.id} en proceso…` : "Iniciando cargue…"}
            </h2>
            <p className="text-xs text-slate-400">
              <span className="font-mono font-semibold text-slate-600">{hechas}</span> de{" "}
              <span className="font-mono font-semibold text-slate-600">{total}</span> items procesados
            </p>
          </div>
          <span className="ml-auto font-mono text-sm font-semibold text-blue-700">{Math.round(pct)}%</span>
        </div>
        <div className="h-2 rounded-full bg-slate-100 overflow-hidden">
          <div className="h-full rounded-full bg-gradient-to-r from-blue-500 to-blue-400 transition-all duration-500"
               style={{ width: `${pct}%` }} />
        </div>
        <p className="text-xs text-slate-500">
          Cada item se crea en Siesa y luego se le asocian sus parámetros de planeación; no cierres esta
          ventana si quieres ver el resumen al terminar (el cargue sigue igual si la cierras).
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Barra de acciones en tarjeta: es lo primero y queda montada sobre el hero oscuro (-mt-5). */}
      <div className={`${CARD} p-4 space-y-3`}>
        <div className="flex items-center gap-3 flex-wrap">
          <p className="text-sm text-slate-500">
            {cargando ? "Cargando…" : (
              <>
                <span className="font-semibold text-slate-700">{filas.length}</span> autorizados por Diseño ·{" "}
                <span className="font-semibold text-slate-700">{opciones.rutas.length}</span> rutas activas en Siesa
              </>
            )}
          </p>
          {sel.size > 0 && (
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="flex items-center gap-1.5 text-xs text-slate-500">
                <Warehouse size={14} className="text-slate-400" />
                Bodega para los <span className="font-semibold text-slate-700">{sel.size}</span> seleccionados:
              </span>
              {opciones.bodegas.map((b) => (
                <button key={b} type="button" disabled={!permiso.editar} onClick={() => bodegaEnSeleccion(b)}
                        className="px-2.5 py-1 text-xs font-mono font-semibold border border-slate-200 rounded-lg bg-white text-slate-600 hover:bg-blue-50 hover:text-blue-700 hover:border-blue-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-white disabled:hover:text-slate-600 disabled:hover:border-slate-200">
                  {b}
                </button>
              ))}
            </div>
          )}
          {permiso.crear && (
            <button className={`${BTN_PRIMARIO} ml-auto`} disabled={!puedeLanzar} onClick={() => setConfirmar(true)}>
              <Upload size={15} /> Confirmar y cargar (<span className="font-mono">{seleccion.length}</span>)
            </button>
          )}
        </div>

        {errorRutas && (
          <Aviso tono="error" icon={AlertCircle}>No se pudieron traer las rutas de Siesa: {errorRutas}</Aviso>
        )}
        {envio?.error && !confirmar && <ErrorEnvio envio={envio} alTerminar={alTerminar} />}
        {seleccion.length > 0 && incompletas.length > 0 && (
          <Aviso tono="alerta" icon={AlertTriangle}>
            {incompletas.length} seleccionado(s) sin ruta, bodega o código de item. Complétalos para cargar.
          </Aviso>
        )}
      </div>

      {filas.length === 0 ? (
        cargando ? <Loading label="Cargando items..." /> : (
          <Vacio icon={PackageCheck} titulo="No hay items autorizados pendientes."
                 sub="Llegan aquí cuando Diseño registra “Aprobación de Diseño”." />
        )
      ) : (
        <div className={`${CARD} overflow-hidden`}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50">
                  <th className="pl-5 pr-2 py-3.5 w-8">
                    <input type="checkbox" className={CHECK} checked={todas} aria-label="Seleccionar todos"
                           onChange={() => setSel(todas ? new Set() : new Set(elegibles.map((f) => f.id)))} />
                  </th>
                  <th className={TH}>ID</th>
                  <th className={TH}>Item base</th>
                  <th className={TH}>Marca</th>
                  <th className={TH}>Calibre</th>
                  <th className={`${TH} !text-right`}>Cantidad</th>
                  <th className={TH}>Código item</th>
                  <th className={TH}>Ruta</th>
                  <th className={TH}>Bodega asig.</th>
                  <th className={TH}>Estado</th>
                </tr>
              </thead>
              <tbody>
                {filas.map((f, idx) => (
                  <tr key={f.id}
                      className={`border-b border-slate-100 last:border-0 transition-colors hover:bg-blue-50/40
                        ${sel.has(f.id) ? "bg-blue-50/70" : idx % 2 === 0 ? "bg-white" : "bg-slate-50/60"}`}>
                    <td className="pl-5 pr-2 py-3 align-top">
                      <input type="checkbox" className={`${CHECK} mt-1`} checked={sel.has(f.id)} disabled={!!f.en_cargue}
                             onChange={() => alternar(f.id)} aria-label={`Seleccionar ${sol(f.id)}`} />
                    </td>
                    <td className={`${TD} font-mono text-xs text-slate-500`}>{f.id}</td>
                    <td className={TD}>
                      <p className="font-medium text-slate-800">{f.item_base}</p>
                      <p className="text-xs text-slate-400 font-mono">{f.referencia}</p>
                    </td>
                    <td className={TD}>
                      <p className="text-slate-700">{f.marca}</p>
                      <p className="text-xs text-slate-400 font-mono">{f.marca_id}</p>
                    </td>
                    <td className={`${TD} font-mono text-xs text-slate-600`}>{f.calibre_id}</td>
                    <td className={`${TD} font-mono text-right text-slate-700 font-medium`}>{f.cantidad?.toLocaleString("es-CO")}</td>
                    <td className={TD}>
                      <input type="text" inputMode="numeric" maxLength={7} disabled={!permiso.editar}
                             className={`${CELDA} w-24 font-mono`}
                             value={f.item_codigo ?? ""} placeholder="f120_id"
                             onChange={(e) => cambiar(f.id, "item_codigo", e.target.value.replace(/\D/g, ""), false)}
                             onBlur={(e) => e.target.value && cambiar(f.id, "item_codigo", e.target.value)} />
                    </td>
                    <td className={TD}>
                      <select className={`${CELDA} min-w-[11rem] max-w-[16rem]`} value={f.ruta_id || ""} disabled={!permiso.editar}
                              onChange={(e) => cambiar(f.id, "ruta_id", e.target.value)}>
                        <option value="">Elegir ruta…</option>
                        {opciones.rutas.map((r) => <option key={r.id} value={r.id}>{r.descripcion || r.id}</option>)}
                      </select>
                    </td>
                    <td className={TD}>
                      <select className={`${CELDA} w-24 font-mono`} value={f.bodega_asignacion || ""} disabled={!permiso.editar}
                              onChange={(e) => cambiar(f.id, "bodega_asignacion", e.target.value)}>
                        <option value="">—</option>
                        {opciones.bodegas.map((b) => <option key={b} value={b}>{b}</option>)}
                      </select>
                    </td>
                    <td className={TD}><EstadoListo f={f} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {confirmar && permiso.crear && (
        <Modal title="Confirmar cargue en Siesa" onClose={() => setConfirmar(false)} ancho="max-w-2xl">
          <div className="space-y-4">
            <Aviso tono="alerta" icon={AlertTriangle}>
              Se van a crear <strong>{seleccion.length}</strong> item(s) en Siesa y asociarles sus parámetros de
              planeación. Esto escribe en Siesa (producción).
            </Aviso>
            {envio?.error && <ErrorEnvio envio={envio} alTerminar={alTerminar} />}
            <ul className="rounded-xl border border-slate-100 divide-y divide-slate-100 max-h-[45vh] overflow-y-auto">
              {seleccion.map((f, i) => (
                <li key={f.id} className={`px-4 py-2.5 text-sm ${i % 2 === 0 ? "bg-white" : "bg-slate-50/60"}`}>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-mono text-xs font-semibold text-blue-700">{sol(f.id)}</span>
                    <span className="text-slate-700 font-medium">{f.item_base}</span>
                    <span className="text-xs text-slate-400">· {f.marca} · <span className="font-mono">{f.calibre_id}</span></span>
                  </div>
                  <p className="text-xs text-slate-500 mt-0.5">
                    ruta <span className="font-mono font-semibold text-slate-700">{f.ruta_id}</span>, bodega{" "}
                    <span className="font-mono font-semibold text-slate-700">{f.bodega_asignacion}</span>
                  </p>
                </li>
              ))}
            </ul>
            <div className="flex items-center justify-end gap-2">
              <button className={BTN_SECUNDARIO} onClick={() => setConfirmar(false)}>Cancelar</button>
              <button className={BTN_PRIMARIO} onClick={lanzar} disabled={!puedeLanzar}>
                <Upload size={15} /> Sí, cargar en Siesa
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

function ErrorEnvio({ envio, alTerminar }) {
  return (
    <Aviso tono="error" icon={AlertCircle}>
      <span>{envio.error}</span>
      {envio.cargueId && (
        <button type="button" onClick={() => alTerminar(envio.cargueId)}
                className="ml-2 inline-flex items-center gap-1 font-semibold underline underline-offset-2 hover:text-rose-900">
          <ExternalLink size={13} /> Ver cargue #{envio.cargueId}
        </button>
      )}
    </Aviso>
  );
}

function EstadoListo({ f }) {
  if (f.en_cargue) return <Pill>En cargue</Pill>;
  if (f.estado === "Creado") {
    return (
      <div className="space-y-1">
        <Pill>Faltan parámetros</Pill>
        {f.planeacion_mensaje && <p className="text-xs text-slate-400 max-w-[260px]">{f.planeacion_mensaje}</p>}
      </div>
    );
  }
  if (f.estado === "Bloqueado") {
    return (
      <div className="space-y-1">
        <Pill>Con error</Pill>
        {f.motivo_bloqueo && <p className="text-xs text-slate-400 max-w-[260px]">{f.motivo_bloqueo}</p>}
      </div>
    );
  }
  return <Pill>Por crear</Pill>;
}

function Historial({ abierto, alAbrir }) {
  const [cargues, setCargues] = useState([]);
  const [detalle, setDetalle] = useState(null);
  const [soloErrores, setSoloErrores] = useState(false);

  useEffect(() => {
    pedir("/api/planeacion/cargues").then(setCargues).catch(() => {});
  }, [abierto]);

  useEffect(() => {
    setDetalle(null);
    if (!abierto) return;
    let vigente = true, reloj;
    const traer = () => pedir(`/api/planeacion/cargues/${abierto}`).then((d) => {
      if (!vigente) return;
      setDetalle(d);
      if (d.cargue.estado === "En proceso") reloj = setTimeout(traer, 2000);
    }).catch(() => {});
    traer();
    return () => { vigente = false; clearTimeout(reloj); };
  }, [abierto]);

  if (abierto && detalle) {
    const c = detalle.cargue;
    const filas = soloErrores ? detalle.filas.filter((f) => f.estado !== "Exitoso") : detalle.filas;
    return (
      <div className="space-y-6">
        {/* En tarjeta: este bloque queda montado sobre el hero oscuro (-mt-5). */}
        <div className={`${CARD} p-4 flex items-center gap-3 flex-wrap`}>
          <button className={BTN_SECUNDARIO} onClick={() => alAbrir(null)}>
            <ArrowLeft size={15} /> Todos los cargues
          </button>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="font-semibold text-slate-800">Cargue <span className="font-mono">#{c.id}</span></h2>
              <Pill>{c.estado}</Pill>
              {c.estado === "En proceso" && <span className="text-xs text-slate-400">se actualiza solo</span>}
            </div>
            <p className="text-xs text-slate-400">{fecha(c.fecha)} · {c.usuario || "—"}</p>
          </div>
          <div className="ml-auto flex items-center gap-x-5 gap-y-2 flex-wrap">
            <p className="text-sm text-slate-500">
              <span className="font-semibold text-slate-700">{c.total}</span> items ·{" "}
              <span className={`font-semibold ${c.exitosos > 0 ? "text-emerald-700" : "text-slate-700"}`}>{c.exitosos}</span> exitosos ·{" "}
              <span className={`font-semibold ${c.con_error > 0 ? "text-rose-700" : "text-slate-700"}`}>{c.con_error}</span> con error
            </p>
            <label className="flex items-center gap-2 text-sm text-slate-600 cursor-pointer select-none">
              <input type="checkbox" className={CHECK} checked={soloErrores} onChange={(e) => setSoloErrores(e.target.checked)} />
              <Filter size={14} className="text-slate-400" /> Solo con error
            </label>
          </div>
        </div>

        {filas.length === 0 ? (
          <Vacio icon={CheckCircle2} titulo={soloErrores ? "Ningún item con error en este cargue." : "Este cargue no tiene items."} />
        ) : (
          <div className={`${CARD} overflow-hidden`}>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 bg-slate-50">
                    <th className={TH}>Solicitud</th>
                    <th className={TH}>Item</th>
                    <th className={TH}>Ruta / bodega</th>
                    <th className={TH}>Resultado</th>
                    <th className={TH}>1 · Creación del item</th>
                    <th className={TH}>2 · Parámetros de planeación</th>
                  </tr>
                </thead>
                <tbody>
                  {filas.map((f, idx) => (
                    <tr key={f.id} className={`border-b border-slate-100 last:border-0 ${idx % 2 === 0 ? "bg-white" : "bg-slate-50/60"} hover:bg-blue-50/40 transition-colors`}>
                      <td className={`${TD} font-mono text-xs font-semibold text-blue-700 whitespace-nowrap`}>{sol(f.solicitud_id)}</td>
                      <td className={TD}>
                        <p className="font-medium text-slate-800">{f.item_base}</p>
                        <p className="text-xs text-slate-400">
                          <span className="font-mono">{f.referencia}</span> · cód.{" "}
                          <span className="font-mono">{f.item_codigo ?? "—"}</span> · {f.marca_id} {f.marca} ·{" "}
                          <span className="font-mono">{f.calibre_id}</span>
                        </p>
                      </td>
                      <td className={TD}>
                        <p className="font-mono text-xs text-slate-700">{f.ruta_id}</p>
                        <p className="text-xs text-slate-400">bodega <span className="font-mono">{f.bodega}</span></p>
                      </td>
                      <td className={TD}><Pill>{f.estado}</Pill></td>
                      <td className={`${TD} max-w-[320px]`}><Paso ok={f.item_ok} msg={f.item_mensaje} /></td>
                      <td className={`${TD} max-w-[320px]`}>
                        <Paso ok={f.param_ok} msg={f.param_mensaje ?? (f.item_ok === false ? "No se envió: el item no se creó." : null)} />
                        {f.param_ok === false && f.param_http != null && (
                          <p className="text-xs text-slate-400 font-mono mt-1">HTTP {f.param_http} · código {f.param_codigo ?? "—"}</p>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* En tarjeta: texto suelto aqui quedaria oscuro sobre el hero (-mt-5). */}
      <div className={`${CARD} p-4`}>
        <p className="text-sm text-slate-500">
          <span className="font-semibold text-slate-700">{cargues.length}</span> cargues
        </p>
      </div>
      {cargues.length === 0 ? (
        <Vacio icon={History} titulo="Aún no hay cargues." sub="Aparecen aquí al confirmar un cargue desde “Items listos a crear”." />
      ) : (
        <div className={`${CARD} overflow-hidden`}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50">
                  <th className={TH}>#</th>
                  <th className={TH}>Fecha</th>
                  <th className={TH}>Planeador</th>
                  <th className={`${TH} !text-right`}>Items</th>
                  <th className={`${TH} !text-right`}>Exitosos</th>
                  <th className={`${TH} !text-right`}>Con error</th>
                  <th className={TH}>Estado</th>
                </tr>
              </thead>
              <tbody>
                {cargues.map((c, idx) => {
                  const estado = c.estado === "En proceso" ? "En proceso" : c.con_error ? "Revisar" : "Completo";
                  return (
                    <tr key={c.id} onClick={() => alAbrir(c.id)}
                        className={`border-b border-slate-100 last:border-0 cursor-pointer ${idx % 2 === 0 ? "bg-white" : "bg-slate-50/60"} hover:bg-blue-50/40 transition-colors`}>
                      <td className="px-5 py-3 font-mono text-xs font-semibold text-blue-700">{c.id}</td>
                      <td className="px-5 py-3 text-xs text-slate-500 font-mono whitespace-nowrap">{fecha(c.fecha)}</td>
                      <td className="px-5 py-3 text-slate-700">{c.usuario || <span className="text-slate-300">—</span>}</td>
                      <td className="px-5 py-3 font-mono text-right text-slate-700 font-medium">{c.total}</td>
                      <td className="px-5 py-3 font-mono text-right text-emerald-600 font-semibold">{c.exitosos}</td>
                      <td className={`px-5 py-3 font-mono text-right font-semibold ${c.con_error ? "text-rose-600" : "text-slate-400"}`}>{c.con_error}</td>
                      <td className="px-5 py-3"><Pill>{estado}</Pill></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function Paso({ ok, msg }) {
  if (ok == null && !msg) return <span className="text-slate-300">—</span>;
  return (
    <div className="flex items-start gap-1.5 text-xs text-slate-600">
      {ok
        ? <CheckCircle2 size={15} className="text-emerald-500 shrink-0 mt-px" />
        : ok === false
          ? <XCircle size={15} className="text-rose-500 shrink-0 mt-px" />
          : <Circle size={15} className="text-slate-300 shrink-0 mt-px" />}
      <span className="min-w-0 break-words">{msg}</span>
    </div>
  );
}
