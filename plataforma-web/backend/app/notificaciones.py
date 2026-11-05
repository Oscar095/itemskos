# -*- coding: utf-8 -*-
"""
Correos de avance de las solicitudes, enviados por un flujo de n8n.

Quién recibe qué (pedido del 2026-11-05):
  * El vendedor de la solicitud: cada cambio. El registro, cada etapa, la
    aprobación de diseño (o el bloqueo que salga de ella) y el resultado de la
    creación en Siesa.
  * Diseño: cada solicitud nueva.
  * Planeación: cuando Diseño aprueba (la solicitud queda en "Items listos a
    crear") y cada vez que un cargue crea el item.

Diseño y Planeación son los usuarios activos, con correo, del cargo del área y
con el permiso para actuar sobre el aviso (DESTINOS). Por rol no se puede: hoy
quien diseña y quien planea son Admin, y el Admin tiene todos los permisos.

Cómo viaja (outbox):
  1. registrar() arma cada correo completo (destinatarios, asunto y cuerpo) y lo
     deja en items.notificaciones como 'Pendiente'. Ese es el registro de cada
     actividad, y queda aunque n8n no responda. registrar() nunca lanza: un
     correo no puede tumbar una aprobación ni un cargue.
  2. Un hilo los manda, uno por correo, al Webhook del flujo de n8n, que envía
     con la credencial "Formularios" y responde {"ok": true}.
  3. Si n8n falla se reintenta a los 1, 5, 15 y 60 min. Lo que lleva más de 24 h
     sin salir queda 'Vencido': un aviso de hace dos días confunde más de lo que
     informa.

Solo envía el servidor que tiene N8N_WEBHOOK_URL (Azure). El PC y Azure usan la
misma base, así que lo que se registre desde un PC lo manda Azure. Las filas se
toman con UPDLOCK + READPAST: dos servidores nunca mandan el mismo correo.
"""
import html
import logging
import threading

import requests
from sqlalchemy import text

from app.config import settings
from app.db.session import consultar, engine

_log = logging.getLogger(__name__)

# Área -> (cargo, módulo, permiso) de quien recibe sus avisos.
DESTINOS = {
    "diseno": ("Diseño", "diseno", "puede_editar"),             # registra la Aprobación de Diseño
    "planeacion": ("Producción", "planeacion", "puede_crear"),  # lanza los cargues a Siesa
}

INTERVALO_SEGUNDOS = 60
REINTENTOS_MIN = (1, 5, 15, 60)        # espera tras el intento 1, 2, 3 y 4
MAX_INTENTOS = len(REINTENTOS_MIN) + 1
VIGENCIA_HORAS = 24
COLGADO_MIN = 10                       # 'Enviando' de un servidor que se apagó a mitad
TIMEOUT = (5, 30)
LOTE = 20
ENCABEZADO_TOKEN = "X-KOS-Token"       # lo valida la credencial Header Auth del Webhook

_despertar = threading.Event()
_hilo_lock = threading.Lock()
_hilo: threading.Thread | None = None


# --- a quién -----------------------------------------------------------------

def _equipo(area: str) -> list[dict]:
    cargo, modulo, permiso = DESTINOS[area]
    return consultar(f"""
        SELECT u.nombre, u.email
          FROM items.usuarios u
          JOIN items.rol_permisos p ON p.rol_id = u.rol_id AND p.modulo = :modulo
         WHERE u.activo = 1 AND u.cargo = :cargo AND p.{permiso} = 1
           AND LTRIM(RTRIM(ISNULL(u.email, ''))) <> ''
    """, modulo=modulo, cargo=cargo)


def _vendedor(s: dict) -> list[dict]:
    # El correo vigente de su usuario (si se lo corrigieron, el nuevo). El que
    # quedó guardado en la solicitud solo sirve si el vendedor no tiene usuario.
    filas = consultar("""
        SELECT TOP 1 nombre, email, activo FROM items.usuarios
         WHERE vendedor_id = :v ORDER BY activo DESC, id DESC
    """, v=s["vendedor_id"])
    if filas:
        return filas if filas[0]["activo"] and (filas[0]["email"] or "").strip() else []
    return [{"nombre": s["vendedor_nombre"], "email": s["vendedor_email"]}] if s["vendedor_email"] else []


def _sin_destinatario(destino: str) -> str:
    if destino == "vendedor":
        return "No se envió: el vendedor no tiene un usuario activo con correo."
    cargo, modulo, _ = DESTINOS[destino]
    return (f"No se envió: no hay usuarios activos con cargo {cargo}, correo y permiso en el "
            f"módulo {modulo}.")


# --- qué ---------------------------------------------------------------------

def _solicitud(solicitud_id: int) -> dict | None:
    filas = consultar("""
        SELECT s.id, s.estado, s.motivo_bloqueo, s.cantidad, s.tipo_material, s.tipo_solicitud,
               s.observaciones, s.vendedor_id, s.vendedor_nombre, s.vendedor_email, s.sku_creado,
               COALESCE(c.Nombre, s.cliente_texto)          AS cliente,
               COALESCE(m.descripcion, s.marca_nueva_texto) AS marca,
               s.item_base_referencia                        AS referencia,
               b.descripcion                                 AS item_base,
               COALESCE(cal.descripcion, s.calibre_id)       AS calibre,
               e.nombre                                      AS etapa
          FROM items.solicitudes s
          LEFT JOIN dbo.PQRS_ClientesSiesa c ON c.Id = s.cliente_id
          LEFT JOIN items.cat_marcas m       ON m.id = s.marca_id
          LEFT JOIN items.cat_items_base b   ON b.referencia = s.item_base_referencia
          LEFT JOIN items.cat_calibres cal   ON cal.id = s.calibre_id
          LEFT JOIN items.etapas e           ON e.id = s.etapa_actual_id
         WHERE s.id = :id
    """, id=solicitud_id)
    return filas[0] if filas else None


def _mensajes(evento: str, s: dict, d: dict) -> list[dict]:
    """Los correos de un evento: [{destino, asunto, titulo, parrafos, notas, enlace}]."""
    sol = f"SOL-{s['id']:05d}"
    item = " · ".join(str(x) for x in (s["item_base"] or s["referencia"], s["marca"], s["calibre"]) if x)
    actor = d.get("actor") or "La plataforma"
    obs = (d.get("observacion") or "").strip()
    nota_obs = [("info", f"Observación: {obs}")] if obs else []
    bloqueo = s["motivo_bloqueo"] if s["estado"] == "Bloqueado" else None
    ficha = f"/seguimiento?sol={s['id']}"

    def correo(destino, asunto, titulo, parrafos, notas=(), enlace=ficha):
        return {"destino": destino, "asunto": asunto, "titulo": titulo,
                "parrafos": [p for p in parrafos if p], "notas": list(notas), "enlace": enlace}

    if evento == "solicitud_creada":
        propia = actor == s["vendedor_nombre"]
        notas = ([("alerta", f"Quedó bloqueada: {bloqueo}")] if bloqueo else []) + nota_obs
        return [
            correo("vendedor", f"{sol} registrada · {item}", "Tu solicitud quedó registrada",
                   [f"La solicitud {sol} quedó registrada a tu nombre"
                    + ("." if propia else f"; la registró {actor}.")
                    + " Te escribiremos por este medio con cada avance."], notas),
            correo("diseno", f"Nueva solicitud {sol} · {item}", "Nueva solicitud de diseño",
                   [f"{actor} registró la solicitud {sol}"
                    + ("." if propia else f" a nombre de {s['vendedor_nombre']}.")], notas),
        ]

    if evento == "etapa":
        etapa = d.get("etapa") or s["etapa"]
        return [correo("vendedor", f"{sol}: {etapa} · {item}", f"Tu solicitud avanzó: {etapa}",
                       [f"{actor} registró la etapa «{etapa}» en la solicitud {sol}."], nota_obs)]

    if evento == "diseno_aprobado":
        return [
            correo("vendedor", f"{sol}: diseño aprobado · {item}", "Diseño aprobó tu solicitud",
                   [f"{actor} aprobó el diseño de {sol}. Sigue Planeación: confirma la ruta y la "
                    "bodega y crea el item en Siesa."], nota_obs),
            correo("planeacion", f"Lista para crear: {sol} · {item}", "Item listo para crear",
                   [f"{actor} aprobó el diseño de {sol}.",
                    "Ya está en Planeación → Items listos a crear: elige la ruta y la bodega y "
                    "lanza el cargue."], nota_obs, enlace="/planeacion"),
        ]

    if evento == "diseno_bloqueado":
        return [correo("vendedor", f"{sol} bloqueada · {item}", "Tu solicitud quedó bloqueada",
                       [f"{actor} registró la Aprobación de Diseño de {sol}, pero la plataforma no "
                        "autorizó la creación del item."],
                       [("alerta", d.get("mensaje") or bloqueo or "Revisa la solicitud.")])]

    if evento == "item_existente":
        sku = d.get("sku") or s["sku_creado"]
        return [correo("vendedor", f"{sol}: el item ya existe en Siesa (SKU {sku})",
                       "El item ya existe en Siesa",
                       [f"Al aprobar el diseño de {sol} se encontró que el item ya está creado en "
                        "Siesa. No hace falta crearlo."], [("ok", f"SKU en Siesa: {sku}")])]

    if evento == "item_creado":
        ya = bool(d.get("ya_existia"))
        params = d.get("param_msg") or ""
        cargue = f"El cargue #{d.get('cargue_id')}" + (f" de {d['actor']}" if d.get("actor") else "")
        return [
            correo("vendedor", f"{sol}: item {'ya existente' if ya else 'creado'} en Siesa · {item}",
                   "Tu item ya está en Siesa" if ya else "Tu item ya está creado en Siesa",
                   [d.get("mensaje")]),
            correo("planeacion", f"Item {'ya existente' if ya else 'creado'}: {sol} · {item}",
                   "Item ya existente en Siesa" if ya else "Item creado en Siesa",
                   [f"{cargue} procesó {sol}.", d.get("mensaje")],
                   [("ok", params)] if d.get("param_ok") else
                   [("alerta", f"{params} Reintenta los parámetros desde Items listos a crear.")],
                   enlace="/planeacion"),
        ]

    if evento == "creacion_fallida":
        return [correo("vendedor", f"{sol}: no se pudo crear el item · {item}",
                       "No se pudo crear tu item en Siesa",
                       [f"El cargue #{d.get('cargue_id')} no pudo crear el item de {sol}."],
                       [("alerta", d.get("mensaje") or "Siesa rechazó la creación.")])]

    raise ValueError(f"Evento desconocido: {evento}")


# --- cómo se ve --------------------------------------------------------------

TONOS = {  # fondo, borde, texto
    "info": ("#eff6ff", "#bfdbfe", "#1e3a8a"),
    "ok": ("#ecfdf5", "#a7f3d0", "#065f46"),
    "alerta": ("#fff7ed", "#fdba74", "#9a3412"),
}

PLANTILLA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titulo}</title></head>
<body style="margin:0;padding:0;background:#f1f5f9;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f1f5f9;">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;background:#ffffff;border-radius:12px;overflow:hidden;font-family:'Segoe UI',Arial,Helvetica,sans-serif;font-size:14px;line-height:1.55;color:#0f172a;">
<tr><td style="background:#1e3a8a;padding:20px 28px;">
<div style="color:#bfdbfe;font-size:11px;letter-spacing:1.5px;text-transform:uppercase;">KOS &middot; Plataforma de Items</div>
<div style="color:#ffffff;font-size:20px;font-weight:600;margin-top:4px;">{titulo}</div>
</td></tr>
<tr><td style="padding:24px 28px 8px;">{parrafos}{notas}</td></tr>
<tr><td style="padding:0 28px 24px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top:1px solid #e2e8f0;">{filas}</table>
{boton}
</td></tr>
<tr><td style="padding:14px 28px;background:#f8fafc;color:#64748b;font-size:12px;">Correo automático de la Plataforma de Items de KOS. No respondas a este mensaje.</td></tr>
</table>
</td></tr></table>
</body></html>"""


def _e(valor) -> str:
    """Escapado HTML: observaciones, clientes y marcas los escribe la gente."""
    return html.escape(str(valor), quote=True).replace("\n", "<br>")


def _ficha(s: dict) -> list[tuple[str, str]]:
    base = s["item_base"] or ""
    if s["referencia"] and s["referencia"] not in base:
        base = f"{base} ({s['referencia']})".strip()
    filas = [
        ("Solicitud", f"SOL-{s['id']:05d}"),
        ("Cliente", s["cliente"]),
        ("Item base", base),
        ("Marca", s["marca"]),
        ("Calibre", s["calibre"]),
        ("Cantidad", f"{s['cantidad']:,}".replace(",", ".") if s["cantidad"] is not None else None),
        ("Material", s["tipo_material"]),
        ("Tipo de solicitud", s["tipo_solicitud"]),
        ("Vendedor", s["vendedor_nombre"]),
        ("Estado", s["estado"]),
        ("Etapa actual", s["etapa"]),
    ]
    return [(k, str(v)) for k, v in filas if v not in (None, "")]


def _enlace(m: dict) -> str | None:
    return settings.app_url + m["enlace"] if settings.app_url else None


def _html(m: dict, s: dict) -> str:
    parrafos = "".join(f'<p style="margin:0 0 12px;">{_e(p)}</p>' for p in m["parrafos"])
    notas = "".join(
        f'<div style="margin:4px 0 16px;padding:12px 14px;background:{TONOS[t][0]};'
        f'border:1px solid {TONOS[t][1]};border-radius:8px;color:{TONOS[t][2]};">{_e(txt)}</div>'
        for t, txt in m["notas"])
    filas = "".join(
        f'<tr><td style="padding:7px 12px 7px 0;border-bottom:1px solid #f1f5f9;color:#64748b;'
        f'width:140px;vertical-align:top;">{_e(k)}</td>'
        f'<td style="padding:7px 0;border-bottom:1px solid #f1f5f9;">{_e(v)}</td></tr>'
        for k, v in _ficha(s))
    url = _enlace(m)
    boton = (f'<p style="margin:20px 0 0;"><a href="{_e(url)}" style="display:inline-block;'
             'background:#1d4ed8;color:#ffffff;text-decoration:none;padding:10px 18px;'
             'border-radius:8px;font-weight:600;">Ver en la plataforma</a></p>') if url else ""
    return PLANTILLA.format(titulo=_e(m["titulo"]), parrafos=parrafos, notas=notas,
                            filas=filas, boton=boton)


def _texto(m: dict, s: dict) -> str:
    partes = [m["titulo"], ""] + m["parrafos"] + [t for _, t in m["notas"]] + [""]
    partes += [f"{k}: {v}" for k, v in _ficha(s)]
    url = _enlace(m)
    if url:
        partes += ["", f"Ver en la plataforma: {url}"]
    partes += ["", "Correo automático de la Plataforma de Items de KOS. No respondas a este mensaje."]
    return "\n".join(partes)


# --- registro ----------------------------------------------------------------

def registrar(evento: str, solicitud_id: int, **datos) -> None:
    """
    Deja en cola los correos de un evento de la solicitud. Se llama DESPUÉS de
    confirmar el cambio en la base, para que el correo cuente lo que de verdad
    quedó. Nunca lanza.
    """
    try:
        s = _solicitud(solicitud_id)
        if not s:
            return
        if datos.get("etapa_id"):
            fila = consultar("SELECT nombre FROM items.etapas WHERE id = :id", id=datos["etapa_id"])
            datos["etapa"] = fila[0]["nombre"] if fila else None
        filas = []
        for m in _mensajes(evento, s, datos):
            gente = _vendedor(s) if m["destino"] == "vendedor" else _equipo(m["destino"])
            para = ", ".join(sorted({g["email"].strip().lower() for g in gente}))
            filas.append({
                "sol": solicitud_id, "evento": evento, "destino": m["destino"],
                "para": para or None, "asunto": m["asunto"][:300],
                "html": _html(m, s), "texto": _texto(m, s),
                "estado": "Pendiente" if para else "Omitido",
                "detalle": None if para else _sin_destinatario(m["destino"]),
            })
        with engine.begin() as conn:
            for f in filas:
                conn.execute(text("""
                    INSERT INTO items.notificaciones
                        (solicitud_id, evento, destino, para, asunto, cuerpo_html, cuerpo_texto,
                         estado, detalle)
                    VALUES (:sol, :evento, :destino, :para, :asunto, :html, :texto, :estado, :detalle)
                """), f)
        _despertar.set()
    except Exception:
        _log.exception("No se pudo registrar la notificación %s de la solicitud %s", evento, solicitud_id)


def de_solicitud(solicitud_id: int) -> list[dict]:
    """Correos de una solicitud, para su ficha (sin el cuerpo)."""
    try:
        return consultar("""
            SELECT id, evento, destino, para, asunto, estado, intentos, detalle, creado, enviado
              FROM items.notificaciones WHERE solicitud_id = :id ORDER BY id
        """, id=solicitud_id)
    except Exception:
        # Sin la tabla (base sin la migracion del 2026-11-05) la ficha igual debe abrir.
        _log.exception("Notificaciones: no se pudo leer items.notificaciones")
        return []


# --- envío -------------------------------------------------------------------

def iniciar() -> None:
    """Al arrancar la app. Sin N8N_WEBHOOK_URL no hay hilo: la cola la vacía otro servidor."""
    global _hilo
    if not settings.n8n_webhook_url:
        _log.warning("Notificaciones: sin N8N_WEBHOOK_URL este servidor no envía correos; "
                     "quedan en cola para el que sí la tenga.")
        return
    with _hilo_lock:
        if _hilo and _hilo.is_alive():
            return
        _hilo = threading.Thread(target=_bucle, daemon=True, name="notificaciones")
        _hilo.start()


def _bucle() -> None:
    while True:
        try:
            enviar_pendientes()
        except Exception:
            _log.exception("Notificaciones: falló el envío de la cola")
        _despertar.wait(INTERVALO_SEGUNDOS)
        _despertar.clear()


def enviar_pendientes() -> int:
    """Manda lo que esté en cola y devuelve cuántos salieron."""
    _mantenimiento()
    enviados = 0
    while True:
        lote = _tomar(LOTE)
        for n in lote:
            enviados += _enviar(n)
        if len(lote) < LOTE:
            return enviados


def _mantenimiento() -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE items.notificaciones
               SET estado = CASE WHEN intentos < :max THEN 'Pendiente' ELSE 'Error' END,
                   detalle = N'El envío se cortó: el servidor se reinició a mitad.',
                   actualizado = SYSUTCDATETIME()
             WHERE estado = 'Enviando' AND actualizado < DATEADD(MINUTE, -:colgado, SYSUTCDATETIME())
        """), {"max": MAX_INTENTOS, "colgado": COLGADO_MIN})
        conn.execute(text("""
            UPDATE items.notificaciones
               SET estado = 'Vencido', actualizado = SYSUTCDATETIME(),
                   detalle = LEFT(CONCAT(N'No salió en ', :h, N' h y ya no se envía. ', detalle), 1000)
             WHERE estado = 'Pendiente' AND creado < DATEADD(HOUR, -:h, SYSUTCDATETIME())
        """), {"h": VIGENCIA_HORAS})


def _tomar(n: int) -> list[dict]:
    """Marca 'Enviando' hasta n filas listas y las devuelve; otro servidor no las ve (READPAST)."""
    with engine.begin() as conn:
        filas = conn.execute(text("""
            WITH cola AS (
                SELECT TOP (:n) * FROM items.notificaciones WITH (ROWLOCK, UPDLOCK, READPAST)
                 WHERE estado = 'Pendiente'
                   AND (proximo_intento IS NULL OR proximo_intento <= SYSUTCDATETIME())
                 ORDER BY id
            )
            UPDATE cola SET estado = 'Enviando', intentos = intentos + 1, actualizado = SYSUTCDATETIME()
            OUTPUT INSERTED.id, INSERTED.evento, INSERTED.destino, INSERTED.solicitud_id, INSERTED.para,
                   INSERTED.asunto, INSERTED.cuerpo_html, INSERTED.cuerpo_texto, INSERTED.intentos
        """), {"n": n}).mappings().all()
    return sorted((dict(f) for f in filas), key=lambda f: f["id"])


def _enviar(n: dict) -> bool:
    cuerpo = {
        "id": n["id"], "evento": n["evento"], "destino": n["destino"],
        "solicitud": f"SOL-{n['solicitud_id']:05d}" if n["solicitud_id"] else None,
        "para": n["para"], "asunto": n["asunto"], "html": n["cuerpo_html"], "texto": n["cuerpo_texto"],
    }
    try:
        r = requests.post(settings.n8n_webhook_url, json=cuerpo, timeout=TIMEOUT,
                          headers={ENCABEZADO_TOKEN: settings.n8n_webhook_token})
        try:
            respuesta = r.json()
        except ValueError:
            respuesta = None
        # Solo cuenta como enviado si el flujo llegó a su respuesta {"ok": true}:
        # un 200 de otra cosa (una URL equivocada, un proxy) no es un correo enviado.
        ok = r.status_code == 200 and isinstance(respuesta, dict) and respuesta.get("ok") is True
        detalle = f"n8n respondió HTTP {r.status_code}" + ("" if ok else f": {r.text[:300]}")
    except requests.RequestException as exc:
        ok, detalle = False, f"n8n no respondió: {type(exc).__name__}"
    try:
        _cerrar(n, ok, detalle)
    except Exception:
        # Queda 'Enviando'; _mantenimiento lo devuelve a la cola en COLGADO_MIN.
        _log.exception("Notificaciones: no se pudo marcar el resultado de la %s", n["id"])
    return ok


def _cerrar(n: dict, ok: bool, detalle: str) -> None:
    with engine.begin() as conn:
        if ok:
            conn.execute(text("""
                UPDATE items.notificaciones
                   SET estado = 'Enviado', enviado = SYSUTCDATETIME(), actualizado = SYSUTCDATETIME(),
                       proximo_intento = NULL, detalle = :d
                 WHERE id = :id
            """), {"id": n["id"], "d": detalle[:1000]})
            return
        espera = REINTENTOS_MIN[n["intentos"] - 1] if n["intentos"] <= len(REINTENTOS_MIN) else None
        conn.execute(text("""
            UPDATE items.notificaciones
               SET estado = :estado, detalle = :d, actualizado = SYSUTCDATETIME(),
                   proximo_intento = CASE WHEN :espera IS NULL THEN NULL
                                          ELSE DATEADD(MINUTE, :espera, SYSUTCDATETIME()) END
             WHERE id = :id
        """), {"id": n["id"], "d": detalle[:1000], "espera": espera,
               "estado": "Pendiente" if espera else "Error"})
