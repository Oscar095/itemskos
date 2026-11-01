import { createPortal } from "react-dom";
import { Loader2, X } from "lucide-react";

// Piezas visuales de produccionweb (Usuarios.tsx, Orders.tsx, Loading.tsx),
// para que esta app se vea y se use igual que las demas de KOS.

export const INPUT =
  "w-full border border-slate-200 rounded-xl px-3 py-2.5 text-sm text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 shadow-sm";
export const SELECT = `${INPUT} bg-white`;
export const BTN_PRIMARIO =
  "flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-xl shadow-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
export const BTN_SECUNDARIO =
  "flex items-center justify-center gap-2 px-4 py-2 bg-white border border-slate-200 hover:bg-slate-50 text-slate-600 text-sm font-medium rounded-xl shadow-sm transition-colors disabled:opacity-50";
export const BTN_HERO =
  "flex items-center gap-2 px-4 py-2 bg-white/10 hover:bg-white/20 text-white text-sm font-medium rounded-xl border border-white/20 transition-all backdrop-blur-sm";
export const CARD = "bg-white rounded-2xl border border-slate-100 shadow-sm";
export const TH = "px-5 py-3.5 text-left font-semibold text-slate-600 text-xs uppercase tracking-wide";

// Estados de una solicitud y de un cargue, con los colores de ESTADO_PILL.
export const ESTADO_PILL = {
  Creado: "bg-emerald-100 text-emerald-700",
  Exitoso: "bg-emerald-100 text-emerald-700",
  Completo: "bg-emerald-100 text-emerald-700",
  Pendiente: "bg-amber-100 text-amber-700",
  "Por crear": "bg-amber-100 text-amber-700",
  "En cola": "bg-amber-100 text-amber-700",
  "En proceso": "bg-blue-100 text-blue-700",
  "En cargue": "bg-blue-100 text-blue-700",
  Bloqueado: "bg-rose-100 text-rose-700",
  Error: "bg-rose-100 text-rose-700",
  "Con error": "bg-rose-100 text-rose-700",
  "Faltan parámetros": "bg-rose-100 text-rose-700",
  Revisar: "bg-rose-100 text-rose-700",
};

export function Pill({ children, estado }) {
  return (
    <span className={`inline-flex px-3 py-1 rounded-full text-xs font-bold whitespace-nowrap ${ESTADO_PILL[estado ?? children] || "bg-slate-100 text-slate-500"}`}>
      {children}
    </span>
  );
}

/** Encabezado azul con degradado que abre cada pagina. */
export function PageHero({ icon: Icon, eyebrow, title, subtitle, actions, children }) {
  return (
    <div className="bg-gradient-to-br from-slate-800 via-blue-900 to-blue-800 px-6 pt-6 pb-10">
      <div className="max-w-full mx-auto">
        <div className={`flex items-start justify-between flex-wrap gap-4 ${children ? "mb-6" : ""}`}>
          <div>
            <div className="flex items-center gap-2 mb-1">
              {Icon && <Icon size={20} className="text-blue-300" />}
              <span className="text-blue-300 text-sm font-medium uppercase tracking-widest">{eyebrow}</span>
            </div>
            <h1 className="text-3xl font-bold text-white">{title}</h1>
            {subtitle && <p className="text-blue-200 text-sm mt-1">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center gap-2 flex-wrap">{actions}</div>}
        </div>
        {children}
      </div>
    </div>
  );
}

/** Pestanas de vidrio dentro del PageHero. tabs: [{key, label, icon?}] */
export function HeroTabs({ tabs, value, onChange }) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {tabs.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={`flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-xl border transition-all backdrop-blur-sm
            ${value === t.key
              ? "bg-white text-blue-900 border-white shadow-sm"
              : "bg-white/10 text-white border-white/20 hover:bg-white/20"}`}
        >
          {t.icon}
          {t.label}
        </button>
      ))}
    </div>
  );
}

/** Contenedor del cuerpo, montado 20px sobre el hero (como en produccionweb). */
export function PageBody({ children }) {
  return <div className="px-6 -mt-5 pb-10 max-w-full mx-auto space-y-6">{children}</div>;
}

export function Field({ label, children, hint }) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-semibold text-slate-500 uppercase tracking-wide">{label}</label>
      {children}
      {hint && <p className="text-xs text-slate-400">{hint}</p>}
    </div>
  );
}

export function Modal({ title, onClose, children, ancho = "max-w-lg" }) {
  // En un portal sobre <body>: dentro de un contenedor space-y-* heredaba un
  // margin-top y quedaba una franja arriba sin el fondo oscuro.
  return createPortal(
    <div className="fixed inset-0 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className={`bg-white rounded-2xl shadow-xl w-full ${ancho} max-h-[90vh] flex flex-col border border-slate-100`}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 shrink-0">
          <h3 className="font-semibold text-slate-800">{title}</h3>
          <button onClick={onClose} aria-label="Cerrar"
                  className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors">
            <X size={18} />
          </button>
        </div>
        <div className="p-6 overflow-y-auto">{children}</div>
      </div>
    </div>,
    document.body,
  );
}

const TAMANOS = {
  sm: { icon: "w-6 h-6", text: "text-sm", gap: "gap-2", pad: "py-4" },
  md: { icon: "w-10 h-10", text: "text-lg", gap: "gap-3", pad: "py-10" },
  lg: { icon: "w-16 h-16", text: "text-2xl", gap: "gap-4", pad: "py-16" },
};

export function Loading({ label = "Cargando...", size = "lg", fullPanel = true, className = "" }) {
  const s = TAMANOS[size];
  const caja = fullPanel
    ? `w-full flex flex-col items-center justify-center ${s.pad} ${s.gap} bg-white rounded-2xl border border-gray-100 shadow-sm`
    : `w-full flex flex-col items-center justify-center ${s.pad} ${s.gap}`;
  return (
    <div className={`${caja} ${className}`} role="status" aria-live="polite">
      <div className="relative flex items-center justify-center">
        <span className={`absolute inline-flex rounded-full bg-blue-400/30 animate-ping ${s.icon}`} />
        <Loader2 className={`relative text-blue-600 animate-spin ${s.icon}`} strokeWidth={2.5} />
      </div>
      <div className={`font-semibold text-gray-700 tracking-wide ${s.text}`}>
        <span className="inline-block animate-pulse">{label}</span>
      </div>
    </div>
  );
}

export function Vacio({ icon: Icon, titulo, sub }) {
  return (
    <div className={`${CARD} p-12 text-center`}>
      {Icon && <Icon size={40} className="mx-auto text-slate-200 mb-3" />}
      <p className="text-slate-400 font-medium">{titulo}</p>
      {sub && <p className="text-slate-300 text-sm mt-1">{sub}</p>}
    </div>
  );
}

/** Aviso en linea: tono "ok" | "error" | "alerta" | "info". */
export function Aviso({ tono = "info", icon: Icon, children, className = "" }) {
  const t = {
    ok: "bg-emerald-50 border-emerald-200 text-emerald-700",
    error: "bg-rose-50 border-rose-200 text-rose-700",
    alerta: "bg-amber-50 border-amber-200 text-amber-800",
    info: "bg-blue-50 border-blue-200 text-blue-800",
  }[tono];
  return (
    <div className={`border rounded-xl px-4 py-2.5 text-sm flex items-start gap-2 ${t} ${className}`}>
      {Icon && <Icon size={15} className="flex-shrink-0 mt-0.5" />}
      <div className="min-w-0">{children}</div>
    </div>
  );
}

export function initialsOf(name) {
  const parts = (name || "").trim().split(/\s+/);
  if (!parts.length || !parts[0]) return "?";
  if (parts.length === 1) return parts[0].charAt(0).toUpperCase();
  return (parts[0].charAt(0) + parts[parts.length - 1].charAt(0)).toUpperCase();
}

/**
 * La base guarda UTC sin zona ("2026-11-01T01:12:43"): sin la Z el navegador
 * lo toma como hora local y muestra 5 horas de mas. Se interpreta como UTC y
 * se muestra en la hora de quien mira.
 */
export function fechaHora(f, opciones) {
  if (!f) return "—";
  const iso = typeof f === "string" && !/[zZ]|[+-]\d\d:?\d\d$/.test(f) ? `${f}Z` : f;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("es-CO", opciones);
}
