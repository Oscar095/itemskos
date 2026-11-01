import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  ClipboardList, FilePlus2, Users, Settings, LogOut, KeyRound,
  Menu, X, ChevronUp, ChevronDown, ChevronLeft, ChevronRight, PackageCheck,
} from "lucide-react";
import { useAuthStore } from "../store/auth";
import { pedir } from "../api";
import { Aviso, BTN_PRIMARIO, Field, INPUT, Modal } from "./ui";

// Cada entrada se muestra si el rol tiene el permiso indicado (como NAV en
// produccionweb/Layout.tsx, que filtra por permisos[modulo].ver).
export const NAV = [
  { to: "/seguimiento", label: "Seguimiento", Icon: ClipboardList, modulo: "seguimiento", accion: "ver" },
  { to: "/nueva", label: "Nueva solicitud", Icon: FilePlus2, modulo: "solicitudes", accion: "crear" },
  { to: "/planeacion", label: "Planeación", Icon: PackageCheck, modulo: "planeacion", accion: "ver" },
  { to: "/usuarios", label: "Usuarios", Icon: Users, modulo: "usuarios", accion: "ver" },
  { to: "/configuracion", label: "Configuración", Icon: Settings, modulo: "configuracion", accion: "ver" },
];

export const puedeVer = (user, { modulo, accion }) => user?.permisos?.[modulo]?.[accion] ?? false;

function leer(clave, defecto) {
  try { return localStorage.getItem(clave) ?? defecto; } catch { return defecto; }
}
function guardar(clave, valor) {
  try { localStorage.setItem(clave, valor); } catch { /* sin almacenamiento */ }
}

export default function Layout({ children }) {
  const { user, logout } = useAuthStore();
  const navigate = useNavigate();
  const [bannerVisible, setBannerVisible] = useState(() => leer("kos-banner-visible", "1") !== "0");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [colapsado, setColapsado] = useState(() => leer("kos-sidebar-collapsed", "0") === "1");
  const [cambiarClave, setCambiarClave] = useState(false);

  const salir = async () => {
    await logout();
    navigate("/login");
  };
  const alternarBanner = () => setBannerVisible((v) => { guardar("kos-banner-visible", v ? "0" : "1"); return !v; });
  const alternarSidebar = () => setColapsado((v) => { guardar("kos-sidebar-collapsed", v ? "0" : "1"); return !v; });

  const sidebar = (
    <aside className="w-56 bg-blue-900 text-white flex flex-col h-full">
      <div className="border-b border-blue-800">
        {bannerVisible && (
          <div className="px-5 pt-6 pb-3">
            <div className="flex items-center gap-2 mb-2">
              <img src="/logo.png" alt="KOS Logo" className="h-14 w-auto object-contain" />
            </div>
            <p className="text-xs text-blue-300 mt-0.5">Creación de Items</p>
          </div>
        )}
        <button
          onClick={alternarBanner}
          className="w-full flex items-center justify-center py-1.5 text-blue-400 hover:text-white hover:bg-blue-800 transition"
          aria-label={bannerVisible ? "Ocultar banner" : "Mostrar banner"}
        >
          {bannerVisible ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {NAV.filter((n) => puedeVer(user, n)).map(({ to, label, Icon }) => (
          <NavLink
            key={to}
            to={to}
            onClick={() => setMobileOpen(false)}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition
              ${isActive ? "bg-blue-700 text-white" : "text-blue-200 hover:bg-blue-800 hover:text-white"}`
            }
          >
            <Icon size={18} />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="px-5 py-4 border-t border-blue-800 shrink-0">
        <p className="text-xs text-blue-300 truncate">{user?.nombre}</p>
        <p className="text-xs text-blue-400 capitalize">{user?.rol}</p>
        <button onClick={() => setCambiarClave(true)}
                className="mt-3 flex items-center gap-2 text-xs text-blue-300 hover:text-white transition">
          <KeyRound size={14} /> Cambiar contraseña
        </button>
        <button onClick={salir} className="mt-2 flex items-center gap-2 text-xs text-blue-300 hover:text-white transition">
          <LogOut size={14} /> Cerrar sesión
        </button>
      </div>
    </aside>
  );

  return (
    <div className="flex h-screen overflow-hidden">
      {!colapsado && (
        <div className="hidden md:flex shrink-0 relative">
          {sidebar}
          <button
            onClick={alternarSidebar}
            className="hidden md:flex absolute top-3 -right-3 z-30 items-center justify-center w-6 h-6 rounded-full bg-blue-900 text-white border border-blue-700 hover:bg-blue-800 shadow transition"
            aria-label="Ocultar panel lateral" title="Ocultar panel lateral"
          >
            <ChevronLeft size={14} />
          </button>
        </div>
      )}

      {colapsado && (
        <button
          onClick={alternarSidebar}
          className="hidden md:flex fixed top-3 left-3 z-30 items-center justify-center w-8 h-8 rounded-lg bg-blue-900 text-white hover:bg-blue-800 shadow-lg transition"
          aria-label="Mostrar panel lateral" title="Mostrar panel lateral"
        >
          <ChevronRight size={18} />
        </button>
      )}

      {mobileOpen && (
        <div className="fixed inset-0 z-40 flex md:hidden">
          <div className="fixed inset-0 bg-black/50" onClick={() => setMobileOpen(false)} aria-hidden="true" />
          <div className="relative z-50 flex">{sidebar}</div>
        </div>
      )}

      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <header className="flex md:hidden items-center justify-between px-4 py-3 bg-blue-900 text-white shrink-0">
          <div className="flex items-center gap-2">
            <ClipboardList size={18} className="text-blue-200" />
            <span className="text-sm font-bold">Items KOS</span>
          </div>
          <button onClick={() => setMobileOpen((v) => !v)} className="p-1.5 rounded-lg hover:bg-blue-800 transition"
                  aria-label="Abrir menú">
            {mobileOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </header>

        <main className="flex-1 overflow-auto bg-gray-50">{children}</main>
      </div>

      {cambiarClave && <CambiarClave onClose={() => setCambiarClave(false)} />}
    </div>
  );
}

function CambiarClave({ onClose }) {
  const [f, setF] = useState({ actual: "", nueva: "", repetir: "" });
  const [estado, setEstado] = useState(null);   // {ok, mensaje} | "guardando"
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  const distintas = f.repetir && f.nueva !== f.repetir;

  const guardarClave = async () => {
    setEstado("guardando");
    try {
      await pedir("/api/auth/clave", { method: "POST", json: { actual: f.actual, nueva: f.nueva } });
      setEstado({ ok: true, mensaje: "Contraseña actualizada. Las sesiones abiertas en otros equipos se cerraron." });
      setF({ actual: "", nueva: "", repetir: "" });
    } catch (e) {
      setEstado({ ok: false, mensaje: e.message });
    }
  };

  return (
    <Modal title="Cambiar contraseña" onClose={onClose}>
      <div className="space-y-4">
        <Field label="Contraseña actual">
          <input type="password" className={INPUT} value={f.actual} onChange={set("actual")} autoComplete="current-password" />
        </Field>
        <Field label="Nueva contraseña" hint="Mínimo 8 caracteres.">
          <input type="password" className={INPUT} value={f.nueva} onChange={set("nueva")} autoComplete="new-password" />
        </Field>
        <Field label="Repite la nueva">
          <input type="password" className={INPUT} value={f.repetir} onChange={set("repetir")} autoComplete="new-password" />
        </Field>
        {distintas && <p className="text-rose-500 text-xs">No coinciden.</p>}
        {estado?.mensaje && <Aviso tono={estado.ok ? "ok" : "error"}>{estado.mensaje}</Aviso>}
        <button
          onClick={guardarClave}
          disabled={!f.actual || f.nueva.length < 8 || f.nueva !== f.repetir || estado === "guardando"}
          className={`${BTN_PRIMARIO} w-full py-2.5`}
        >
          {estado === "guardando" ? "Guardando..." : "Cambiar contraseña"}
        </button>
      </div>
    </Modal>
  );
}
