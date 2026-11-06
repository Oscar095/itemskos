import { useCallback, useEffect, useRef, useState } from "react";
import { Settings, Plus, Layers, ListChecks, AlertCircle, SlidersHorizontal, Briefcase, Lock, Printer } from "lucide-react";
import { pedir } from "../api";
import { usePermiso } from "../store/auth";
import {
  Aviso, BTN_PRIMARIO, CARD, HeroTabs, INPUT, Loading, PageBody, PageHero, TH, Vacio, fechaHora,
} from "../components/ui";

// Listas que usan las solicitudes y los usuarios. Se agregan o se desactivan;
// no se renombran ni se borran, porque cada registro guarda el nombre y el
// historial no debe cambiar.
const ICONOS = {
  materiales: <Layers size={14} />, tipos_solicitud: <ListChecks size={14} />,
  tipos_impresion: <Printer size={14} />, cargos: <Briefcase size={14} />,
};
const PLACEHOLDER = {
  materiales: "Nuevo tipo de material…", tipos_solicitud: "Nuevo tipo de solicitud…",
  tipos_impresion: "Nuevo tipo de impresión…", cargos: "Nuevo cargo…",
};
const DESTINO = { cargos: "el formulario de usuarios" };   // por defecto: el de solicitudes

export default function Configuracion() {
  const permiso = usePermiso("configuracion");
  const [listas, setListas] = useState([]);
  const [lista, setLista] = useState("materiales");
  const [filas, setFilas] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [nombre, setNombre] = useState("");
  const [guardando, setGuardando] = useState(false);
  const [aviso, setAviso] = useState(null);   // {tono, texto}
  // Lista visible ahora: una respuesta de la pestaña anterior que llegue tarde se descarta.
  const vigente = useRef(lista);
  vigente.current = lista;

  useEffect(() => {
    pedir("/api/config/listas").then(setListas).catch((e) => setAviso({ tono: "error", texto: e.message }));
  }, []);

  const cargar = useCallback(async () => {
    try {
      const datos = await pedir(`/api/config/opciones/${lista}`);
      if (vigente.current === lista) setFilas(datos);
    } catch (e) {
      if (vigente.current === lista) setAviso({ tono: "error", texto: e.message });
    } finally {
      if (vigente.current === lista) setCargando(false);
    }
  }, [lista]);

  useEffect(() => { setCargando(true); setAviso(null); setNombre(""); cargar(); }, [cargar]);

  const etiqueta = listas.find((l) => l.clave === lista)?.label ?? "";

  const agregar = async (e) => {
    e.preventDefault();
    setGuardando(true); setAviso(null);
    try {
      const nueva = await pedir(`/api/config/opciones/${lista}`, { method: "POST", json: { nombre } });
      setNombre("");
      await cargar();
      setAviso({ tono: "ok", texto: `«${nueva.nombre}» agregado. Ya aparece en ${DESTINO[lista] ?? "el formulario de solicitudes"}.` });
    } catch (err) {
      setAviso({ tono: "error", texto: err.message });
    } finally {
      setGuardando(false);
    }
  };

  const alternar = async (f, activo) => {
    setAviso(null);
    try {
      const r = await pedir(`/api/config/opciones/${lista}/${f.id}`, { method: "PATCH", json: { activo } });
      setFilas((fs) => fs.map((x) => (x.id === r.id ? r : x)));
      setAviso({ tono: "ok", texto: activo
        ? `«${f.nombre}» activo de nuevo.`
        : `«${f.nombre}» desactivado: ya no se ofrece en registros nuevos; los anteriores lo conservan.` });
    } catch (err) {
      setAviso({ tono: "error", texto: err.message });
    }
  };

  const activas = filas.filter((f) => f.activo).length;

  return (
    <div className="min-h-screen bg-slate-50">
      <PageHero icon={Settings} eyebrow="Administración" title="Configuración"
                subtitle="Listas que se usan en las solicitudes y en los usuarios">
        <HeroTabs value={lista} onChange={setLista}
                  tabs={listas.map((l) => ({ key: l.clave, label: l.label, icon: ICONOS[l.clave] ?? <SlidersHorizontal size={14} /> }))} />
      </PageHero>

      <PageBody>
        {/* Primer bloque en tarjeta: queda montado sobre el degradado del encabezado. */}
        <div className={`${CARD} p-4 space-y-3`}>
          <div className="flex items-center gap-3 flex-wrap">
            {permiso.crear ? (
              <form onSubmit={agregar} className="flex gap-2 flex-1 min-w-[260px] max-w-md">
                <input className={INPUT} value={nombre} maxLength={60} placeholder={PLACEHOLDER[lista] ?? "Nueva opción…"}
                       onChange={(e) => setNombre(e.target.value)} />
                <button type="submit" className={`${BTN_PRIMARIO} shrink-0`} disabled={!nombre.trim() || guardando}>
                  <Plus size={15} /> {guardando ? "Agregando..." : "Agregar"}
                </button>
              </form>
            ) : (
              <p className="text-sm text-slate-500">Tu rol puede ver estas listas, pero no agregar opciones.</p>
            )}
            <p className="text-sm text-slate-500 ml-auto">
              <span className="font-semibold text-slate-700">{activas}</span> activas de{" "}
              <span className="font-semibold text-slate-700">{filas.length}</span>
            </p>
          </div>
          {aviso && <Aviso tono={aviso.tono} icon={aviso.tono === "error" ? AlertCircle : undefined}>{aviso.texto}</Aviso>}
        </div>

        {cargando ? <Loading label="Cargando..." /> : filas.length === 0 ? (
          <Vacio icon={Settings} titulo={`No hay opciones de ${etiqueta.toLowerCase()}.`} sub="Agrega la primera." />
        ) : (
          <div className={`${CARD} overflow-hidden`}>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 bg-slate-50">
                    <th className={TH}>{etiqueta}</th>
                    <th className={`${TH} hidden md:table-cell`}>Agregado</th>
                    <th className={`${TH} !text-center w-28`}>Activo</th>
                  </tr>
                </thead>
                <tbody>
                  {filas.map((f, idx) => (
                    <tr key={f.id} className={`border-b border-slate-100 last:border-0 ${idx % 2 === 0 ? "bg-white" : "bg-slate-50/60"} hover:bg-blue-50/40 transition-colors ${f.activo ? "" : "opacity-60"}`}>
                      <td className="px-5 py-3 font-medium text-slate-800">
                        {f.nombre}
                        {f.protegida && (
                          <span className="ml-2 inline-flex items-center gap-1 text-[11px] font-medium text-slate-400" title={f.protegida}>
                            <Lock size={11} /> requerido
                          </span>
                        )}
                      </td>
                      <td className="px-5 py-3 text-xs text-slate-400 hidden md:table-cell">
                        {f.creado_por === "sistema" ? "Lista original" : `${f.creado_por || "—"} · ${fechaHora(f.created_at, { dateStyle: "short", timeStyle: "short" })}`}
                      </td>
                      <td className="px-5 py-3 text-center">
                        <input type="checkbox" checked={f.activo} disabled={!permiso.editar || (f.protegida && f.activo)}
                               onChange={(e) => alternar(f, e.target.checked)}
                               className="w-4 h-4 accent-blue-600 cursor-pointer disabled:cursor-not-allowed"
                               aria-label={`${f.nombre} activo`}
                               title={f.protegida && f.activo ? `No se puede desactivar. ${f.protegida}`
                                 : permiso.editar ? (f.activo ? "Desmarca para dejar de ofrecerlo" : "Marca para volver a ofrecerlo")
                                 : "Tu rol no puede cambiarlo"} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </PageBody>
    </div>
  );
}
