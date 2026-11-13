# -*- coding: utf-8 -*-
"""Alta, consulta, seguimiento y adjuntos de las solicitudes de creacion de items."""
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text

from app import notificaciones, opciones as listas
from app.auth.seguridad import exigir, requiere, tiene
from app.db.session import consultar, engine
from app.siesa import creacion, extensiones
from app.storage import datalake

router = APIRouter(prefix="/solicitudes", tags=["solicitudes"])

ETAPA_INICIAL = 1     # Solicitud de Diseño
ETAPA_APROBACION = 2  # "Aprobación de Diseño": autoriza la creacion (la hace el cargue del planeador)
# Que modulo de permisos (accion "editar") hace falta para registrar cada etapa.
# 7-10 (En Diseño, En Aprobación, Envío Muestra, Ajuste Arte) van entre la 1 y la 2:
# el orden del flujo es items.etapas.orden, no el id.
ETAPA_MODULO = {1: "diseno", 2: "diseno", 3: "planeacion", 4: "pedidos", 5: "diseno", 6: "planeacion",
                7: "diseno", 8: "diseno", 9: "diseno", 10: "diseno"}


class SolicitudNueva(BaseModel):
    marca_id: Optional[str] = None
    marca_nueva_texto: Optional[str] = None
    cliente_id: Optional[int] = None
    cliente_texto: Optional[str] = None
    item_base_referencia: str
    calibre_id: Optional[str] = None
    tipo_material: str
    cantidad: int = Field(gt=0)
    vendedor_id: int
    tipo_solicitud: Optional[str] = None
    tipo_impresion: Optional[str] = None
    observaciones: Optional[str] = None


class EventoNuevo(BaseModel):
    etapa_id: int
    observacion: Optional[str] = None


@router.get("/opciones")
def opciones():
    # Editables en Configuracion; aqui solo las activas, en su orden.
    return {"materiales": listas.activas("materiales"), "tipos_solicitud": listas.activas("tipos_solicitud"),
            "tipos_impresion": listas.activas("tipos_impresion")}


def duplicado(ref: str, marca: str, cal: str, forzar: bool = False, excluir: int | None = None) -> dict:
    """
    Si esa combinacion item base + marca + calibre ya esta creada o pedida:
    {"existe": bool, "mensaje": str, "fuente": "siesa"|"copia", ...}.

    Es la UNICA regla de duplicados: la usan el aviso del formulario
    (GET /verificar) y el POST. Antes el aviso miraba solo la copia de Siesa y
    decia "se puede crear" a algo que el POST despues rechazaba con 409.

    Dos fuentes, porque ninguna alcanza sola:
      * Siesa EN VIVO (app.siesa.extensiones): lo que ya esta creado, sea por
        la plataforma o a mano. Si Siesa no responde, la copia del sync.
      * items.solicitudes: lo ya pedido y aun no creado (en diseno, esperando
        el cargue...), que Siesa todavia no conoce.
    """
    siesa = extensiones.sku_existente(ref, marca, cal, forzar=forzar)
    fuente = siesa["fuente"]
    if siesa["sku"]:
        estado = ", pero está inactivo. No se puede volver a crear" if siesa["activo"] is False else ""
        return {"existe": True, "sku_siesa": siesa["sku"], "fuente": fuente,
                "mensaje": f"Ese item ya existe en Siesa con SKU {siesa['sku']}{estado}. "
                           "No hace falta solicitarlo."}

    # Una creada gana sobre una abierta (mismo orden que creacion.otra_creada).
    otra = consultar("""
        SELECT TOP 1 id, estado FROM items.solicitudes
         WHERE item_base_referencia = :ref AND marca_id = :marca AND calibre_id = :cal
           AND eliminado_en IS NULL AND id <> :excl
         ORDER BY CASE WHEN estado = 'Creado' THEN 0 ELSE 1 END, id DESC
    """, ref=ref, marca=marca, cal=cal, excl=excluir or 0)
    if otra:
        sol = f"SOL-{otra[0]['id']:05d}"
        if otra[0]["estado"] == "Creado":
            msg = f"Ese item ya fue creado en Siesa por {sol}. No hace falta solicitarlo."
        else:
            msg = f"Ya hay una solicitud abierta para ese item: {sol} ({otra[0]['estado']})."
        return {"existe": True, "solicitud_id": otra[0]["id"], "fuente": fuente, "mensaje": msg}

    if fuente == "siesa":
        msg = "Combinación nueva: no está en Siesa ni en otra solicitud."
    else:
        msg = ("Combinación nueva según la última copia del catálogo: Siesa no respondió y no "
               "se pudo confirmar en vivo.")
    return {"existe": False, "fuente": fuente, "mensaje": msg}


@router.get("/verificar")
def verificar(item_base_referencia: str, marca_id: str, calibre_id: str):
    """Aviso del formulario, antes de guardar: la misma regla que aplica el POST."""
    return duplicado(item_base_referencia, marca_id, calibre_id)


@router.post("")
def crear(s: SolicitudNueva, usuario: dict = Depends(requiere("solicitudes", "crear"))):
    # Se guarda el nombre tal como esta configurado ("p1" -> "P1").
    s.tipo_material = listas.canonica("materiales", s.tipo_material)
    if not s.tipo_material:
        raise HTTPException(400, f"Tipo de material inválido. Válidos: {', '.join(listas.activas('materiales'))}.")
    if s.tipo_solicitud:
        s.tipo_solicitud = listas.canonica("tipos_solicitud", s.tipo_solicitud)
        if not s.tipo_solicitud:
            raise HTTPException(400, f"Tipo de solicitud inválido. Válidos: {', '.join(listas.activas('tipos_solicitud'))}.")
    if s.tipo_impresion:
        s.tipo_impresion = listas.canonica("tipos_impresion", s.tipo_impresion)
        if not s.tipo_impresion:
            raise HTTPException(400, f"Tipo de impresión inválido. Válidos: {', '.join(listas.activas('tipos_impresion'))}.")
    if not s.marca_id and not s.marca_nueva_texto:
        raise HTTPException(400, "Indica una marca existente o el nombre de una marca nueva.")
    if not s.cliente_id and not s.cliente_texto:
        raise HTTPException(400, "Indica un cliente.")
    if not s.calibre_id:
        raise HTTPException(400, "Indica el calibre: sin él no se puede crear el item en Siesa.")

    # No se piden items que ya existen: ni en Siesa ni en otra solicitud
    # (la misma regla que el aviso del formulario, ver duplicado()). Al guardar
    # se pregunta a Siesa de nuevo: el aviso pudo usar un dato de hace un minuto.
    if s.marca_id:
        dup = duplicado(s.item_base_referencia, s.marca_id, s.calibre_id, forzar=True)
        if dup["existe"]:
            raise HTTPException(409, dup["mensaje"])

    # Un Comercial solo crea a su nombre; los demas eligen entre los comerciales activos.
    if usuario.get("cargo") == "Comercial" and usuario["vendedor_id"]:
        s.vendedor_id = usuario["vendedor_id"]
    vend = consultar("""
        SELECT u.nombre, u.email FROM items.usuarios u
         WHERE u.vendedor_id = :id AND u.activo = 1 AND u.cargo = 'Comercial'
    """, id=s.vendedor_id)
    if not vend:
        raise HTTPException(400, "El vendedor debe ser un usuario activo con cargo Comercial.")
    vendedor = vend[0]

    # Sin marca en Siesa la solicitud nace bloqueada: hay que crearla en Ext1 primero.
    if s.marca_id:
        estado, motivo = "Pendiente", None
    else:
        estado = "Bloqueado"
        motivo = f"La marca '{s.marca_nueva_texto}' no existe en Siesa (Ext1); hay que crearla primero."

    with engine.begin() as conn:
        fila = conn.execute(text("""
            INSERT INTO items.solicitudes
                (marca_id, marca_nueva_texto, cliente_id, cliente_texto,
                 item_base_referencia, calibre_id, tipo_material, cantidad,
                 vendedor_id, vendedor_email, vendedor_nombre, tipo_solicitud, tipo_impresion,
                 estado, motivo_bloqueo, observaciones, etapa_actual_id, origen, creado_por)
            OUTPUT INSERTED.id
            VALUES (:marca_id, :marca_nueva, :cliente_id, :cliente_texto,
                    :ref, :calibre, :material, :cantidad,
                    :vend_id, :vend_email, :vend_nombre, :tipo_sol, :tipo_imp,
                    :estado, :motivo, :obs, :etapa, 'web', :creado_por)
        """), {
            "marca_id": s.marca_id, "marca_nueva": s.marca_nueva_texto,
            "cliente_id": s.cliente_id, "cliente_texto": s.cliente_texto,
            "ref": s.item_base_referencia, "calibre": s.calibre_id,
            "material": s.tipo_material, "cantidad": s.cantidad,
            "vend_id": s.vendedor_id, "vend_email": vendedor["email"],
            "vend_nombre": vendedor["nombre"], "tipo_sol": s.tipo_solicitud,
            "tipo_imp": s.tipo_impresion or None,
            "estado": estado, "motivo": motivo, "obs": s.observaciones,
            "etapa": ETAPA_INICIAL, "creado_por": usuario["nombre"],
        }).first()
        nuevo_id = fila[0]

        # Primer evento del tracking: toda solicitud arranca en "Solicitud de Diseño"
        conn.execute(text("""
            INSERT INTO items.seguimiento (solicitud_id, etapa_id, observacion, usuario_email, usuario_nombre)
            VALUES (:id, :etapa, :obs, :email, :nombre)
        """), {"id": nuevo_id, "etapa": ETAPA_INICIAL,
               "obs": s.observaciones or "Solicitud creada.",
               "email": None, "nombre": usuario["nombre"]})

    # Al vendedor (su constancia) y a Diseño, que es quien la toma.
    notificaciones.registrar("solicitud_creada", nuevo_id, actor=usuario["nombre"],
                             observacion=s.observaciones)
    return {"id": nuevo_id, "estado": estado, "motivo_bloqueo": motivo}


@router.get("")
def listar(
    usuario: dict = Depends(requiere("seguimiento", "ver")),
    estado: str = Query("", description="Pendiente | Creado | Bloqueado"),
    cliente: str = Query("", description="filtro por nombre de cliente"),
    referencia: str = Query("", description="filtro por item base"),
    marca: str = Query("", description="filtro por marca"),
    vendedor_id: Optional[int] = None,
    etapa_id: Optional[int] = None,
    mis_menciones: bool = False,
    limite: int = 50,
    pagina: int = 1,
):
    """
    Listado con los filtros del panel superior.

    Devuelve el TOTAL que cumple el filtro, no solo la pagina: con 953+ filas,
    mostrar "(50)" cuando hay 953 que coinciden desinforma.
    """
    filtros = dict(estado=estado, cliente=cliente, referencia=referencia,
                   marca=marca, vendedor=vendedor_id, etapa=etapa_id,
                   mias=1 if mis_menciones else 0, yo=usuario["id"])

    where = """
         WHERE s.eliminado_en IS NULL
           AND (:estado = ''    OR s.estado = :estado)
           AND (:cliente = ''   OR COALESCE(c.Nombre, s.cliente_texto) LIKE '%' + :cliente + '%')
           AND (:referencia = '' OR s.item_base_referencia LIKE '%' + :referencia + '%'
                                 OR b.descripcion LIKE '%' + :referencia + '%')
           AND (:marca = ''     OR COALESCE(m.descripcion, s.marca_nueva_texto) LIKE '%' + :marca + '%')
           AND (:vendedor IS NULL OR s.vendedor_id = :vendedor)
           AND (:etapa IS NULL    OR s.etapa_actual_id = :etapa)
           AND (:mias = 0 OR EXISTS (SELECT 1 FROM items.comentarios co
                                       JOIN items.comentario_menciones cm ON cm.comentario_id = co.id
                                      WHERE co.solicitud_id = s.id AND cm.usuario_id = :yo))
    """
    joins = """
          FROM items.solicitudes s
          LEFT JOIN dbo.PQRS_ClientesSiesa c ON c.Id = s.cliente_id
          LEFT JOIN items.cat_marcas m       ON m.id = s.marca_id
          LEFT JOIN items.cat_items_base b   ON b.referencia = s.item_base_referencia
          LEFT JOIN items.cat_calibres cal   ON cal.id = s.calibre_id
          LEFT JOIN items.etapas e           ON e.id = s.etapa_actual_id
    """
    total = consultar("SELECT COUNT(1) AS n " + joins + where, **filtros)[0]["n"]

    filas = consultar(
        """
        SELECT s.id, s.estado, s.motivo_bloqueo, s.cantidad, s.tipo_material,
               s.tipo_solicitud, s.tipo_impresion, s.montaje, s.fecha_creado, s.sku_creado,
               s.vendedor_nombre,
               COALESCE(c.Nombre, s.cliente_texto)        AS cliente,
               COALESCE(m.descripcion, s.marca_nueva_texto) AS marca,
               s.item_base_referencia                      AS referencia,
               b.descripcion                               AS item_base,
               cal.descripcion                             AS calibre,
               e.nombre                                    AS etapa_actual,
               e.orden                                     AS etapa_orden,
               (SELECT COUNT(1) FROM items.adjuntos a WHERE a.solicitud_id = s.id) AS adjuntos,
               (SELECT COUNT(1) FROM items.comentarios co
                 WHERE co.solicitud_id = s.id AND co.tipo = 'comentario') AS comentarios,
               (SELECT COUNT(1) FROM items.comentarios co
                  JOIN items.comentario_menciones cm ON cm.comentario_id = co.id
                 WHERE co.solicitud_id = s.id AND cm.usuario_id = :yo) AS menciones_mias,
               (SELECT MAX(sg.fecha) FROM items.seguimiento sg WHERE sg.solicitud_id = s.id) AS ultimo_movimiento
        """ + joins + where + """
         ORDER BY s.id DESC
         OFFSET :salto ROWS FETCH NEXT :limite ROWS ONLY
        """,
        **filtros, limite=limite, salto=max(0, (pagina - 1) * limite),
    )
    return {"total": total, "pagina": pagina, "limite": limite, "filas": filas}


@router.get("/resumen")
def resumen(_=Depends(requiere("seguimiento", "ver"))):
    """Totales para las tarjetas del panel de visualizacion."""
    por_estado = consultar(
        "SELECT estado, COUNT(1) AS total FROM items.solicitudes WHERE eliminado_en IS NULL GROUP BY estado")
    por_etapa = consultar("""
        SELECT e.nombre AS etapa, e.orden, COUNT(s.id) AS total
          FROM items.etapas e
          LEFT JOIN items.solicitudes s ON s.etapa_actual_id = e.id AND s.eliminado_en IS NULL
         GROUP BY e.nombre, e.orden
         ORDER BY e.orden
    """)
    return {"por_estado": por_estado, "por_etapa": por_etapa}


# Debe ir ANTES de /{solicitud_id}: esa ruta comodin capturaria /adjuntos/...
@router.get("/adjuntos/{adjunto_id}/url")
def url_adjunto(adjunto_id: int, _=Depends(requiere("seguimiento", "ver"))):
    """URL firmada de vida corta; el contenedor no es publico."""
    filas = consultar("SELECT blob_path, nombre_archivo FROM items.adjuntos WHERE id = :id",
                      id=adjunto_id)
    if not filas:
        raise HTTPException(404, "Adjunto no encontrado")
    return {"url": datalake.url_temporal(filas[0]["blob_path"]),
            "nombre_archivo": filas[0]["nombre_archivo"]}


@router.get("/mencionables")
def mencionables(_=Depends(requiere("seguimiento", "ver"))):
    """Personas que se pueden etiquetar en un comentario: los usuarios activos."""
    return consultar("""
        SELECT id, nombre, username, cargo,
               CASE WHEN LTRIM(RTRIM(ISNULL(email, ''))) <> '' THEN 1 ELSE 0 END AS tiene_correo
          FROM items.usuarios WHERE activo = 1 ORDER BY nombre
    """)


def comentarios_de(solicitud_id: int) -> list[dict]:
    filas = consultar("""
        SELECT id, usuario_id, autor, texto, tipo, creado
          FROM items.comentarios WHERE solicitud_id = :id ORDER BY creado, id
    """, id=solicitud_id)
    menciones = consultar("""
        SELECT cm.comentario_id, u.id, u.nombre
          FROM items.comentario_menciones cm
          JOIN items.comentarios co ON co.id = cm.comentario_id
          JOIN items.usuarios u     ON u.id = cm.usuario_id
         WHERE co.solicitud_id = :id
    """, id=solicitud_id)
    for f in filas:
        f["menciones"] = [{"id": m["id"], "nombre": m["nombre"]}
                          for m in menciones if m["comentario_id"] == f["id"]]
    return filas


@router.get("/{solicitud_id}")
def detalle(solicitud_id: int, _=Depends(requiere("seguimiento", "ver"))):
    filas = listar_una(solicitud_id)
    if not filas:
        raise HTTPException(404, "Solicitud no encontrada")
    seguimiento = consultar("""
        SELECT sg.id, sg.etapa_id, e.nombre AS etapa, e.orden, sg.observacion,
               sg.usuario_nombre, sg.fecha
          FROM items.seguimiento sg
          JOIN items.etapas e ON e.id = sg.etapa_id
         WHERE sg.solicitud_id = :id
         ORDER BY sg.fecha, sg.id
    """, id=solicitud_id)
    adjuntos = consultar("""
        SELECT id, nombre_archivo, tipo_contenido, tamano_bytes, subido_por, fecha
          FROM items.adjuntos WHERE solicitud_id = :id ORDER BY fecha
    """, id=solicitud_id)
    return {"solicitud": filas[0], "seguimiento": seguimiento, "adjuntos": adjuntos,
            "comentarios": comentarios_de(solicitud_id),
            "notificaciones": notificaciones.de_solicitud(solicitud_id)}


def listar_una(solicitud_id: int):
    """La solicitud (sin las eliminadas: para todo lo demas, ya no existe)."""
    return consultar("""
        SELECT s.id, s.estado, s.motivo_bloqueo, s.cantidad, s.tipo_material,
               s.tipo_solicitud, s.tipo_impresion, s.montaje, s.fecha_creado, s.sku_creado, s.observaciones,
               s.vendedor_nombre, s.vendedor_email, s.vendedor_id,
               s.marca_id, s.marca_nueva_texto, s.cliente_id, s.cliente_texto, s.calibre_id,
               CASE WHEN EXISTS (SELECT 1 FROM items.cargue_detalle d
                                  WHERE d.solicitud_id = s.id AND d.estado = 'En cola')
                    THEN 1 ELSE 0 END AS en_cargue,
               COALESCE(c.Nombre, s.cliente_texto)          AS cliente,
               COALESCE(m.descripcion, s.marca_nueva_texto) AS marca,
               s.item_base_referencia                        AS referencia,
               b.descripcion AS item_base, cal.descripcion AS calibre,
               e.nombre AS etapa_actual, e.orden AS etapa_orden,
               s.fecha_autorizacion, s.ruta_id, s.bodega_asignacion,
               s.planeacion_estado, s.planeacion_mensaje
          FROM items.solicitudes s
          LEFT JOIN dbo.PQRS_ClientesSiesa c ON c.Id = s.cliente_id
          LEFT JOIN items.cat_marcas m       ON m.id = s.marca_id
          LEFT JOIN items.cat_items_base b   ON b.referencia = s.item_base_referencia
          LEFT JOIN items.cat_calibres cal   ON cal.id = s.calibre_id
          LEFT JOIN items.etapas e           ON e.id = s.etapa_actual_id
         WHERE s.id = :id AND s.eliminado_en IS NULL
    """, id=solicitud_id)


# --- comentarios ---------------------------------------------------------------

class ComentarioNuevo(BaseModel):
    texto: str
    menciones: list[int] = Field(default_factory=list)


MAX_COMENTARIO = 2000
MAX_MENCIONES = 20


def _bitacora(conn, solicitud_id: int, usuario: dict | None, texto: str, tipo: str) -> None:
    """Comentario que deja la plataforma (edicion, eliminacion): queda en la ficha como historial."""
    conn.execute(text("""
        INSERT INTO items.comentarios (solicitud_id, usuario_id, autor, texto, tipo)
        VALUES (:s, :u, :a, :t, :tipo)
    """), {"s": solicitud_id, "u": usuario["id"] if usuario else None,
           "a": usuario["nombre"] if usuario else "Plataforma", "t": texto[:MAX_COMENTARIO], "tipo": tipo})


@router.post("/{solicitud_id}/comentarios", status_code=201)
def comentar(solicitud_id: int, c: ComentarioNuevo, usuario: dict = Depends(requiere("seguimiento", "ver"))):
    """
    Comentario en la ficha. `menciones` son los usuarios etiquetados con @: el
    comentario queda dirigido a ellos y cada uno recibe un correo (menos quien
    se etiqueta a si mismo).
    """
    texto = (c.texto or "").strip()
    if not texto:
        raise HTTPException(400, "Escribe el comentario.")
    if len(texto) > MAX_COMENTARIO:
        raise HTTPException(400, f"Máximo {MAX_COMENTARIO} caracteres.")
    ids = list(dict.fromkeys(int(i) for i in c.menciones))
    if len(ids) > MAX_MENCIONES:
        raise HTTPException(400, f"Máximo {MAX_MENCIONES} personas por comentario.")
    if not listar_una(solicitud_id):
        raise HTTPException(404, "Solicitud no encontrada")
    gente = []
    if ids:
        marcadores = ", ".join(f":m{i}" for i in range(len(ids)))
        gente = consultar(f"""
            SELECT id, nombre, email FROM items.usuarios WHERE activo = 1 AND id IN ({marcadores})
        """, **{f"m{i}": v for i, v in enumerate(ids)})
        if len(gente) != len(ids):
            raise HTTPException(400, "Alguna de las personas etiquetadas no existe o está inactiva.")

    with engine.begin() as conn:
        nuevo = conn.execute(text("""
            INSERT INTO items.comentarios (solicitud_id, usuario_id, autor, texto, tipo)
            OUTPUT INSERTED.id VALUES (:s, :u, :a, :t, 'comentario')
        """), {"s": solicitud_id, "u": usuario["id"], "a": usuario["nombre"], "t": texto}).first()[0]
        for g in gente:
            conn.execute(text("INSERT INTO items.comentario_menciones (comentario_id, usuario_id) VALUES (:c, :u)"),
                         {"c": nuevo, "u": g["id"]})

    for g in gente:
        if g["id"] != usuario["id"]:
            notificaciones.registrar("mencion", solicitud_id, actor=usuario["nombre"], texto=texto,
                                     gente=[g] if (g["email"] or "").strip() else [], nombre=g["nombre"])
    return {"id": nuevo}


# --- edicion y eliminacion (permisos Editar / Eliminar de "solicitudes") ---------

class SolicitudEdicion(SolicitudNueva):
    montaje: Optional[int] = None


def _valor_lista(lista: str, nombre: str | None, actual: str | None, etiqueta: str, obligatorio=False):
    """Opcion activa de Configuracion. La que la solicitud YA tiene vale aunque la hayan desactivado."""
    nombre = (nombre or "").strip()
    if not nombre:
        if obligatorio:
            raise HTTPException(400, f"Indica el {etiqueta.lower()}.")
        return None
    if actual and nombre.lower() == actual.lower():
        return actual
    canon = listas.canonica(lista, nombre)
    if not canon:
        raise HTTPException(400, f"{etiqueta} inválido. Válidos: {', '.join(listas.activas(lista))}.")
    return canon


# Lo que se compara para la bitacora de la edicion: (campo de listar_una, etiqueta).
CAMPOS_EDICION = [
    ("item_base", "Item base"), ("marca", "Marca"), ("cliente", "Cliente"), ("calibre", "Calibre"),
    ("tipo_material", "Material"), ("cantidad", "Cantidad"), ("vendedor_nombre", "Vendedor"),
    ("tipo_solicitud", "Tipo de solicitud"), ("tipo_impresion", "T. Impresión"), ("montaje", "Montaje"),
    ("observaciones", "Observaciones"),
]


@router.put("/{solicitud_id}")
def editar(solicitud_id: int, s: SolicitudEdicion, usuario: dict = Depends(requiere("solicitudes", "editar"))):
    """
    Corrige los datos de una solicitud. Item base, marca y calibre no cambian si
    el item ya esta creado en Siesa (seria otro item) ni durante un cargue; si
    cambian, se revisa de nuevo que esa combinacion no exista. El cambio queda
    como comentario de la plataforma en la ficha.
    """
    previas = listar_una(solicitud_id)
    if not previas:
        raise HTTPException(404, "Solicitud no encontrada")
    p = previas[0]
    if p["en_cargue"]:
        raise HTTPException(409, "Está en un cargue en proceso: espera a que termine para editarla.")

    material = _valor_lista("materiales", s.tipo_material, p["tipo_material"], "Tipo de material", True)
    tipo_sol = _valor_lista("tipos_solicitud", s.tipo_solicitud, p["tipo_solicitud"], "Tipo de solicitud")
    tipo_imp = _valor_lista("tipos_impresion", s.tipo_impresion, p["tipo_impresion"], "Tipo de impresión")
    if not s.cliente_id and not (s.cliente_texto or "").strip():
        raise HTTPException(400, "Indica un cliente.")
    if not s.calibre_id:
        raise HTTPException(400, "Indica el calibre: sin él no se puede crear el item en Siesa.")
    if s.montaje is not None and not (0 < s.montaje <= 9999):
        raise HTTPException(400, "El montaje es un número entero entre 1 y 9999.")
    if not s.marca_id:
        if p["marca_id"] or not (s.marca_nueva_texto or "").strip():
            raise HTTPException(400, "Elige una marca del catálogo de Siesa.")

    claves_antes = (p["referencia"], p["marca_id"], p["calibre_id"])
    claves = (s.item_base_referencia, s.marca_id, s.calibre_id)
    if claves != claves_antes:
        if p["estado"] == "Creado":
            raise HTTPException(400, "El item ya está creado en Siesa: item base, marca y calibre no se "
                                     "pueden cambiar (sería otro item). Crea una solicitud nueva.")
        if s.marca_id:
            dup = duplicado(*claves, forzar=True, excluir=solicitud_id)
            if dup["existe"]:
                raise HTTPException(409, dup["mensaje"])

    if s.vendedor_id == p["vendedor_id"]:
        vendedor = {"nombre": p["vendedor_nombre"], "email": p["vendedor_email"]}
    else:
        vend = consultar("""
            SELECT nombre, email FROM items.usuarios
             WHERE vendedor_id = :id AND activo = 1 AND cargo = 'Comercial'
        """, id=s.vendedor_id)
        if not vend:
            raise HTTPException(400, "El vendedor debe ser un usuario activo con cargo Comercial.")
        vendedor = vend[0]

    # Bloqueada solo por marca inexistente y ahora con marca del catalogo: se libera.
    estado, motivo = p["estado"], p["motivo_bloqueo"]
    if s.marca_id and not p["marca_id"] and estado == "Bloqueado":
        estado, motivo = "Pendiente", None

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE items.solicitudes SET
                   item_base_referencia = :ref, marca_id = :marca, marca_nueva_texto = :marca_nueva,
                   cliente_id = :cliente_id, cliente_texto = :cliente_texto, calibre_id = :cal,
                   tipo_material = :material, cantidad = :cantidad, vendedor_id = :vend_id,
                   vendedor_email = :vend_email, vendedor_nombre = :vend_nombre,
                   tipo_solicitud = :tipo_sol, tipo_impresion = :tipo_imp, montaje = :montaje,
                   observaciones = :obs, estado = :estado, motivo_bloqueo = :motivo,
                   modificado_por = :quien, fecha_modificado = SYSUTCDATETIME()
             WHERE id = :id AND eliminado_en IS NULL
        """), {
            "ref": s.item_base_referencia, "marca": s.marca_id,
            "marca_nueva": None if s.marca_id else s.marca_nueva_texto.strip(),
            "cliente_id": s.cliente_id, "cliente_texto": None if s.cliente_id else s.cliente_texto.strip(),
            "cal": s.calibre_id, "material": material, "cantidad": s.cantidad,
            "vend_id": s.vendedor_id, "vend_email": vendedor["email"], "vend_nombre": vendedor["nombre"],
            "tipo_sol": tipo_sol, "tipo_imp": tipo_imp, "montaje": s.montaje,
            "obs": (s.observaciones or "").strip() or None, "estado": estado, "motivo": motivo,
            "quien": usuario["nombre"], "id": solicitud_id,
        })
        nueva = listar_una_conn(conn, solicitud_id)
        cambios = []
        for campo, etiqueta in CAMPOS_EDICION:
            a, d = _v(p.get(campo)), _v(nueva.get(campo))
            if a == d:
                continue
            if campo == "observaciones":
                cambios.append("Observaciones actualizadas")
            else:
                cambios.append(f"{etiqueta}: {a if a is not None else '—'} → {d if d is not None else '—'}")
        if cambios:
            _bitacora(conn, solicitud_id, usuario, "Editó la solicitud. " + " · ".join(cambios), "edicion")
    return {"ok": True, "cambios": len(cambios)}


def _v(x):
    """Vacio y None cuentan igual al comparar antes / despues."""
    return None if x is None or (isinstance(x, str) and not x.strip()) else x


def listar_una_conn(conn, solicitud_id: int) -> dict:
    """Como listar_una, dentro de una transaccion abierta (ve lo que ella acaba de escribir)."""
    fila = conn.execute(text("""
        SELECT s.cantidad, s.tipo_material, s.tipo_solicitud, s.tipo_impresion, s.montaje,
               s.observaciones, s.vendedor_nombre,
               COALESCE(c.Nombre, s.cliente_texto)          AS cliente,
               COALESCE(m.descripcion, s.marca_nueva_texto) AS marca,
               b.descripcion AS item_base, cal.descripcion AS calibre
          FROM items.solicitudes s
          LEFT JOIN dbo.PQRS_ClientesSiesa c ON c.Id = s.cliente_id
          LEFT JOIN items.cat_marcas m       ON m.id = s.marca_id
          LEFT JOIN items.cat_items_base b   ON b.referencia = s.item_base_referencia
          LEFT JOIN items.cat_calibres cal   ON cal.id = s.calibre_id
         WHERE s.id = :id
    """), {"id": solicitud_id}).mappings().first()
    return dict(fila) if fila else {}


@router.delete("/{solicitud_id}")
def eliminar(solicitud_id: int, motivo: str = Query("", max_length=500),
             usuario: dict = Depends(requiere("solicitudes", "eliminar"))):
    """
    Eliminacion logica: la solicitud desaparece de las pantallas y de la regla
    de duplicados (se puede volver a pedir), pero su historial queda en la base.
    No borra nada en Siesa. Los correos que aun no salieron se cancelan.
    """
    previas = listar_una(solicitud_id)
    if not previas:
        raise HTTPException(404, "Solicitud no encontrada")
    if previas[0]["en_cargue"]:
        raise HTTPException(409, "Está en un cargue en proceso: espera a que termine para eliminarla.")
    with engine.begin() as conn:
        hecho = conn.execute(text("""
            UPDATE items.solicitudes SET eliminado_en = SYSUTCDATETIME(), eliminado_por = :quien,
                   fecha_modificado = SYSUTCDATETIME()
             WHERE id = :id AND eliminado_en IS NULL
        """), {"quien": usuario["nombre"], "id": solicitud_id}).rowcount
        if not hecho:
            raise HTTPException(404, "Solicitud no encontrada")
        conn.execute(text("""
            UPDATE items.notificaciones SET estado = 'Omitido', detalle = 'No se envió: la solicitud se eliminó.',
                   actualizado = SYSUTCDATETIME()
             WHERE solicitud_id = :id AND estado = 'Pendiente'
        """), {"id": solicitud_id})
        motivo = " ".join((motivo or "").split())
        _bitacora(conn, solicitud_id, usuario,
                  "Eliminó la solicitud." + (f" Motivo: {motivo}" if motivo else ""), "eliminacion")
    return {"ok": True}


@router.post("/{solicitud_id}/seguimiento")
def agregar_evento(solicitud_id: int, ev: EventoNuevo, usuario: dict = Depends(requiere("seguimiento", "ver"))):
    """
    Registra un avance de etapa. Deja el historial completo en items.seguimiento
    y actualiza `etapa_actual_id` (que es solo un espejo, para el listado).
    Cada etapa la registra el area duena (ETAPA_MODULO), a nombre de la sesion.
    """
    if ev.etapa_id not in ETAPA_MODULO:
        raise HTTPException(400, "Etapa desconocida.")
    exigir(usuario, ETAPA_MODULO[ev.etapa_id], "editar")
    previa = listar_una(solicitud_id)
    if not previa:
        raise HTTPException(404, "Solicitud no encontrada")

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO items.seguimiento
                (solicitud_id, etapa_id, observacion, usuario_email, usuario_nombre)
            VALUES (:id, :etapa, :obs, :email, :nombre)
        """), {"id": solicitud_id, "etapa": ev.etapa_id, "obs": ev.observacion,
               "email": None, "nombre": usuario["nombre"]})
        conn.execute(text(
            "UPDATE items.solicitudes SET etapa_actual_id = :etapa, "
            + ("aprobacion = 1, " if ev.etapa_id == ETAPA_APROBACION else "")
            + "fecha_modificado = SYSUTCDATETIME() WHERE id = :id"
        ), {"etapa": ev.etapa_id, "id": solicitud_id})

    if ev.etapa_id == ETAPA_APROBACION:
        # Su correo depende de lo que resulte de autorizar: lo arma esa funcion.
        return _autorizar_al_aprobar(solicitud_id, previa[0], usuario["nombre"], ev.observacion)
    notificaciones.registrar("etapa", solicitud_id, etapa_id=ev.etapa_id, actor=usuario["nombre"],
                             observacion=ev.observacion)
    return {"ok": True}


def _autorizar_al_aprobar(solicitud_id: int, previa: dict, actor: str | None = None,
                          observacion: str | None = None) -> dict:
    """
    Aprobar el diseno AUTORIZA la creacion, no la hace: el item necesita sus
    parametros de planeacion (ruta y bodega) y esos los confirma el planeador
    en "Items listos a crear". Aqui solo se corre lo que se puede revisar sin
    Siesa, para que al planeador no le lleguen solicitudes que van a fallar.
    """
    if previa["estado"] == "Creado" or previa["fecha_autorizacion"]:
        return {"ok": True, "autorizacion": {"ok": True, "repetida": True,
                "mensaje": "Ya estaba autorizada para creación; no cambia nada."}}

    s = creacion.cargar(solicitud_id)
    r = creacion.revisar(s)
    with engine.begin() as conn:
        if r["motivo"]:
            msg = "No se autorizó la creación. " + r["motivo"]
            conn.execute(text(
                "UPDATE items.solicitudes SET estado = 'Bloqueado', motivo_bloqueo = :m, "
                "fecha_modificado = SYSUTCDATETIME() WHERE id = :id"
            ), {"m": r["motivo"][:400], "id": solicitud_id})
            ok = False
        elif r["sku_existente"]:
            msg = f"El item ya existía en Siesa con SKU {r['sku_existente']}. No hace falta crearlo."
            conn.execute(text(
                "UPDATE items.solicitudes SET estado = 'Creado', sku_creado = :sku, motivo_bloqueo = NULL, "
                "fecha_modificado = SYSUTCDATETIME() WHERE id = :id"
            ), {"sku": r["sku_existente"], "id": solicitud_id})
            ok = True
        else:
            msg = ("Autorizado para creación. Pendiente: el planeador confirma ruta y bodega "
                   "en “Items listos a crear”.")
            conn.execute(text(
                "UPDATE items.solicitudes SET fecha_autorizacion = SYSUTCDATETIME(), estado = 'Pendiente', "
                "motivo_bloqueo = NULL, fecha_modificado = SYSUTCDATETIME() WHERE id = :id"
            ), {"id": solicitud_id})
            ok = True
        conn.execute(text("""
            INSERT INTO items.seguimiento (solicitud_id, etapa_id, observacion, usuario_nombre)
            VALUES (:id, :etapa, :obs, 'Plataforma')
        """), {"id": solicitud_id, "etapa": ETAPA_APROBACION, "obs": msg})

    # Vendedor siempre; Planeación solo si quedó autorizada (le llega a "Items listos a crear").
    if r["motivo"]:
        notificaciones.registrar("diseno_bloqueado", solicitud_id, actor=actor, mensaje=r["motivo"])
    elif r["sku_existente"]:
        notificaciones.registrar("item_existente", solicitud_id, actor=actor, sku=r["sku_existente"])
    else:
        notificaciones.registrar("diseno_aprobado", solicitud_id, actor=actor, observacion=observacion)
    return {"ok": ok, "autorizacion": {"ok": ok, "mensaje": msg,
                                       "ya_existia": bool(r["sku_existente"])}}


@router.post("/{solicitud_id}/adjuntos")
async def subir_adjunto(solicitud_id: int, archivo: UploadFile = File(...),
                        usuario: dict = Depends(requiere("seguimiento", "ver"))):
    # Quien crea la solicitud adjunta sus artes aunque su rol no edite el seguimiento.
    if not (tiene(usuario, "seguimiento", "editar") or tiene(usuario, "solicitudes", "crear")):
        raise HTTPException(403, "Tu rol no tiene permiso para esta acción.")
    if not listar_una(solicitud_id):
        raise HTTPException(404, "Solicitud no encontrada")
    datos = await archivo.read()
    if not datos:
        raise HTTPException(400, "El archivo esta vacio.")
    ruta = datalake.subir(solicitud_id, archivo.filename, datos, archivo.content_type)
    with engine.begin() as conn:
        fila = conn.execute(text("""
            INSERT INTO items.adjuntos
                (solicitud_id, nombre_archivo, tipo_contenido, tamano_bytes, blob_path, subido_por)
            OUTPUT INSERTED.id
            VALUES (:id, :nombre, :tipo, :tam, :ruta, :quien)
        """), {"id": solicitud_id, "nombre": archivo.filename,
               "tipo": archivo.content_type, "tam": len(datos),
               "ruta": ruta, "quien": usuario["nombre"]}).first()
    return {"id": fila[0], "nombre_archivo": archivo.filename, "tamano_bytes": len(datos)}

