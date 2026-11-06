import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ClipboardList, Search, X, ChevronLeft, ChevronRight, Paperclip, FileSearch,
} from "lucide-react";
import Detalle from "./Detalle.jsx";
import { pedir } from "./api";
import {
  BTN_SECUNDARIO, CARD, Field, INPUT, Loading, PageBody, PageHero, Pill, SELECT, TH, Vacio,
} from "./components/ui";

const FILTROS_VACIOS = {
  estado: "", cliente: "", referencia: "", marca: "", vendedor_id: "", etapa_id: "",
};
const POR_PAGINA = 50;

// Pastillas de estado, como las de Orders.tsx: "" es "Todos" (sin filtro).
const ESTADOS = ["", "Pendiente", "Creado", "Bloqueado"];

export default function Panel({ recargar }) {
  const [filtros, setFiltros] = useState(FILTROS_VACIOS);
  const [filas, setFilas] = useState([]);
  const [total, setTotal] = useState(0);
  const [pagina, setPagina] = useState(1);
  const [vendedores, setVendedores] = useState([]);
  const [etapas, setEtapas] = useState([]);
  // /seguimiento?sol=12 abre esa ficha: es el enlace de los correos de avance.
  const [params, setParams] = useSearchParams();
  const [abierta, setAbierta] = useState(() => Number(params.get("sol")) || null);
  const [cargando, setCargando] = useState(false);

  const cerrarFicha = () => {
    setAbierta(null);
    if (params.has("sol")) {
      const p = new URLSearchParams(params);
      p.delete("sol");
      setParams(p, { replace: true });
    }
  };

  useEffect(() => {
    // Todos, tambien los inactivos: este filtro es para consultar el historial.
    pedir("/api/catalogos/vendedores?incluir_inactivos=true").then(setVendedores).catch(() => {});
    pedir("/api/catalogos/etapas").then(setEtapas).catch(() => {});
  }, []);

  const cargar = useCallback(async () => {
    setCargando(true);
    const p = new URLSearchParams({ pagina, limite: POR_PAGINA });
    Object.entries(filtros).forEach(([k, v]) => { if (v !== "") p.append(k, v); });
    try {
      const datos = await pedir(`/api/solicitudes?${p}`);
      setFilas(datos.filas || []);
      setTotal(datos.total || 0);
    } catch {
      setFilas([]);
    } finally {
      setCargando(false);
    }
  }, [filtros, pagina]);

  // Al cambiar un filtro hay que volver a la pagina 1, o se ve una pagina vacia.
  useEffect(() => { setPagina(1); }, [filtros]);

  useEffect(() => {
    const t = setTimeout(cargar, 250);   // debounce para los filtros de texto
    return () => clearTimeout(t);
  }, [cargar, recargar]);

  const set = (k) => (e) => setFiltros((f) => ({ ...f, [k]: e.target.value }));
  // Pulsar otra vez la pastilla activa no cambia nada: ni recarga ni vuelve a la pagina 1.
  const elegirEstado = (v) => setFiltros((f) => (f.estado === v ? f : { ...f, estado: v }));
  const hayFiltros = Object.values(filtros).some((v) => v !== "");

  return (
    <div className="min-h-screen bg-slate-50">
      <PageHero
        icon={ClipboardList}
        eyebrow="Gestión"
        title="Seguimiento de solicitudes"
        subtitle="Recorrido de cada item por las etapas del flujo, hasta su creación en Siesa."
      />

      <PageBody>
        {/* ── Filtros (primer elemento: CARD blanca sobre el degradado del hero) ── */}
        <div className={`${CARD} p-4 space-y-4`}>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filtrar por estado">
              {ESTADOS.map((e) => (
                <button
                  key={e || "todos"}
                  type="button"
                  aria-pressed={filtros.estado === e}
                  onClick={() => elegirEstado(e)}
                  className={`px-3 py-1.5 text-xs font-semibold rounded-full border transition
                    ${filtros.estado === e
                      ? "bg-blue-600 text-white border-blue-600 shadow-sm"
                      : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"}`}
                >
                  {e || "Todos"}
                </button>
              ))}
            </div>
            {hayFiltros && (
              <button
                type="button"
                onClick={() => setFiltros(FILTROS_VACIOS)}
                className="ml-auto inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-slate-500 hover:text-slate-700 hover:bg-slate-50 transition-colors"
              >
                <X size={14} /> Limpiar filtros
              </button>
            )}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-3">
            <Field label="Etapa">
              <select className={SELECT} value={filtros.etapa_id} onChange={set("etapa_id")}>
                <option value="">Todas</option>
                {etapas.map((e) => <option key={e.id} value={e.id}>{e.nombre}</option>)}
              </select>
            </Field>
            <Field label="Vendedor">
              <select className={SELECT} value={filtros.vendedor_id} onChange={set("vendedor_id")}>
                <option value="">Todos</option>
                {vendedores.map((v) => <option key={v.id} value={v.id}>{v.nombre}</option>)}
              </select>
            </Field>
            <Field label="Cliente">
              <div className="relative">
                <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input type="text" className={`${INPUT} pl-9`} value={filtros.cliente}
                       placeholder="Buscar…" onChange={set("cliente")} />
              </div>
            </Field>
            <Field label="Referencia / item">
              <input type="text" className={`${INPUT} font-mono`} value={filtros.referencia}
                     placeholder="VASO 7 OZ…" onChange={set("referencia")} />
            </Field>
            <Field label="Marca">
              <input type="text" className={INPUT} value={filtros.marca}
                     placeholder="TOSTAO…" onChange={set("marca")} />
            </Field>
          </div>
        </div>

        {/* ── Tabla ── */}
        {filas.length === 0 ? (
          cargando ? <Loading label="Cargando solicitudes..." /> : (
            <Vacio icon={FileSearch} titulo="Sin resultados con estos filtros."
                   sub={hayFiltros ? "Prueba ajustando o limpiando los filtros." : undefined} />
          )
        ) : (
          <div className={`${CARD} overflow-hidden`}>
            <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-slate-100">
              <h2 className="font-semibold text-slate-800">Solicitudes</h2>
              <span className="text-xs text-slate-400 font-medium">
                {cargando ? "cargando…" : (
                  <><span className="font-semibold text-slate-700">{total.toLocaleString("es-CO")}</span> registros</>
                )}
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 bg-slate-50">
                    <th className={TH}>ID</th>
                    <th className={TH}>Item base</th>
                    <th className={TH}>Marca</th>
                    <th className={TH}>Cliente</th>
                    <th className={TH}>Calibre</th>
                    <th className={TH}>T. Impresión</th>
                    <th className={`${TH} !text-right`}>Cantidad</th>
                    <th className={`${TH} !text-right`}>Montaje</th>
                    <th className={TH}>Vendedor</th>
                    <th className={TH}>Etapa</th>
                    <th className={TH}>Estado</th>
                    <th className="px-5 py-3.5" />
                  </tr>
                </thead>
                <tbody>
                  {filas.map((s, idx) => (
                    <tr
                      key={s.id}
                      onClick={() => setAbierta(s.id)}
                      className={`border-b border-slate-100 last:border-0 cursor-pointer ${idx % 2 === 0 ? "bg-white" : "bg-slate-50/60"} hover:bg-blue-50/40 transition-colors`}
                    >
                      <td className="px-5 py-3 font-mono font-bold text-slate-700">{s.id}</td>
                      <td className="px-5 py-3 max-w-[260px] truncate">
                        {s.item_base
                          ? <span className="font-mono text-xs font-medium text-slate-800">{s.item_base}</span>
                          : <span className="text-xs italic text-slate-400">sin resolver</span>}
                      </td>
                      <td className="px-5 py-3 text-slate-600">{s.marca}</td>
                      <td className="px-5 py-3 text-slate-600 max-w-[220px] truncate">{s.cliente}</td>
                      <td className="px-5 py-3 font-mono text-xs text-slate-500">{s.calibre || "—"}</td>
                      <td className="px-5 py-3 text-slate-600">{s.tipo_impresion || <span className="text-slate-300">—</span>}</td>
                      <td className="px-5 py-3 font-mono text-right font-medium text-slate-700">
                        {s.cantidad?.toLocaleString("es-CO")}
                      </td>
                      <td className="px-5 py-3 font-mono text-right text-slate-700">
                        {s.montaje ?? <span className="text-slate-300">—</span>}
                      </td>
                      <td className="px-5 py-3 text-slate-600">{s.vendedor_nombre}</td>
                      <td className="px-5 py-3 text-slate-600">{s.etapa_actual || <span className="text-slate-300">—</span>}</td>
                      <td className="px-5 py-3"><Pill estado={s.estado}>{s.estado}</Pill></td>
                      <td className="px-5 py-3 text-right">
                        {s.adjuntos > 0 && (
                          <span className="inline-flex items-center gap-1 text-xs text-slate-400 whitespace-nowrap" title={`${s.adjuntos} adjunto(s)`}>
                            <Paperclip size={13} />
                            <span className="font-mono">{s.adjuntos}</span> adj.
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {filas.length > 0 && total > POR_PAGINA && (
          <div className="flex items-center justify-center gap-4 flex-wrap">
            <button className={BTN_SECUNDARIO} disabled={pagina <= 1} onClick={() => setPagina((p) => p - 1)}>
              <ChevronLeft size={15} /> Anterior
            </button>
            <span className="text-sm text-slate-500 font-medium">
              <span className="font-mono text-slate-800 font-bold">
                {((pagina - 1) * POR_PAGINA + 1).toLocaleString("es-CO")}–
                {Math.min(pagina * POR_PAGINA, total).toLocaleString("es-CO")}
              </span>{" "}
              de <span className="font-mono">{total.toLocaleString("es-CO")}</span>
            </span>
            <button className={BTN_SECUNDARIO} disabled={pagina * POR_PAGINA >= total} onClick={() => setPagina((p) => p + 1)}>
              Siguiente <ChevronRight size={15} />
            </button>
          </div>
        )}
      </PageBody>

      {abierta && <Detalle id={abierta} alCerrar={cerrarFicha} alCambiar={cargar} />}
    </div>
  );
}
