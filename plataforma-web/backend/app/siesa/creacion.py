# -*- coding: utf-8 -*-
"""
Creacion real del item-extension en Siesa.

"Aprobación de Diseño" solo corre las validaciones previas (`revisar`) y deja
la solicitud autorizada; la creacion real la hace el cargue que confirma el
planeador (app.siesa.planeacion), seguida de los parametros de planeacion. Todo lo
que sabe este modulo del conector esta verificado contra el servicio real
(ver app/siesa/client.py para el contrato completo).

Dos cosas del conector que obligan a este diseno:

  1. Responde HTTP 200 / codigo 0 tanto si inserto como si la combinacion YA
     existia. Por eso se consulta el catalogo ANTES: si ya existe se informa
     el SKU y no se manda nada, en vez de reportar una creacion que no ocurrio.

  2. Cuando falla, el motivo viene dentro de `detalle` como una lista de
     objetos con `f_detalle`. Aqui se extrae a un mensaje legible; devolver
     el JSON crudo al vendedor no le sirve de nada.
"""
import json

from sqlalchemy import text

from app.db.session import consultar, engine
from app.siesa import client, extensiones

# Traduccion de los errores del conector a algo accionable para quien lo lee.
PISTAS = {
    "el item no existe": "El item base no existe en Siesa o la referencia esta mal.",
    "la extension 1 no existe": "La marca (Ext1) no existe en Siesa; hay que crearla primero.",
    "la extension 2 no existe": "El calibre (Ext2) no existe en Siesa.",
    "no manejar extensiones": "El item base no esta parametrizado para manejar extensiones.",
    "item - extensi": ("Revisa en Siesa que el item-extensión exista y que el código del "
                       "item (f120_id) sea el correcto."),
    "ruta no es valida": "Siesa no reconoce esa ruta; elige otra de la lista.",
    "bodega de asignaci": "La bodega de asignación no es válida (solo 020 o 018).",
    "unidad de medida": "La unidad de medida que envía el conector (UND) no es válida para ese item.",
    "debe ser de tipo 0": ("El conector PARAMETROS_ITEMS_V5 no genera el registro inicial del "
                           "plano; hay que corregir su definicion en Connekta."),
}


def motivo_legible(cuerpo) -> str:
    """Saca el motivo real de la respuesta del conector."""
    if isinstance(cuerpo, str):
        return cuerpo[:400]
    detalle = cuerpo.get("detalle") if isinstance(cuerpo, dict) else None
    if isinstance(detalle, list):
        partes = []
        for d in detalle:
            txt = (d.get("f_detalle") or "").strip() if isinstance(d, dict) else str(d)
            if not txt:
                continue
            pista = next((v for k, v in PISTAS.items() if k in txt.lower()), None)
            partes.append(f"{txt} {pista}".strip() if pista else txt)
        if partes:
            # Sin duplicar: el conector repite el mismo error por cada validacion en cascada
            vistos, unicos = set(), []
            for p in partes:
                if p not in vistos:
                    vistos.add(p); unicos.append(p)
            return " | ".join(unicos)[:600]
    if isinstance(cuerpo, dict):
        return f"{cuerpo.get('mensaje', '')} {cuerpo.get('detalle', '')}".strip()[:600]
    return str(cuerpo)[:400]


def _registrar(solicitud_id, usuario, http, codigo, mensaje, payload, sku=None):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO items.log_creacion
                (solicitud_id, usuario_web, http_status, codigo_conector, mensaje, sku_creado, payload_enviado)
            VALUES (:id, :usuario, :http, :codigo, :mensaje, :sku, :payload)
        """), {"id": solicitud_id, "usuario": usuario, "http": http, "codigo": codigo,
               "mensaje": mensaje[:3000] if mensaje else None, "sku": sku,
               "payload": json.dumps(payload, ensure_ascii=False) if payload else None})


def _revisar_material(s) -> str | None:
    """
    Devuelve el motivo si material e item base no concuerdan, o None si todo bien.
    Solo "Bio Natura" es bloqueante: las demas opciones (P1, P2, SP...) son
    calidades de carton que no cambian de item base.
    """
    material = (s.get("tipo_material") or "").strip().upper()
    base = (s.get("item_base") or "").upper()
    es_ldp = "LIBRE DE PLASTICO" in base

    if material == "BIO NATURA" and not es_ldp:
        alternativas = consultar("""
            SELECT TOP 3 referencia, descripcion FROM items.cat_items_base
             WHERE descripcion LIKE '%LIBRE DE PLASTICO%' AND descripcion LIKE :patron
        """, patron="%" + base.replace("VASO ", "VASO %").split(" X ")[0][:18] + "%")
        sugerencia = ""
        if alternativas:
            opts = ", ".join(f"{a['descripcion']} ({a['referencia']})" for a in alternativas)
            sugerencia = f" ¿Debería ser: {opts}?"
        return (f"No se creó: el material es Bio Natura (libre de plástico) pero el item base "
                f"'{s.get('item_base')}' es el normal.{sugerencia} "
                f"Corrige el item base antes de crear.")

    if material in ("P1", "P2") and es_ldp:
        return (f"No se creó: el item base '{s.get('item_base')}' es libre de plástico pero el "
                f"material dice {material}. Revisa cuál de los dos está mal.")
    return None


def cargar(solicitud_id: int) -> dict | None:
    filas = consultar("""
        SELECT s.id, s.item_base_referencia, s.marca_id, s.calibre_id, s.estado, s.sku_creado,
               s.tipo_material, s.titulo, s.planeacion_estado,
               b.descripcion AS item_base,
               COALESCE(m.descripcion, s.marca_nueva_texto) AS marca
          FROM items.solicitudes s
          LEFT JOIN items.cat_items_base b ON b.referencia = s.item_base_referencia
          LEFT JOIN items.cat_marcas m     ON m.id = s.marca_id
         WHERE s.id = :id
    """, id=solicitud_id)
    return filas[0] if filas else None


def otra_creada(solicitud_id: int | None, ref: str, marca: str, calibre: str) -> int | None:
    """Otra solicitud ya Creado con la misma combinacion (None si no hay)."""
    filas = consultar("""
        SELECT TOP 1 id FROM items.solicitudes
         WHERE item_base_referencia = :ref AND marca_id = :marca AND calibre_id = :cal
           AND estado = 'Creado' AND id <> :id
         ORDER BY id DESC
    """, ref=ref, marca=marca, cal=calibre, id=solicitud_id or 0)
    return filas[0]["id"] if filas else None


def revisar(s: dict) -> dict:
    """
    Lo que se puede saber sin mandar nada a Siesa. Devuelve
    {"motivo": str|None, "sku_existente": int|None}.
    """
    faltan = []
    if not s["item_base_referencia"]:
        faltan.append("item base sin resolver")
    if not s["marca_id"]:
        faltan.append(f"la marca '{s['marca'] or '—'}' no existe en Siesa (Ext1)")
    if not s["calibre_id"]:
        faltan.append("calibre sin definir")
    if faltan:
        return {"motivo": "No se puede crear: " + "; ".join(faltan) + ".", "sku_existente": None}

    # "Bio Natura" es una LINEA de producto distinta (libre de plastico), no un
    # acabado: si el material dice Bio Natura pero el item base es el normal, se
    # crearia el SKU equivocado. Siesa no valida esto — aceptaria la creacion
    # sin chistar — asi que se atrapa aqui.
    incoherencia = _revisar_material(s)
    if incoherencia:
        return {"motivo": incoherencia, "sku_existente": None}

    # Creado por otra solicitud de la plataforma: el catalogo de extensiones
    # solo se refresca con el sync, asi que un item recien creado aun no aparece.
    otra = otra_creada(s["id"], s["item_base_referencia"], s["marca_id"], s["calibre_id"])
    if otra:
        return {"motivo": f"Ese item ya fue creado en Siesa por SOL-{otra:05d}.", "sku_existente": None}

    # Ya existe? El conector responderia "exitosa" igual y seria enganoso.
    # En vivo en Siesa: la copia del sync puede ir dias atrasada.
    ya = extensiones.sku_existente(s["item_base_referencia"], s["marca_id"], s["calibre_id"],
                                   forzar=True)
    return {"motivo": None, "sku_existente": ya["sku"]}


def crear_en_siesa(solicitud_id: int, usuario: str | None = None) -> dict:
    """
    Intenta crear el item-extension. Devuelve siempre un dict con `ok` y
    `mensaje`; nunca lanza excepcion hacia la UI.
    """
    s = cargar(solicitud_id)
    if not s:
        return {"ok": False, "mensaje": "Solicitud no encontrada."}

    previo = revisar(s)
    if previo["motivo"]:
        _registrar(solicitud_id, usuario, None, None, previo["motivo"], None)
        return {"ok": False, "mensaje": previo["motivo"], "creado": False}

    if previo["sku_existente"]:
        sku = previo["sku_existente"]
        msg = f"El item ya existía en Siesa con SKU {sku}. No se creó nada nuevo."
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE items.solicitudes SET estado='Creado', sku_creado=:sku, motivo_bloqueo=NULL, "
                "fecha_modificado=SYSUTCDATETIME() WHERE id=:id"), {"sku": sku, "id": solicitud_id})
        _registrar(solicitud_id, usuario, None, None, msg, None, sku)
        return {"ok": True, "ya_existia": True, "sku_siesa": sku, "mensaje": msg}

    # --- creacion
    payload = client.construir_payload_creacion(
        s["item_base_referencia"], s["marca_id"], s["calibre_id"])
    http, cuerpo = client.crear_extension(
        s["item_base_referencia"], s["marca_id"], s["calibre_id"])

    codigo = cuerpo.get("codigo") if isinstance(cuerpo, dict) else None
    exito = http == 200 and codigo == 0

    if exito:
        msg = (f"Item creado en Siesa: {s['item_base']} · {s['marca']} · {s['calibre_id']}. "
               f"El SKU aparecerá al refrescar el catálogo.")
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE items.solicitudes SET estado='Creado', motivo_bloqueo=NULL, "
                "fecha_modificado=SYSUTCDATETIME() WHERE id=:id"), {"id": solicitud_id})
        _registrar(solicitud_id, usuario, http, codigo, msg, payload)
        return {"ok": True, "ya_existia": False, "mensaje": msg}

    motivo = motivo_legible(cuerpo)
    msg = f"Siesa rechazó la creación: {motivo}"
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE items.solicitudes SET estado='Bloqueado', motivo_bloqueo=:m, "
            "fecha_modificado=SYSUTCDATETIME() WHERE id=:id"),
            {"m": msg[:400], "id": solicitud_id})
    _registrar(solicitud_id, usuario, http, codigo, msg, payload)
    return {"ok": False, "mensaje": msg, "http": http, "codigo": codigo}
