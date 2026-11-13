import { useEffect, useState } from "react";
import { AlertCircle, Lock, Save, X } from "lucide-react";
import Combo from "./Combo.jsx";
import { pedir } from "./api";
import { Aviso, BTN_PRIMARIO, BTN_SECUNDARIO, Field, INPUT, SELECT } from "./components/ui.jsx";

/** Lista de opciones activas, con el valor que ya tiene la solicitud aunque lo hayan desactivado. */
const conActual = (lista, actual) => (actual && !lista.includes(actual) ? [actual, ...lista] : lista);

/**
 * Edicion de una solicitud (permiso Editar de "Nueva solicitud"). Mismos campos
 * que el formulario de alta mas el montaje. Si el item ya esta creado en Siesa,
 * item base, marca y calibre quedan fijos: cambiarlos seria otro item.
 */
export default function EditarSolicitud({ s, alGuardar, alCancelar }) {
  const fijo = s.estado === "Creado";
  const [form, setForm] = useState(() => ({
    item_base_referencia: s.referencia,
    marca_id: s.marca_id,
    marca_nueva_texto: s.marca_nueva_texto || "",
    cliente_id: s.cliente_id,
    cliente_texto: s.cliente_texto || "",
    calibre_id: s.calibre_id,
    tipo_material: s.tipo_material || "",
    cantidad: String(s.cantidad ?? ""),
    vendedor_id: String(s.vendedor_id ?? ""),
    tipo_solicitud: s.tipo_solicitud || "",
    tipo_impresion: s.tipo_impresion || "",
    montaje: s.montaje != null ? String(s.montaje) : "",
    observaciones: s.observaciones || "",
  }));
  const [opciones, setOpciones] = useState({ materiales: [], tipos_solicitud: [], tipos_impresion: [] });
  const [calibres, setCalibres] = useState([]);
  const [vendedores, setVendedores] = useState([]);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    pedir("/api/solicitudes/opciones").then(setOpciones).catch(() => {});
    pedir("/api/catalogos/calibres").then(setCalibres).catch(() => {});
    pedir("/api/catalogos/comerciales").then(setVendedores).catch(() => {});
  }, []);

  const set = (campo) => (v) => setForm((f) => ({ ...f, [campo]: v }));
  const vendedoresConActual = vendedores.some((v) => String(v.id) === String(s.vendedor_id)) || !s.vendedor_id
    ? vendedores : [{ id: s.vendedor_id, nombre: `${s.vendedor_nombre} (actual)` }, ...vendedores];

  const listo = form.item_base_referencia && form.marca_id && form.calibre_id
    && (form.cliente_id || form.cliente_texto.trim()) && form.tipo_material
    && Number(form.cantidad) > 0 && form.vendedor_id;

  const guardar = async (e) => {
    e.preventDefault();
    setGuardando(true); setError("");
    try {
      await pedir(`/api/solicitudes/${s.id}`, {
        method: "PUT",
        json: {
          ...form,
          cantidad: Number(form.cantidad),
          vendedor_id: Number(form.vendedor_id),
          montaje: form.montaje ? Number(form.montaje) : null,
          tipo_solicitud: form.tipo_solicitud || null,
          tipo_impresion: form.tipo_impresion || null,
        },
      });
      alGuardar();
    } catch (err) {
      setError(err.message);
    } finally {
      setGuardando(false);
    }
  };

  const Fijo = ({ label, children }) => (
    <Field label={label}>
      <div className="flex items-center gap-2 border border-slate-200 bg-slate-50 rounded-xl px-3 py-2.5 text-sm text-slate-500">
        <Lock size={14} className="shrink-0 text-slate-400" /> <span className="truncate">{children}</span>
      </div>
    </Field>
  );

  return (
    <form onSubmit={guardar} className="space-y-4">
      {fijo && (
        <Aviso tono="info" icon={Lock}>
          El item ya está creado en Siesa: item base, marca y calibre no se pueden cambiar.
        </Aviso>
      )}
      {s.en_cargue ? (
        <Aviso tono="alerta" icon={AlertCircle}>Está en un cargue en proceso: espera a que termine para editarla.</Aviso>
      ) : null}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="sm:col-span-2">
          {fijo ? <Fijo label="Item base">{s.item_base || s.referencia}</Fijo> : (
            <Combo etiqueta="Item base (catálogo de Siesa)" endpoint="/api/catalogos/items-base"
                   campoValor="referencia" campoTexto="descripcion" textoInicial={s.item_base}
                   valor={form.item_base_referencia} onChange={set("item_base_referencia")} />
          )}
        </div>
        <div>
          {fijo ? <Fijo label="Marca">{s.marca}</Fijo> : (
            <>
              <Combo etiqueta="Marca (Ext1)" endpoint="/api/catalogos/marcas"
                     campoValor="id" campoTexto="descripcion" textoInicial={s.marca_id ? s.marca : null}
                     valor={form.marca_id} onChange={set("marca_id")}
                     placeholder="Busca por nombre o código (K1234)…" />
              {!s.marca_id && s.marca_nueva_texto && !form.marca_id && (
                <p className="text-xs text-amber-700 mt-1">
                  Pidió la marca nueva «{s.marca_nueva_texto}»: elige la marca del catálogo para desbloquearla.
                </p>
              )}
            </>
          )}
        </div>
        <div>
          <Combo etiqueta="Cliente" endpoint="/api/catalogos/clientes"
                 campoValor="id" campoTexto="nombre" textoInicial={s.cliente_id ? s.cliente : null}
                 valor={form.cliente_id} onChange={set("cliente_id")}
                 permitirNuevo textoNuevo={form.cliente_texto} onTextoNuevo={set("cliente_texto")} />
          {!form.cliente_id && form.cliente_texto && (
            <p className="text-xs text-slate-500 mt-1">Cliente sin código en Siesa: «{form.cliente_texto}»</p>
          )}
        </div>

        {fijo ? <Fijo label="Calibre">{s.calibre || s.calibre_id}</Fijo> : (
          <Field label="Calibre (Ext2)">
            <select className={SELECT} value={form.calibre_id || ""} onChange={(e) => set("calibre_id")(e.target.value || null)}>
              <option value="">—</option>
              {calibres.map((c) => <option key={c.id} value={c.id}>{c.descripcion}</option>)}
            </select>
          </Field>
        )}
        <Field label="Tipo de material">
          <select className={SELECT} value={form.tipo_material} onChange={(e) => set("tipo_material")(e.target.value)}>
            <option value="">—</option>
            {conActual(opciones.materiales, s.tipo_material).map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </Field>
        <Field label="Cantidad">
          <input type="number" min="1" className={`${INPUT} font-mono`} value={form.cantidad}
                 onChange={(e) => set("cantidad")(e.target.value)} />
        </Field>
        <Field label="Vendedor">
          <select className={SELECT} value={form.vendedor_id} onChange={(e) => set("vendedor_id")(e.target.value)}>
            <option value="">—</option>
            {vendedoresConActual.map((v) => <option key={v.id} value={v.id}>{v.nombre}</option>)}
          </select>
        </Field>
        <Field label="Tipo de solicitud">
          <select className={SELECT} value={form.tipo_solicitud} onChange={(e) => set("tipo_solicitud")(e.target.value)}>
            <option value="">—</option>
            {conActual(opciones.tipos_solicitud, s.tipo_solicitud).map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </Field>
        <Field label="T. Impresión">
          <select className={SELECT} value={form.tipo_impresion} onChange={(e) => set("tipo_impresion")(e.target.value)}>
            <option value="">—</option>
            {conActual(opciones.tipos_impresion ?? [], s.tipo_impresion).map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </Field>
        <Field label="Montaje" hint="Opcional. Normalmente lo define el planeador.">
          <input type="text" inputMode="numeric" maxLength={4} className={`${INPUT} font-mono`} value={form.montaje}
                 onChange={(e) => set("montaje")(e.target.value.replace(/\D/g, ""))} />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Observaciones">
            <textarea rows="3" className={`${INPUT} resize-y`} value={form.observaciones}
                      onChange={(e) => set("observaciones")(e.target.value)} />
          </Field>
        </div>
      </div>

      {error && <Aviso tono="error" icon={AlertCircle}>No se guardó: {error}</Aviso>}

      <div className="flex items-center justify-end gap-2 pt-1">
        <button type="button" className={BTN_SECUNDARIO} onClick={alCancelar} disabled={guardando}>
          <X size={15} /> Cancelar
        </button>
        <button type="submit" className={BTN_PRIMARIO} disabled={!listo || guardando || !!s.en_cargue}>
          <Save size={15} /> {guardando ? "Guardando…" : "Guardar cambios"}
        </button>
      </div>
    </form>
  );
}
