import { Fragment, useEffect, useRef, useState } from "react";
import { AtSign, Pencil, Send, Trash2, X } from "lucide-react";
import { pedir } from "./api";
import { useAuthStore } from "./store/auth";
import { Aviso, BTN_PRIMARIO, fechaHora, initialsOf } from "./components/ui.jsx";

// "Diana" encuentra a "Diana Nieto" y "diana" o "DIÁNA" tambien.
const norm = (t) => (t || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
const escapar = (t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
// "@dia" justo antes del cursor (al inicio o despues de un espacio).
const ARROBA = /(^|\s)@([^\s@]{0,30})$/;
const MAX = 2000;

/** Texto del comentario con las personas etiquetadas resaltadas. */
function TextoConMenciones({ texto, menciones, yo }) {
  if (!menciones?.length) return texto;
  const nombres = [...menciones].sort((a, b) => b.nombre.length - a.nombre.length);
  const re = new RegExp(`@(${nombres.map((m) => escapar(m.nombre)).join("|")})`, "g");
  const partes = texto.split(re);
  return partes.map((p, i) => {
    if (i % 2 === 0) return <Fragment key={i}>{p}</Fragment>;
    const m = nombres.find((x) => x.nombre === p);
    return (
      <span key={i} className={`font-semibold rounded px-0.5 ${m?.id === yo ? "bg-amber-100 text-amber-800" : "text-blue-700"}`}>
        @{p}
      </span>
    );
  });
}

/**
 * Conversacion de la solicitud. Con @ se etiqueta a una persona: el comentario
 * queda dirigido a ella (se ve "Para: …") y le llega un correo.
 * Las ediciones y la eliminacion las deja la plataforma como historial.
 */
export default function Comentarios({ solicitudId, comentarios, alCambiar }) {
  const yo = useAuthStore((st) => st.user?.id);
  const [gente, setGente] = useState([]);
  const [texto, setTexto] = useState("");
  const [etiquetados, setEtiquetados] = useState([]);   // [{id, nombre}]
  const [busqueda, setBusqueda] = useState(null);       // texto despues de @, o null si no hay lista abierta
  const [idx, setIdx] = useState(0);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState("");
  const area = useRef(null);
  const fin = useRef(null);

  useEffect(() => {
    pedir("/api/solicitudes/mencionables").then(setGente).catch(() => {});
  }, []);

  const sugerencias = busqueda === null ? [] : gente
    .filter((u) => !etiquetados.some((e) => e.id === u.id))
    .filter((u) => !busqueda || norm(u.nombre).split(" ").some((p) => p.startsWith(norm(busqueda)))
                   || norm(u.username).startsWith(norm(busqueda)))
    .slice(0, 8);

  const detectar = (valor, cursor) => {
    const m = valor.slice(0, cursor).match(ARROBA);
    setBusqueda(m ? m[2] : null);
    setIdx(0);
  };

  const etiquetar = (u) => {
    const el = area.current;
    const cursor = el?.selectionStart ?? texto.length;
    const antes = texto.slice(0, cursor).replace(ARROBA, (_, esp) => `${esp}@${u.nombre} `);
    const nuevo = antes + texto.slice(cursor);
    setTexto(nuevo);
    setEtiquetados((e) => [...e, { id: u.id, nombre: u.nombre, tiene_correo: u.tiene_correo }]);
    setBusqueda(null);
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(antes.length, antes.length);
    });
  };

  const quitar = (u) => {
    setEtiquetados((e) => e.filter((x) => x.id !== u.id));
    setTexto((t) => t.split(`@${u.nombre}`).join(u.nombre));
  };

  // Solo cuentan los que siguen escritos en el texto (si borro "@Diana Nieto", ya no va para ella).
  const vigentes = etiquetados.filter((u) => texto.includes(`@${u.nombre}`));

  const enviar = async () => {
    if (!texto.trim() || enviando) return;
    setEnviando(true); setError("");
    try {
      await pedir(`/api/solicitudes/${solicitudId}/comentarios`, {
        method: "POST", json: { texto: texto.trim(), menciones: vigentes.map((u) => u.id) },
      });
      setTexto(""); setEtiquetados([]); setBusqueda(null);
      await alCambiar?.();
      requestAnimationFrame(() => fin.current?.scrollIntoView({ block: "nearest" }));
    } catch (e) {
      setError(`No se guardó el comentario: ${e.message}`);
    } finally {
      setEnviando(false);
    }
  };

  const teclas = (e) => {
    if (sugerencias.length) {
      if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => (i + 1) % sugerencias.length); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => (i - 1 + sugerencias.length) % sugerencias.length); return; }
      if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); etiquetar(sugerencias[idx]); return; }
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setBusqueda(null); return; }
    }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); enviar(); }
  };

  return (
    <div className="space-y-4">
      {comentarios.length === 0 ? (
        <p className="text-sm text-slate-400">Sin comentarios. Escribe el primero; con @ etiquetas a alguien.</p>
      ) : (
        <ul className="space-y-3">
          {comentarios.map((c) => {
            if (c.tipo !== "comentario") {
              const Icono = c.tipo === "eliminacion" ? Trash2 : Pencil;
              return (
                <li key={c.id} className="flex items-start gap-2 text-xs text-slate-500 px-1">
                  <Icono size={13} className="mt-0.5 shrink-0 text-slate-400" />
                  <p className="min-w-0 break-words">
                    <span className="font-semibold text-slate-600">{c.autor}</span> · {c.texto}
                    <span className="text-slate-400"> · {fechaHora(c.creado)}</span>
                  </p>
                </li>
              );
            }
            const paraMi = c.menciones.some((m) => m.id === yo);
            return (
              <li key={c.id} className={`flex gap-3 rounded-xl p-3 border ${paraMi ? "bg-amber-50/60 border-amber-200" : "bg-slate-50/70 border-slate-100"}`}>
                <span className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-blue-700 text-white text-xs font-semibold flex items-center justify-center shrink-0">
                  {initialsOf(c.autor)}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2 flex-wrap">
                    <span className="text-sm font-semibold text-slate-800">{c.autor}</span>
                    <span className="text-xs text-slate-400">{fechaHora(c.creado)}</span>
                    {paraMi && <span className="text-[11px] font-semibold text-amber-700 bg-amber-100 rounded-full px-2 py-0.5">Para ti</span>}
                  </div>
                  {c.menciones.length > 0 && (
                    <p className="text-xs text-slate-500 mt-0.5">
                      Para: <span className="font-medium text-slate-700">{c.menciones.map((m) => m.nombre).join(", ")}</span>
                    </p>
                  )}
                  <p className="text-sm text-slate-700 mt-1 whitespace-pre-wrap break-words">
                    <TextoConMenciones texto={c.texto} menciones={c.menciones} yo={yo} />
                  </p>
                </div>
              </li>
            );
          })}
          <li ref={fin} aria-hidden />
        </ul>
      )}

      <div className="space-y-2">
        {vigentes.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap text-xs">
            <span className="text-slate-500">Para:</span>
            {vigentes.map((u) => (
              <span key={u.id} title={u.tiene_correo ? "Le llega un correo" : "No tiene correo: lo verá solo en la plataforma"}
                    className="inline-flex items-center gap-1 rounded-full bg-blue-50 border border-blue-100 text-blue-700 font-medium pl-2 pr-1 py-0.5">
                {u.nombre}{!u.tiene_correo && <span className="text-slate-400 font-normal"> (sin correo)</span>}
                <button type="button" onClick={() => quitar(u)} aria-label={`Quitar a ${u.nombre}`}
                        className="p-0.5 rounded-full hover:bg-blue-100"><X size={12} /></button>
              </span>
            ))}
          </div>
        )}
        <div className="relative">
          <textarea
            ref={area} rows={3} maxLength={MAX} value={texto}
            placeholder="Escribe un comentario… usa @ para etiquetar a alguien"
            className="w-full border border-slate-200 rounded-xl px-3 py-2.5 text-sm text-slate-700 bg-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 shadow-sm resize-y"
            onChange={(e) => { setTexto(e.target.value); detectar(e.target.value, e.target.selectionStart); }}
            onClick={(e) => detectar(e.target.value, e.target.selectionStart)}
            onKeyDown={teclas}
            onBlur={() => setTimeout(() => setBusqueda(null), 150)}
          />
          {sugerencias.length > 0 && (
            <ul className="absolute z-30 left-0 right-0 top-full mt-1 max-h-60 overflow-y-auto bg-white rounded-xl shadow-lg border border-slate-100 py-1">
              {sugerencias.map((u, i) => (
                <li key={u.id}>
                  <button type="button" onMouseDown={(e) => { e.preventDefault(); etiquetar(u); }}
                          className={`w-full flex items-center justify-between gap-3 px-3 py-2 text-left transition-colors ${i === idx ? "bg-blue-50" : "hover:bg-blue-50/60"}`}>
                    <span className="flex items-center gap-2 min-w-0">
                      <AtSign size={13} className="text-blue-500 shrink-0" />
                      <span className="text-sm font-medium text-slate-700 truncate">{u.nombre}</span>
                    </span>
                    <span className="text-xs text-slate-400 shrink-0">{u.cargo || u.username}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        {error && <Aviso tono="error">{error}</Aviso>}
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs text-slate-400">Ctrl + Enter para enviar</span>
          <button type="button" className={BTN_PRIMARIO} onClick={enviar} disabled={!texto.trim() || enviando}>
            <Send size={15} /> {enviando ? "Enviando…" : "Comentar"}
          </button>
        </div>
      </div>
    </div>
  );
}

