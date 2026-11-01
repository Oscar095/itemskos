import { useCallback, useEffect, useMemo, useState } from "react";
import {
  UserPlus, Pencil, KeyRound, Shield, ShieldPlus, Trash2,
  Users, Search, AlertCircle,
} from "lucide-react";
import { pedir } from "../api";
import { useAuthStore, usePermiso } from "../store/auth";
import {
  Aviso, BTN_PRIMARIO, CARD, Field, HeroTabs, INPUT, Loading, Modal,
  PageBody, PageHero, SELECT, TH, Vacio, fechaHora, initialsOf,
} from "../components/ui";

// Pantalla gemela de produccionweb/pages/Usuarios.tsx (mismo layout, tabla,
// modales y matriz de permisos, pero sin tarjetas de indicadores), con lo
// propio de esta app: correo (destino de las notificaciones), cargo (un
// Comercial activo es vendedor en las solicitudes), la casilla Activo para
// llevar el historial, y la explicacion de cada casilla por modulo.

const ACCIONES = [
  { key: "puede_ver", accion: "ver", label: "Ver" },
  { key: "puede_crear", accion: "crear", label: "Crear" },
  { key: "puede_editar", accion: "editar", label: "Editar" },
  { key: "puede_eliminar", accion: "eliminar", label: "Eliminar" },
];

function rolePillClass(name) {
  const n = (name || "").toLowerCase();
  if (n.includes("admin")) return "bg-violet-100 text-violet-700";
  if (n.includes("comercial")) return "bg-amber-100 text-amber-700";
  if (n.includes("dise")) return "bg-blue-100 text-blue-700";
  if (n.includes("plane")) return "bg-emerald-100 text-emerald-700";
  return "bg-slate-100 text-slate-600";
}

const fecha = (f) => fechaHora(f, { dateStyle: "short", timeStyle: "short" });

function useDatos() {
  const [usuarios, setUsuarios] = useState([]);
  const [roles, setRoles] = useState([]);
  const [modulos, setModulos] = useState([]);
  const [cargos, setCargos] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState("");

  const recargar = useCallback(async () => {
    try {
      const [u, r] = await Promise.all([pedir("/api/auth/usuarios"), pedir("/api/roles")]);
      setUsuarios(u); setRoles(r); setError("");
    } catch (e) {
      setError(e.message);
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    recargar();
    pedir("/api/roles/modulos").then(setModulos).catch(() => {});
    pedir("/api/auth/cargos").then(setCargos).catch(() => {});
  }, [recargar]);

  return { usuarios, roles, modulos, cargos, cargando, error, recargar };
}

// ─── Matriz de permisos ──────────────────────────────────────────────────────
function MatrizPermisos({ modulos, value, onChange }) {
  const getP = (modulo) =>
    value.find((p) => p.modulo === modulo) ?? { modulo, puede_ver: false, puede_crear: false, puede_editar: false, puede_eliminar: false };

  const toggle = (modulo, accion) => {
    const actual = getP(modulo);
    const nuevo = { ...actual, [accion]: !actual[accion] };
    if (accion === "puede_ver" && !nuevo.puede_ver) {
      nuevo.puede_crear = false; nuevo.puede_editar = false; nuevo.puede_eliminar = false;
    }
    if (accion !== "puede_ver" && nuevo[accion]) nuevo.puede_ver = true;
    onChange(value.filter((p) => p.modulo !== modulo).concat(nuevo));
  };

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-100">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 border-b border-slate-100">
          <tr>
            <th className="text-left px-3 py-2.5 text-xs font-semibold text-slate-600 uppercase tracking-wide">Módulo</th>
            {ACCIONES.map((a) => (
              <th key={a.key} className="px-3 py-2.5 text-xs font-semibold text-slate-600 uppercase tracking-wide text-center">{a.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {modulos.map(({ clave, label, acciones }, i) => {
            const p = getP(clave);
            return (
              <tr key={clave} className={`${i % 2 === 0 ? "bg-white" : "bg-slate-50/60"} hover:bg-blue-50/40 transition-colors`}>
                <td className="px-3 py-2">
                  <p className="font-medium text-slate-700">{label}</p>
                  {/* Que significa cada casilla en este modulo: no todas aplican en todos. */}
                  <p className="text-[11px] text-slate-400 leading-snug max-w-[220px]">
                    {ACCIONES.filter((a) => acciones[a.accion]).map((a) => `${a.label}: ${acciones[a.accion]}`).join(" · ")}
                  </p>
                </td>
                {ACCIONES.map((a) => {
                  const aplica = a.accion === "ver" || acciones[a.accion];
                  return (
                    <td key={a.key} className="px-3 py-2 text-center">
                      {aplica ? (
                        <input type="checkbox" checked={p[a.key]} onChange={() => toggle(clave, a.key)}
                               className="w-4 h-4 accent-blue-600 cursor-pointer" title={acciones[a.accion] || "Ver el módulo"} />
                      ) : (
                        <span className="text-slate-200">—</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Tab: Roles ──────────────────────────────────────────────────────────────
function TabRoles({ datos, permiso }) {
  const { roles, modulos, recargar } = datos;
  const [nuevo, setNuevo] = useState(null);         // {nombre, descripcion, permisos}
  const [editando, setEditando] = useState(null);   // rol
  const [permisos, setPermisos] = useState([]);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");

  const enviar = async (fn) => {
    setGuardando(true); setError("");
    try { await fn(); await recargar(); setNuevo(null); setEditando(null); }
    catch (e) { setError(e.message); }
    finally { setGuardando(false); }
  };

  const desactivar = (r) => {
    if (!confirm(`¿Desactivar el rol "${r.nombre}"?`)) return;
    pedir(`/api/roles/${r.id}`, { method: "DELETE" }).then(recargar).catch((e) => alert(e.message));
  };

  return (
    <div className="space-y-6">
      {/* Cabecera y tabla en una sola tarjeta blanca: es lo primero que queda sobre el degradado. */}
      <div className={`${CARD} overflow-hidden`}>
        <div className={`px-5 py-4 flex items-center justify-between flex-wrap gap-3 ${roles.length > 0 ? "border-b border-slate-100" : ""}`}>
          <p className="text-sm text-slate-500">
            <span className="font-semibold text-slate-700">{roles.length}</span> roles configurados
          </p>
          {permiso.crear && (
            <button onClick={() => { setError(""); setNuevo({ nombre: "", descripcion: "", permisos: [] }); }} className={BTN_PRIMARIO}>
              <ShieldPlus size={16} /> Nuevo Rol
            </button>
          )}
        </div>

        {roles.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50">
                  <th className={TH}>Rol</th>
                  <th className={`${TH} hidden sm:table-cell`}>Módulos con acceso</th>
                  <th className={`${TH} hidden sm:table-cell`}>Usuarios</th>
                  <th className="px-5 py-3.5" />
                </tr>
              </thead>
              <tbody>
                {roles.map((r, idx) => {
                  const activos = r.permisos.filter((p) => p.puede_ver).length;
                  return (
                    <tr key={r.id} className={`border-b border-slate-100 last:border-0 ${idx % 2 === 0 ? "bg-white" : "bg-slate-50/60"} hover:bg-blue-50/40 transition-colors`}>
                      <td className="px-5 py-3">
                        <p className="font-semibold text-slate-800">{r.nombre}</p>
                        {r.descripcion && <p className="text-xs text-slate-400">{r.descripcion}</p>}
                        {/* En celular las dos columnas de conteo se ocultan y el dato va aqui. */}
                        <p className="sm:hidden text-xs text-slate-400 mt-0.5">
                          <span className="font-semibold text-slate-600">{activos}</span> módulo(s) con acceso ·{" "}
                          <span className="font-semibold text-slate-600">{r.usuarios}</span> usuario(s)
                        </p>
                      </td>
                      <td className="px-5 py-3 text-slate-600 hidden sm:table-cell">{activos}</td>
                      <td className="px-5 py-3 text-slate-600 hidden sm:table-cell">{r.usuarios}</td>
                      <td className="px-5 py-3">
                        <div className="flex items-center gap-1 justify-end">
                          <button
                            onClick={() => { setError(""); setPermisos(r.permisos.map((p) => ({ ...p }))); setEditando(r); }}
                            className="flex items-center gap-1 px-3 py-1.5 text-xs bg-white border border-slate-200 rounded-lg hover:bg-slate-50 text-slate-600 whitespace-nowrap transition-colors"
                          >
                            <Pencil size={13} /> {permiso.editar ? "Permisos" : "Ver permisos"}
                          </button>
                          {permiso.eliminar && (
                            <button onClick={() => desactivar(r)} title="Desactivar"
                                    className="p-2 text-rose-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors">
                              <Trash2 size={15} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {roles.length === 0 && (
        <Vacio icon={Shield} titulo="No hay roles configurados." sub="Crea uno nuevo para empezar." />
      )}

      {nuevo && (
        <Modal title="Nuevo Rol" onClose={() => setNuevo(null)} ancho="max-w-2xl">
          <div className="space-y-4">
            <Field label="Nombre *">
              <input className={INPUT} value={nuevo.nombre} onChange={(e) => setNuevo((f) => ({ ...f, nombre: e.target.value }))} />
            </Field>
            <Field label="Descripción">
              <input className={INPUT} value={nuevo.descripcion} onChange={(e) => setNuevo((f) => ({ ...f, descripcion: e.target.value }))} />
            </Field>
            <Field label="Permisos por módulo">
              <MatrizPermisos modulos={modulos} value={nuevo.permisos} onChange={(p) => setNuevo((f) => ({ ...f, permisos: p }))} />
            </Field>
            <button
              onClick={() => enviar(() => pedir("/api/roles", { method: "POST", json: { ...nuevo, descripcion: nuevo.descripcion || null } }))}
              disabled={!nuevo.nombre.trim() || guardando}
              className={`${BTN_PRIMARIO} w-full py-2.5`}
            >
              {guardando ? "Guardando..." : "Crear Rol"}
            </button>
            {error && <p className="text-rose-500 text-xs text-center">{error}</p>}
          </div>
        </Modal>
      )}

      {editando && (
        <Modal title={`Permisos — ${editando.nombre}`} onClose={() => setEditando(null)} ancho="max-w-2xl">
          <div className="space-y-4">
            <MatrizPermisos modulos={modulos} value={permisos} onChange={permiso.editar ? setPermisos : () => {}} />
            {permiso.editar && (
              <button
                onClick={() => enviar(() => pedir(`/api/roles/${editando.id}/permisos`, { method: "PUT", json: { permisos } }))}
                disabled={guardando}
                className={`${BTN_PRIMARIO} w-full py-2.5`}
              >
                {guardando ? "Guardando..." : "Guardar Permisos"}
              </button>
            )}
            {error && <p className="text-rose-500 text-xs text-center">{error}</p>}
          </div>
        </Modal>
      )}
    </div>
  );
}

// ─── Tab: Usuarios ───────────────────────────────────────────────────────────
const VACIO_NUEVO = { username: "", nombre: "", email: "", cargo: "", password: "", rol_id: "", activo: true };
const correoValido = (e) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test((e || "").trim());

// Activos = la nomina actual; Inactivos = historial (siguen ligados a sus solicitudes).
const FILTROS_ESTADO = [
  { key: "activos", label: "Activos" },
  { key: "inactivos", label: "Inactivos" },
  { key: "todos", label: "Todos" },
];

function CasillaActivo({ checked, onChange, label = "Activo", hint, disabled = false }) {
  return (
    <label className={`flex items-start gap-3 select-none ${disabled ? "opacity-60 cursor-not-allowed" : "cursor-pointer"}`}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)}
             className="mt-0.5 w-4 h-4 accent-blue-600 cursor-pointer disabled:cursor-not-allowed" />
      <span>
        <span className="block text-sm font-medium text-slate-700">{label}</span>
        {hint && <span className="block text-xs text-slate-400">{hint}</span>}
      </span>
    </label>
  );
}

function TabUsuarios({ datos, permiso, nuevoAbierto, setNuevoAbierto }) {
  const { usuarios, roles, cargos, cargando, recargar } = datos;
  const yo = useAuthStore((s) => s.user);
  const [modal, setModal] = useState(null);   // 'editar' | 'password'
  const [sel, setSel] = useState(null);
  const [busqueda, setBusqueda] = useState("");
  const [estado, setEstado] = useState("activos");
  const [nuevoForm, setNuevoForm] = useState(VACIO_NUEVO);
  const [editForm, setEditForm] = useState({ nombre: "", email: "", cargo: "", rol_id: "", activo: true });
  const [pwd, setPwd] = useState("");
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState(null);   // {tono, texto} de acciones en la tabla

  const cerrar = () => { setModal(null); setNuevoAbierto(false); setError(""); };
  const enviar = async (fn, alTerminar) => {
    setGuardando(true); setError("");
    try {
      await fn(); await recargar(); alTerminar?.(); cerrar();
      // Si me edite a mi mismo (cargo, nombre...), la sesion del navegador debe reflejarlo.
      if (sel?.id === yo?.id) useAuthStore.getState().cargar();
    }
    catch (e) { setError(e.message); }
    finally { setGuardando(false); }
  };

  const filtrados = useMemo(() => {
    const q = busqueda.toLowerCase().trim();
    return usuarios
      .filter((u) => estado === "todos" || (estado === "activos" ? u.activo : !u.activo))
      .filter((u) => !q || [u.nombre, u.username, u.email, u.cargo, u.rol_nombre]
        .some((v) => (v ?? "").toLowerCase().includes(q)));
  }, [usuarios, busqueda, estado]);

  // Activar pide "editar"; desactivar pide "eliminar" (mismas reglas que el backend).
  const puedeAlternar = (u) => u.id !== yo?.id && (u.activo ? permiso.eliminar : permiso.editar);
  // Un usuario cuyo rol se desactivo no puede volver a entrar: antes de reactivarlo hay que darle otro rol.
  const rolActivo = (u) => roles.some((r) => r.id === u.rol_id);

  const alternarActivo = async (u, activo) => {
    if (!activo && !confirm(`¿Desactivar a "${u.nombre}"?\n\nSale de los listados (por ejemplo, de los vendedores de una solicitud) y se cierran sus sesiones. Su historial se conserva.`)) return;
    setAviso(null);
    try {
      // Desactivar va por DELETE (solo exige "eliminar"); reactivar, por PATCH ("editar").
      await (activo
        ? pedir(`/api/auth/usuarios/${u.id}`, { method: "PATCH", json: { activo: true } })
        : pedir(`/api/auth/usuarios/${u.id}`, { method: "DELETE" }));
      await recargar();
      setAviso({ tono: "ok", texto: `${u.nombre} quedó ${activo ? "activo" : "inactivo"}.` });
    } catch (e) {
      setAviso({ tono: "error", texto: e.message });
    }
  };

  return (
    <div className="space-y-6">
      {/* Barra de busqueda: tarjeta blanca, porque es lo primero que queda sobre el degradado. */}
      <div className={`${CARD} p-4 space-y-3`}>
        <div className="flex items-center gap-3 flex-wrap">
          <div className="relative flex-1 min-w-[220px] max-w-sm">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text" placeholder="Buscar por nombre, usuario, correo, cargo o rol..." value={busqueda}
              onChange={(e) => setBusqueda(e.target.value)}
              className="w-full pl-9 pr-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 shadow-sm"
            />
          </div>
          <div className="flex items-center gap-2">
            {FILTROS_ESTADO.map((f) => (
              <button key={f.key} onClick={() => setEstado(f.key)}
                      className={`px-3 py-1.5 text-xs font-semibold rounded-full border transition
                        ${estado === f.key
                          ? "bg-blue-600 text-white border-blue-600 shadow-sm"
                          : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"}`}>
                {f.label}
              </button>
            ))}
          </div>
          {busqueda && (
            <button onClick={() => setBusqueda("")} className="text-xs text-slate-400 hover:text-slate-600 underline underline-offset-2">
              Limpiar
            </button>
          )}
          <p className="text-sm text-slate-500 ml-auto">
            <span className="font-semibold text-slate-700">{filtrados.length}</span> de{" "}
            <span className="font-semibold text-slate-700">{usuarios.length}</span> usuarios
          </p>
        </div>
        {aviso && <Aviso tono={aviso.tono}>{aviso.texto}</Aviso>}
      </div>

      {cargando ? <Loading label="Cargando usuarios..." /> : filtrados.length === 0 ? (
        <Vacio icon={Users}
               titulo={busqueda ? "Sin resultados para la búsqueda."
                 : estado === "inactivos" ? "No hay usuarios inactivos."
                 : usuarios.length ? "No hay usuarios activos." : "No hay usuarios registrados."}
               sub={busqueda ? "Prueba con otro término." : usuarios.length ? "Cambia el filtro para ver los demás." : "Crea un usuario nuevo para empezar."} />
      ) : (
        <div className={`${CARD} overflow-hidden`}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50">
                  <th className={TH}>Usuario</th>
                  <th className={`${TH} hidden md:table-cell`}>Cargo</th>
                  <th className={TH}>Rol</th>
                  <th className={`${TH} hidden lg:table-cell`}>Último ingreso</th>
                  <th className={`${TH} !text-center`}>Activo</th>
                  <th className="px-5 py-3.5" />
                </tr>
              </thead>
              <tbody>
                {filtrados.map((u, idx) => (
                  <tr key={u.id} className={`border-b border-slate-100 last:border-0 ${idx % 2 === 0 ? "bg-white" : "bg-slate-50/60"} hover:bg-blue-50/40 transition-colors ${u.activo ? "" : "opacity-60"}`}>
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-3">
                        <div className="w-9 h-9 rounded-full bg-gradient-to-br from-blue-400 to-blue-600 text-white flex items-center justify-center font-bold text-xs shadow-sm shrink-0">
                          {initialsOf(u.nombre)}
                        </div>
                        <div className="min-w-0">
                          <p className="font-semibold text-slate-800 truncate">
                            {u.nombre}{u.id === yo?.id && <span className="ml-2 text-[11px] font-medium text-blue-600">(tú)</span>}
                          </p>
                          <p className="text-xs text-slate-400 truncate">
                            @{u.username} ·{" "}
                            {u.email || <span className="text-amber-600 font-medium">sin correo</span>}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-slate-600 hidden md:table-cell">{u.cargo || <span className="text-slate-300">—</span>}</td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-3 py-1 text-xs font-bold ${rolePillClass(u.rol_nombre)}`}>{u.rol_nombre}</span>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-400 font-mono hidden lg:table-cell">{fecha(u.ultimo_ingreso)}</td>
                    <td className="px-4 py-3 text-center">
                      <input
                        type="checkbox" checked={u.activo} disabled={!puedeAlternar(u) || (!u.activo && !rolActivo(u))}
                        onChange={(e) => alternarActivo(u, e.target.checked)}
                        className="w-4 h-4 accent-blue-600 cursor-pointer disabled:cursor-not-allowed"
                        aria-label={`${u.nombre} activo`}
                        title={u.id === yo?.id ? "No puedes desactivar tu propio usuario"
                          : !u.activo && !rolActivo(u) ? "Su rol está desactivado: edítalo y asígnale otro rol para reactivarlo"
                          : puedeAlternar(u) ? (u.activo ? "Desmarca para desactivar" : "Marca para reactivar")
                          : "Tu rol no puede cambiar el estado de este usuario"}
                      />
                    </td>
                    <td className="px-5 py-3">
                      {permiso.editar && (
                        <div className="flex items-center gap-1 justify-end">
                          <button
                            onClick={() => {
                              setSel(u); setError("");
                              setEditForm({ nombre: u.nombre, email: u.email || "", cargo: u.cargo || "", rol_id: String(u.rol_id), activo: u.activo });
                              setModal("editar");
                            }}
                            className="p-2 rounded-lg text-slate-400 hover:text-blue-600 hover:bg-slate-100 transition-colors" title="Editar"
                          >
                            <Pencil size={15} />
                          </button>
                          <button
                            onClick={() => { setSel(u); setPwd(""); setError(""); setModal("password"); }}
                            className="p-2 rounded-lg text-slate-400 hover:text-amber-600 hover:bg-slate-100 transition-colors" title="Cambiar contraseña"
                          >
                            <KeyRound size={15} />
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {nuevoAbierto && (
        <Modal title="Nuevo Usuario" onClose={cerrar}>
          <div className="space-y-4">
            <Field label="Usuario *" hint="Con esto inicia sesión. Letras sin tilde, números, punto o guion.">
              <input className={INPUT} value={nuevoForm.username} autoComplete="off"
                     onChange={(e) => setNuevoForm((f) => ({ ...f, username: e.target.value.toLowerCase().replace(/\s/g, "") }))} />
            </Field>
            <Field label="Nombre completo *">
              <input className={INPUT} value={nuevoForm.nombre} onChange={(e) => setNuevoForm((f) => ({ ...f, nombre: e.target.value }))} />
            </Field>
            <Field label="Correo electrónico *" hint="Aquí le llegarán las notificaciones de avance.">
              <input type="email" className={INPUT} value={nuevoForm.email} autoComplete="off" placeholder="nombre@koscolombia.com"
                     onChange={(e) => setNuevoForm((f) => ({ ...f, email: e.target.value }))} />
            </Field>
            <Field label="Cargo" hint="Comercial: aparece como vendedor al crear solicitudes.">
              <select className={SELECT} value={nuevoForm.cargo} onChange={(e) => setNuevoForm((f) => ({ ...f, cargo: e.target.value }))}>
                <option value="">Seleccionar cargo...</option>
                {cargos.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </Field>
            <Field label="Contraseña *" hint="Mínimo 8 caracteres. Compártela con el usuario por un canal seguro.">
              <input type="password" className={INPUT} value={nuevoForm.password} autoComplete="new-password"
                     onChange={(e) => setNuevoForm((f) => ({ ...f, password: e.target.value }))} />
            </Field>
            <Field label="Rol *">
              <select className={SELECT} value={nuevoForm.rol_id} onChange={(e) => setNuevoForm((f) => ({ ...f, rol_id: e.target.value }))}>
                <option value="">Seleccionar rol...</option>
                {roles.map((r) => <option key={r.id} value={r.id}>{r.nombre}</option>)}
              </select>
            </Field>
            <CasillaActivo checked={nuevoForm.activo} onChange={(v) => setNuevoForm((f) => ({ ...f, activo: v }))}
                           hint="Desmárcalo para registrar a alguien que ya no está, solo por historial." />
            <button
              onClick={() => enviar(() => pedir("/api/auth/usuarios", {
                method: "POST",
                json: { ...nuevoForm, email: nuevoForm.email.trim(), cargo: nuevoForm.cargo || null, rol_id: Number(nuevoForm.rol_id) },
              }), () => setNuevoForm(VACIO_NUEVO))}
              disabled={!nuevoForm.username || !nuevoForm.nombre.trim() || !correoValido(nuevoForm.email)
                || nuevoForm.password.length < 8 || !nuevoForm.rol_id || guardando}
              className={`${BTN_PRIMARIO} w-full py-2.5`}
            >
              {guardando ? "Guardando..." : "Crear Usuario"}
            </button>
            {error && <p className="text-rose-500 text-xs text-center">{error}</p>}
          </div>
        </Modal>
      )}

      {modal === "editar" && sel && (
        <Modal title={`Editar — ${sel.username}`} onClose={cerrar}>
          <div className="space-y-4">
            <Field label="Nombre">
              <input className={INPUT} value={editForm.nombre} onChange={(e) => setEditForm((f) => ({ ...f, nombre: e.target.value }))} />
            </Field>
            <Field label="Correo electrónico *" hint="Aquí le llegarán las notificaciones de avance.">
              <input type="email" className={INPUT} value={editForm.email} autoComplete="off"
                     onChange={(e) => setEditForm((f) => ({ ...f, email: e.target.value }))} />
            </Field>
            <Field label="Cargo" hint="Comercial: aparece como vendedor al crear solicitudes.">
              <select className={SELECT} value={editForm.cargo} onChange={(e) => setEditForm((f) => ({ ...f, cargo: e.target.value }))}>
                <option value="">Sin cargo</option>
                {/* Un cargo desactivado en Configuracion se conserva para quien ya lo tiene. */}
                {sel.cargo && !cargos.includes(sel.cargo) && <option value={sel.cargo}>{sel.cargo} (inactivo)</option>}
                {cargos.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </Field>
            <Field label="Rol">
              <select className={SELECT} value={editForm.rol_id} disabled={sel.id === yo?.id}
                      onChange={(e) => setEditForm((f) => ({ ...f, rol_id: e.target.value }))}>
                {/* Sin esto el select mostraria el primer rol (Admin) en vez del rol inactivo real. */}
                {!rolActivo(sel) && <option value={String(sel.rol_id)} disabled>{sel.rol_nombre} (rol inactivo: elige otro)</option>}
                {roles.map((r) => <option key={r.id} value={r.id}>{r.nombre}</option>)}
              </select>
              {sel.id === yo?.id && <p className="text-xs text-slate-400">No puedes cambiar tu propio rol.</p>}
            </Field>
            {sel.id !== yo?.id && (
              <CasillaActivo checked={editForm.activo}
                             onChange={(v) => setEditForm((f) => ({ ...f, activo: v }))}
                             disabled={sel.activo ? !permiso.eliminar : false}
                             hint="Inactivo: no entra ni aparece en los listados; su historial se conserva." />
            )}
            <button
              onClick={() => enviar(() => pedir(`/api/auth/usuarios/${sel.id}`, {
                method: "PATCH",
                json: {
                  nombre: editForm.nombre.trim() || null,
                  email: editForm.email.trim(),
                  cargo: editForm.cargo,
                  rol_id: Number(editForm.rol_id),
                  // Solo si cambio: desmarcarla pide "eliminar", y mandarla igual haria fallar todo el guardado.
                  activo: sel.id === yo?.id || editForm.activo === sel.activo ? null : editForm.activo,
                },
              }))}
              disabled={!correoValido(editForm.email) || guardando
                || (editForm.activo && !roles.some((r) => String(r.id) === String(editForm.rol_id)))}
              className={`${BTN_PRIMARIO} w-full py-2.5`}
            >
              {guardando ? "Guardando..." : "Guardar Cambios"}
            </button>
            {error && <p className="text-rose-500 text-xs text-center">{error}</p>}
          </div>
        </Modal>
      )}

      {modal === "password" && sel && (
        <Modal title={`Contraseña — ${sel.username}`} onClose={cerrar}>
          <div className="space-y-4">
            <Field label="Nueva contraseña *" hint="Mínimo 8 caracteres. Sus sesiones abiertas se cerrarán.">
              <input type="password" className={INPUT} value={pwd} autoComplete="new-password" onChange={(e) => setPwd(e.target.value)} />
            </Field>
            <button
              onClick={() => enviar(() => pedir(`/api/auth/usuarios/${sel.id}/password`, { method: "POST", json: { nueva_password: pwd } }))}
              disabled={pwd.length < 8 || guardando}
              className={`${BTN_PRIMARIO} w-full py-2.5`}
            >
              {guardando ? "Cambiando..." : "Cambiar Contraseña"}
            </button>
            {error && <p className="text-rose-500 text-xs text-center">{error}</p>}
          </div>
        </Modal>
      )}
    </div>
  );
}

// ─── Página principal ────────────────────────────────────────────────────────
export default function Usuarios() {
  const [tab, setTab] = useState("usuarios");
  const [nuevoAbierto, setNuevoAbierto] = useState(false);
  const permiso = usePermiso("usuarios");
  const datos = useDatos();

  return (
    <div className="min-h-screen bg-slate-50">
      <PageHero
        icon={Users} eyebrow="Administración" title="Usuarios y Roles"
        subtitle="Gestiona accesos, roles y permisos de la plataforma"
        actions={tab === "usuarios" && permiso.crear && (
          <button onClick={() => setNuevoAbierto(true)} className={BTN_PRIMARIO}>
            <UserPlus size={15} /> Nuevo Usuario
          </button>
        )}
      >
        <HeroTabs
          value={tab} onChange={setTab}
          tabs={[
            { key: "usuarios", label: "Usuarios", icon: <Users size={14} /> },
            { key: "roles", label: "Roles y Permisos", icon: <Shield size={14} /> },
          ]}
        />
      </PageHero>

      <PageBody>
        {datos.error && <Aviso tono="error" icon={AlertCircle}>{datos.error}</Aviso>}
        {tab === "usuarios"
          ? <TabUsuarios datos={datos} permiso={permiso} nuevoAbierto={nuevoAbierto} setNuevoAbierto={setNuevoAbierto} />
          : <TabRoles datos={datos} permiso={permiso} />}
      </PageBody>
    </div>
  );
}
