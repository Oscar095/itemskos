import { useEffect, useState } from "react";
import {
  AlertCircle, AlertTriangle, CheckCircle2, ClipboardList, FilePlus2, Loader2, Paperclip, Send, XCircle,
} from "lucide-react";
import Combo from "./Combo.jsx";
import { pedir } from "./api";
import { useAuthStore, usePermiso } from "./store/auth";
import { Aviso, BTN_PRIMARIO, CARD, Field, INPUT, PageBody, PageHero, SELECT } from "./components/ui";

const VACIO = {
  item_base_referencia: null,
  marca_id: null,
  marca_nueva_texto: "",
  cliente_id: null,
  cliente_texto: "",
  calibre_id: null,
  tipo_material: "",
  cantidad: "",
  tipo_solicitud: "",
  vendedor_id: "",
  observaciones: "",
};

const SELECT_FIJO = `${SELECT} disabled:bg-slate-50 disabled:text-slate-500 disabled:cursor-not-allowed`;

export default function Formulario({ alCrear }) {
  const user = useAuthStore((s) => s.user);
  const puedeCrearMarca = usePermiso("marcas").crear;
  // Un usuario con cargo Comercial solo crea solicitudes a su propio nombre
  // (el backend aplica la misma regla).
  const vendedorFijo = user?.cargo === "Comercial" && user?.vendedor_id ? String(user.vendedor_id) : "";
  const vacio = () => ({ ...VACIO, vendedor_id: vendedorFijo });

  const [form, setForm] = useState(vacio);
  const [opciones, setOpciones] = useState({ materiales: [], tipos_solicitud: [] });
  const [calibres, setCalibres] = useState([]);
  const [vendedores, setVendedores] = useState([]);
  const [duplicado, setDuplicado] = useState(null);
  const [archivos, setArchivos] = useState([]);
  const [claveArchivos, setClaveArchivos] = useState(0);
  const [resultado, setResultado] = useState(null);
  const [enviando, setEnviando] = useState(false);

  const set = (campo) => (v) => setForm((f) => ({ ...f, [campo]: v }));

  // Si la sesion llega o cambia despues de montar, el vendedor fijo manda.
  useEffect(() => {
    if (vendedorFijo) setForm((f) => ({ ...f, vendedor_id: vendedorFijo }));
  }, [vendedorFijo]);

  // Alta de marcas en Ext1. Antes una marca inexistente dejaba la solicitud
  // Bloqueada hasta que alguien la creara a mano en Siesa; ahora se crea aqui
  // con el siguiente consecutivo y la solicitud nace con su codigo real.
  // El backend toma el usuario de la sesion.
  const crearMarca = {
    vistaPrevia: (texto) =>
      pedir(`/api/catalogos/marcas/vista-previa?descripcion=${encodeURIComponent(texto)}`),
    crear: (texto) =>
      pedir("/api/catalogos/marcas", { method: "POST", json: { descripcion: texto } }),
  };

  useEffect(() => {
    pedir("/api/solicitudes/opciones").then(setOpciones).catch(() => {});
    pedir("/api/catalogos/calibres").then(setCalibres).catch(() => {});
    // Solo usuarios activos con cargo Comercial: el historico de vendedores no se ofrece.
    pedir("/api/catalogos/comerciales").then(setVendedores).catch(() => {});
    // El cargo y el vendedor de la sesion pudieron cambiar desde Usuarios: se refrescan.
    useAuthStore.getState().cargar();
  }, []);

  // Aviso de duplicado apenas estan las 3 claves. El backend revisa Siesa y las
  // demas solicitudes: la misma regla que aplica al guardar.
  useEffect(() => {
    const { item_base_referencia, marca_id, calibre_id } = form;
    if (!item_base_referencia || !marca_id || !calibre_id) {
      setDuplicado(null);
      return undefined;
    }
    // Una respuesta lenta de la combinacion anterior no debe pisar la actual.
    let vigente = true;
    setDuplicado({ verificando: true });
    const p = new URLSearchParams({ item_base_referencia, marca_id, calibre_id });
    pedir(`/api/solicitudes/verificar?${p}`)
      .then((r) => { if (vigente) setDuplicado(r); })
      .catch(() => {
        if (vigente) setDuplicado({ existe: false, error: true,
          mensaje: "No se pudo verificar si ese item ya existe; se revisará al guardar." });
      });
    return () => { vigente = false; };
  }, [form.item_base_referencia, form.marca_id, form.calibre_id]);

  const enviar = async (e) => {
    e.preventDefault();
    setEnviando(true);
    setResultado(null);
    try {
      const j = await pedir("/api/solicitudes", {
        method: "POST",
        json: {
          ...form,
          cantidad: Number(form.cantidad),
          vendedor_id: Number(form.vendedor_id),
        },
      });

      // Los adjuntos van despues: necesitan el id de la solicitud ya creada.
      // Quien los sube lo toma el backend de la sesion.
      let subidos = 0;
      for (const f of archivos) {
        const fd = new FormData();
        fd.append("archivo", f);
        try {
          await pedir(`/api/solicitudes/${j.id}/adjuntos`, { method: "POST", body: fd });
          subidos++;
        } catch { /* se cuenta como fallido y se avisa abajo */ }
      }

      setResultado({ ok: true, ...j, adjuntos: subidos,
                     adjuntosFallidos: archivos.length - subidos });
      // Solo se salta al seguimiento si no hay nada que avisar: un adjunto
      // perdido o un motivo de bloqueo tienen que verse aqui.
      const limpio = !j.motivo_bloqueo && subidos === archivos.length;
      setForm(vacio());
      setArchivos([]);
      setClaveArchivos((k) => k + 1);
      setDuplicado(null);
      alCrear?.(limpio);
    } catch (err) {
      setResultado({ ok: false, mensaje: err.message });
      // 409 = duplicado (alguien la pidio entre el aviso y el guardado): el aviso se pone al dia.
      if (err.status === 409) setDuplicado({ existe: true, mensaje: err.message });
    } finally {
      setEnviando(false);
    }
  };

  const listo =
    form.item_base_referencia &&
    form.marca_id &&
    form.calibre_id &&
    !duplicado?.existe && !duplicado?.verificando &&
    (form.cliente_id || form.cliente_texto) &&
    form.tipo_material && form.cantidad && form.vendedor_id;

  const conPendientes = resultado?.ok && (resultado.motivo_bloqueo || resultado.adjuntosFallidos);

  return (
    <div className="min-h-screen bg-slate-50">
      <PageHero
        icon={FilePlus2} eyebrow="Comercial" title="Nueva solicitud de item"
        subtitle="Item base, marca y cliente salen del catálogo de Siesa"
      />

      <PageBody>
        <form onSubmit={enviar} className={`${CARD} max-w-5xl`}>
          <div className="flex items-center gap-2 px-6 py-4 border-b border-slate-100">
            <ClipboardList size={16} className="text-blue-600" />
            <h2 className="font-semibold text-slate-800">Datos de la solicitud</h2>
          </div>

          <div className="p-6 space-y-5">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
              <div className="col-span-full">
                <Combo
                  etiqueta="Item base (catálogo de Siesa)"
                  endpoint="/api/catalogos/items-base"
                  campoValor="referencia" campoTexto="descripcion"
                  valor={form.item_base_referencia} onChange={set("item_base_referencia")}
                  placeholder="CONT 7 OZ, VASO KX 9OZ…"
                />
              </div>

              <div className="col-span-full lg:col-span-2">
                <Combo
                  etiqueta="Marca (Ext1)"
                  endpoint="/api/catalogos/marcas"
                  campoValor="id" campoTexto="descripcion"
                  valor={form.marca_id} onChange={set("marca_id")}
                  placeholder="Busca por nombre o código (K1234)…"
                  crear={puedeCrearMarca ? crearMarca : null}
                  avisoSinAlta="¿No está la marca? No tienes permiso para crear marcas en Siesa: pídele el alta a alguien que lo tenga."
                />
              </div>

              <div className="col-span-full lg:col-span-2">
                <Combo
                  etiqueta="Cliente"
                  endpoint="/api/catalogos/clientes"
                  campoValor="id" campoTexto="nombre"
                  valor={form.cliente_id} onChange={set("cliente_id")}
                  permitirNuevo textoNuevo={form.cliente_texto}
                  onTextoNuevo={set("cliente_texto")}
                />
              </div>

              <Field label="Calibre (Ext2)">
                <select className={SELECT} value={form.calibre_id || ""}
                        onChange={(e) => set("calibre_id")(e.target.value || null)}>
                  <option value="">—</option>
                  {calibres.map((c) => <option key={c.id} value={c.id}>{c.descripcion}</option>)}
                </select>
              </Field>

              <Field label="Tipo de material">
                <select className={SELECT} value={form.tipo_material}
                        onChange={(e) => set("tipo_material")(e.target.value)}>
                  <option value="">—</option>
                  {opciones.materiales.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              </Field>

              <Field label="Cantidad">
                <input type="number" min="1" className={`${INPUT} font-mono`} value={form.cantidad}
                       onChange={(e) => set("cantidad")(e.target.value)} />
              </Field>

              <Field label="Vendedor"
                     hint={vendedorFijo ? "Tu usuario es Comercial: la solicitud queda a tu nombre."
                       : !vendedores.length ? "No hay usuarios comerciales activos: créalos en Usuarios con cargo Comercial."
                       : null}>
                {vendedorFijo ? (
                  <select className={SELECT_FIJO} value={vendedorFijo} disabled>
                    <option value={vendedorFijo}>{user.nombre}</option>
                  </select>
                ) : (
                  <select className={SELECT} value={form.vendedor_id}
                          onChange={(e) => set("vendedor_id")(e.target.value)}>
                    <option value="">—</option>
                    {vendedores.map((v) => <option key={v.id} value={v.id}>{v.nombre}</option>)}
                  </select>
                )}
              </Field>

              {/* Justo debajo de item base, marca y calibre: al fondo del formulario no se veia. */}
              {duplicado && !duplicado.verificando && (
                <div className="col-span-full">
                  <Aviso tono={duplicado.existe ? "alerta" : duplicado.error ? "info" : "ok"}
                         icon={duplicado.existe ? AlertTriangle : duplicado.error ? AlertCircle : CheckCircle2}>
                    {duplicado.mensaje}
                  </Aviso>
                </div>
              )}

              <div className="col-span-full">
                <Field label="Tipo de solicitud">
                  <select className={SELECT} value={form.tipo_solicitud}
                          onChange={(e) => set("tipo_solicitud")(e.target.value)}>
                    <option value="">—</option>
                    {opciones.tipos_solicitud.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </Field>
              </div>

              <div className="col-span-full">
                <Field label="Observaciones">
                  <textarea rows="3" className={`${INPUT} resize-y`} value={form.observaciones}
                            placeholder="Notas para diseño, producción, etc."
                            onChange={(e) => set("observaciones")(e.target.value)} />
                </Field>
              </div>

              <div className="col-span-full">
                <Field label="Adjuntos (artes, fichas, fotos…)">
                  <div className="border border-dashed border-slate-200 rounded-xl px-3 py-3 bg-slate-50/60">
                    <input
                      key={claveArchivos}
                      type="file" multiple
                      onChange={(e) => setArchivos([...e.target.files])}
                      className="block w-full text-sm text-slate-500 file:mr-3 file:py-2 file:px-4 file:rounded-xl file:border-0 file:text-sm file:font-medium file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 file:cursor-pointer cursor-pointer"
                    />
                    {archivos.length > 0 && (
                      <div className="mt-3 space-y-1.5">
                        <p className="text-xs text-slate-500">
                          <span className="font-semibold text-slate-700">{archivos.length}</span> archivo(s):
                        </p>
                        <div className="flex flex-wrap gap-1.5">
                          {archivos.map((f, i) => (
                            <span key={`${f.name}-${i}`}
                                  className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-white border border-slate-200 rounded-lg text-xs text-slate-600 max-w-full">
                              <Paperclip size={12} className="text-slate-400 shrink-0" />
                              <span className="truncate">{f.name}</span>
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </Field>
              </div>
            </div>

            {resultado && (
              <Aviso
                tono={!resultado.ok ? "error" : conPendientes ? "alerta" : "ok"}
                icon={!resultado.ok ? XCircle : conPendientes ? AlertCircle : CheckCircle2}
              >
                {resultado.ok
                  ? `Solicitud #${resultado.id} guardada (${resultado.estado})${
                      resultado.adjuntos ? `, ${resultado.adjuntos} adjunto(s)` : ""
                    }. ${resultado.motivo_bloqueo || ""}${
                      resultado.adjuntosFallidos ? ` ${resultado.adjuntosFallidos} adjunto(s) no se subieron: agrégalos desde la ficha de la solicitud.` : ""
                    }`
                  : `No se pudo guardar: ${resultado.mensaje}`}
              </Aviso>
            )}
          </div>

          <div className="flex items-center gap-4 flex-wrap px-6 py-4 border-t border-slate-100 bg-slate-50/60 rounded-b-2xl">
            <button type="submit" className={`${BTN_PRIMARIO} py-2.5`} disabled={!listo || enviando}>
              {enviando
                ? <><Loader2 size={16} className="animate-spin" /> Guardando…</>
                : <><Send size={16} /> Crear solicitud</>}
            </button>
            {!listo && (
              <span className="text-xs text-slate-400">
                {duplicado?.existe
                  ? "Ese item ya está creado o solicitado: no se puede pedir de nuevo."
                  : duplicado?.verificando
                    ? "Verificando si el item ya existe…"
                    : "Faltan campos: item base, marca, calibre, cliente, material, cantidad y vendedor."}
              </span>
            )}
          </div>
        </form>
      </PageBody>
    </div>
  );
}
