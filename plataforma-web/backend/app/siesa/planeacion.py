# -*- coding: utf-8 -*-
"""
Parametros de planeacion y cargues.

Flujo (2026-10-31):
  1. "Aprobación de Diseño" autoriza la solicitud (fecha_autorizacion), sin
     tocar Siesa.
  2. El planeador ve las autorizadas en "Items listos a crear", elige ruta
     (catalogo koscolombia_MF_Rutas en vivo) y bodega de asignacion (020/018)
     y confirma.
  3. Un cargue, en segundo plano, recorre las filas una por una: crea el
     item-extension (app.siesa.creacion) y, solo si quedo creado, le asocia
     sus parametros (conector PARAMETROS_ITEMS_V5).
  4. Cada fila queda en items.cargue_detalle con el resultado de los dos pasos:
     eso es el historial que consulta el planeador.

Se procesa una fila a la vez y no un plano con todas: cuando el conector
rechaza un plano de varias lineas, el error no siempre dice cual fue, y el
planeador necesita saber exactamente que item revisar en Siesa.
"""
import json
import threading
import time

from sqlalchemy import text

from app.db.session import consultar, engine
from app.siesa import client, creacion

ETAPA_APROBACION = 2
ETAPA_CREACION = 3
BODEGAS = list(client.BODEGAS_ASIGNACION)
RUTAS_TTL = 600

_rutas_cache = {"t": 0.0, "filas": []}
_rutas_lock = threading.Lock()
_cargue_lock = threading.Lock()   # un cargue a la vez: dos en paralelo podrian crear el mismo item


class ErrorPlaneacion(Exception):
    pass


# --- catalogo de rutas -------------------------------------------------------

def rutas(forzar: bool = False) -> list[dict]:
    """Rutas activas de Siesa. Si Siesa no responde se sirve la ultima lista buena."""
    with _rutas_lock:
        if not forzar and _rutas_cache["filas"] and time.time() - _rutas_cache["t"] < RUTAS_TTL:
            return _rutas_cache["filas"]
        try:
            filas = client.consultar("rutas", reintentos=2)
        except RuntimeError:
            if _rutas_cache["filas"]:
                return _rutas_cache["filas"]
            raise
        activas = sorted(
            ({"id": f["f808_id"].strip(), "descripcion": (f["f808_descripcion"] or "").strip()}
             for f in filas if f.get("f808_ind_estado") == 1),
            key=lambda r: r["id"])
        _rutas_cache.update(t=time.time(), filas=activas)
        return activas


# --- items listos a crear ----------------------------------------------------

def listos() -> list[dict]:
    """
    Autorizadas que aun no terminan: sin crear, o creadas sin parametros.
    Las creadas con parametros fallidos siguen aqui para reintentar solo eso.
    """
    return consultar("""
        SELECT s.id, s.estado, s.motivo_bloqueo, s.cantidad, s.tipo_material,
               s.fecha_autorizacion, s.vendedor_nombre,
               s.item_base_referencia AS referencia, b.descripcion AS item_base,
               b.item_id AS item_codigo,
               s.marca_id, COALESCE(m.descripcion, s.marca_nueva_texto) AS marca,
               s.calibre_id, cal.descripcion AS calibre,
               COALESCE(c.Nombre, s.cliente_texto) AS cliente,
               s.ruta_id, s.bodega_asignacion, s.planeacion_estado, s.planeacion_mensaje,
               CASE WHEN EXISTS (SELECT 1 FROM items.cargue_detalle d
                                  WHERE d.solicitud_id = s.id AND d.estado = 'En cola')
                    THEN 1 ELSE 0 END AS en_cargue
          FROM items.solicitudes s
          LEFT JOIN items.cat_items_base b   ON b.referencia = s.item_base_referencia
          LEFT JOIN items.cat_marcas m       ON m.id = s.marca_id
          LEFT JOIN items.cat_calibres cal   ON cal.id = s.calibre_id
          LEFT JOIN dbo.PQRS_ClientesSiesa c ON c.Id = s.cliente_id
         WHERE s.fecha_autorizacion IS NOT NULL
           AND (s.estado <> 'Creado' OR ISNULL(s.planeacion_estado, '') <> 'Cargada')
         ORDER BY s.fecha_autorizacion, s.id
    """)


def guardar_borrador(solicitud_id: int, ruta_id: str | None, bodega: str | None,
                     item_codigo: int | None = None) -> None:
    """Guarda lo que el planeador va eligiendo, para no perderlo al recargar."""
    if bodega and bodega not in BODEGAS:
        raise ErrorPlaneacion(f"Bodega invalida. Opciones: {', '.join(BODEGAS)}.")
    if ruta_id and ruta_id not in {r["id"] for r in rutas()}:
        raise ErrorPlaneacion(f"La ruta '{ruta_id}' no existe o esta inactiva en Siesa.")
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE items.solicitudes SET ruta_id = :ruta, bodega_asignacion = :bodega,
                   fecha_modificado = SYSUTCDATETIME()
             WHERE id = :id
        """), {"ruta": ruta_id or None, "bodega": bodega or None, "id": solicitud_id})
        if item_codigo:
            _guardar_codigo(conn, solicitud_id, item_codigo)


def _guardar_codigo(conn, solicitud_id: int, item_codigo: int) -> None:
    # El codigo es del item BASE: se aprende una vez y sirve para todas sus extensiones.
    if not (0 < int(item_codigo) <= 9_999_999):
        raise ErrorPlaneacion("El código del item es numérico de hasta 7 dígitos.")
    conn.execute(text("""
        UPDATE b SET item_id = :cod
          FROM items.cat_items_base b
          JOIN items.solicitudes s ON s.item_base_referencia = b.referencia
         WHERE s.id = :id
    """), {"cod": int(item_codigo), "id": solicitud_id})


# --- cargues -----------------------------------------------------------------

def iniciar_cargue(filas: list[dict], usuario: str | None) -> int:
    """
    Valida TODO antes de crear el cargue: un cargue que arranca y falla en la
    fila 3 por una ruta mal escrita deja al planeador con medio lote hecho.
    """
    if not filas:
        raise ErrorPlaneacion("No hay items seleccionados.")
    if len({f["solicitud_id"] for f in filas}) != len(filas):
        raise ErrorPlaneacion("Hay solicitudes repetidas en el cargue.")
    # El lock se toma AQUI y lo suelta el hilo al terminar. Chequear locked() y
    # tomarlo despues dejaba pasar dos POST simultaneos con las mismas filas.
    if not _cargue_lock.acquire(blocking=False):
        raise ErrorPlaneacion("Ya hay un cargue en proceso. Espera a que termine.")
    try:
        cargue_id = _registrar_cargue(filas, usuario)
    except BaseException:
        _cargue_lock.release()
        raise
    threading.Thread(target=_procesar, args=(cargue_id, usuario), daemon=True,
                     name=f"cargue-{cargue_id}").start()
    return cargue_id


def _registrar_cargue(filas: list[dict], usuario: str | None) -> int:
    validas = {r["id"] for r in rutas()}
    pendientes = {f["id"]: f for f in listos()}
    # El codigo es del item base: digitado en una fila, vale para las demas del mismo base.
    codigos = {pendientes[f["solicitud_id"]]["referencia"]: f["item_codigo"]
               for f in filas if f.get("item_codigo") and f["solicitud_id"] in pendientes}
    problemas = []
    for f in filas:
        sid = f["solicitud_id"]
        p = pendientes.get(sid)
        etiqueta = f"SOL-{sid:05d}"
        if not p:
            problemas.append(f"{etiqueta}: no está autorizada o ya se cargó.")
            continue
        if p["en_cargue"]:
            problemas.append(f"{etiqueta}: ya está en un cargue en proceso.")
        if f.get("ruta_id") not in validas:
            problemas.append(f"{etiqueta}: elige una ruta válida.")
        if f.get("bodega") not in BODEGAS:
            problemas.append(f"{etiqueta}: elige la bodega de asignación (020 o 018).")
        f["item_codigo"] = f.get("item_codigo") or codigos.get(p["referencia"]) or p["item_codigo"]
        if not f["item_codigo"]:
            problemas.append(f"{etiqueta}: falta el código del item base ({p['referencia']}).")
    if problemas:
        raise ErrorPlaneacion(" ".join(problemas))

    with engine.begin() as conn:
        cargue_id = conn.execute(text("""
            INSERT INTO items.cargues (usuario, total) OUTPUT INSERTED.id VALUES (:u, :n)
        """), {"u": usuario, "n": len(filas)}).first()[0]
        for f in filas:
            sid = f["solicitud_id"]
            if f.get("item_codigo"):
                _guardar_codigo(conn, sid, f["item_codigo"])
            conn.execute(text("""
                UPDATE items.solicitudes SET ruta_id = :ruta, bodega_asignacion = :bodega,
                       fecha_modificado = SYSUTCDATETIME() WHERE id = :id
            """), {"ruta": f["ruta_id"], "bodega": f["bodega"], "id": sid})
            p = pendientes[sid]
            conn.execute(text("""
                INSERT INTO items.cargue_detalle
                    (cargue_id, solicitud_id, referencia, item_codigo, marca_id, calibre_id, ruta_id, bodega)
                VALUES (:c, :s, :ref, :cod, :marca, :cal, :ruta, :bodega)
            """), {"c": cargue_id, "s": sid, "ref": p["referencia"],
                   "cod": f["item_codigo"],
                   "marca": p["marca_id"], "cal": p["calibre_id"],
                   "ruta": f["ruta_id"], "bodega": f["bodega"]})
    return cargue_id


def _procesar(cargue_id: int, usuario: str | None) -> None:
    """Corre con _cargue_lock ya tomado por iniciar_cargue; lo suelta al final."""
    try:
        detalle = consultar("SELECT * FROM items.cargue_detalle WHERE cargue_id = :c ORDER BY id",
                            c=cargue_id)
        for d in detalle:
            try:
                _procesar_fila(cargue_id, d, usuario)
            except Exception as exc:  # una fila rota no debe dejar el lote "En proceso" para siempre
                try:
                    # Solo si sigue 'En cola': si ya quedo Exitoso/Error y fallo
                    # algo despues, el resultado real de Siesa no se pisa.
                    _cerrar_fila(d, "Error", None, None, False,
                                 f"Error interno al procesar: {type(exc).__name__}: {exc}",
                                 solo_en_cola=True)
                except Exception:
                    pass  # la base no responde; el cierre del finally lo reintenta
    finally:
        try:
            _cerrar_cargue(cargue_id)
        finally:
            _cargue_lock.release()


def _cerrar_cargue(cargue_id: int, intentos: int = 3) -> None:
    """Filas que quedaron 'En cola' pasan a Error y el cargue a 'Terminado'."""
    for i in range(intentos):
        try:
            with engine.begin() as conn:
                conn.execute(text("""
                    UPDATE items.cargue_detalle
                       SET estado = 'Error', fecha = SYSUTCDATETIME(),
                           item_mensaje = COALESCE(item_mensaje, 'No se procesó: el cargue se cortó por un error. '
                                          + 'Revisa en Siesa si el item quedó creado.')
                     WHERE cargue_id = :c AND estado = 'En cola'
                """), {"c": cargue_id})
                conn.execute(text("""
                    UPDATE c SET estado = 'Terminado', fecha_fin = SYSUTCDATETIME(),
                           exitosos  = (SELECT COUNT(1) FROM items.cargue_detalle d WHERE d.cargue_id = c.id AND d.estado = 'Exitoso'),
                           con_error = (SELECT COUNT(1) FROM items.cargue_detalle d WHERE d.cargue_id = c.id AND d.estado = 'Error')
                      FROM items.cargues c WHERE c.id = :c
                """), {"c": cargue_id})
            return
        except Exception:
            if i == intentos - 1:
                raise  # queda para recuperar_interrumpidos al proximo arranque
            time.sleep(2 * (i + 1))


def _procesar_fila(cargue_id: int, d: dict, usuario: str | None) -> None:
    quien = f"Siesa (cargue #{cargue_id})"
    s = creacion.cargar(d["solicitud_id"])

    if s["estado"] == "Creado" and s.get("planeacion_estado") == "Cargada":
        # Otro cargue ya la termino: reenviar los parametros podria pisar
        # 'Cargada' con un error falso.
        _cerrar_fila(d, "Exitoso", True, "Ya estaba creado y con parámetros; no se reenvió nada.",
                     True, None)
        return

    # Paso 1: el item. Si un cargue anterior ya lo creo y fallaron solo los
    # parametros, no se vuelve a mandar (el conector diria "exitosa" igual).
    if s["estado"] == "Creado":
        item_ok, item_msg = True, "El item ya estaba creado; solo se cargan los parámetros."
    else:
        r = creacion.crear_en_siesa(d["solicitud_id"], usuario)
        item_ok, item_msg = r["ok"], r["mensaje"]
    if not item_ok:
        _cerrar_fila(d, "Error", item_ok, item_msg, None, None)
        _evento(d["solicitud_id"], ETAPA_APROBACION, f"Cargue #{cargue_id}: {item_msg}", quien)
        return

    # Paso 2: parametros de planeacion, que necesitan el item ya creado.
    payload = client.construir_payload_planeacion(
        d["item_codigo"], d["marca_id"], d["calibre_id"], d["ruta_id"], d["bodega"])
    http, cuerpo = client.crear_parametros_planeacion(
        d["item_codigo"], d["marca_id"], d["calibre_id"], d["ruta_id"], d["bodega"])
    codigo = cuerpo.get("codigo") if isinstance(cuerpo, dict) else None
    param_ok = http == 200 and codigo == 0
    if param_ok:
        param_msg = f"Parámetros asociados: ruta {d['ruta_id']}, bodega {d['bodega']}."
    else:
        param_msg = "Siesa rechazó los parámetros: " + creacion.motivo_legible(cuerpo)

    _cerrar_fila(d, "Exitoso" if param_ok else "Error", item_ok, item_msg, param_ok, param_msg,
                 http=http, codigo=codigo, payload=payload)
    with engine.begin() as conn:
        # El item existe en ambos casos: la solicitud pasa a "Creación de item".
        # Si fallaron los parametros sigue en la lista para reintentar solo eso.
        conn.execute(text("""
            UPDATE items.solicitudes
               SET etapa_actual_id = :etapa, planeacion_estado = :pe, planeacion_mensaje = :pm,
                   fecha_modificado = SYSUTCDATETIME()
             WHERE id = :id
        """), {"etapa": ETAPA_CREACION, "pe": "Cargada" if param_ok else "Error",
               "pm": param_msg[:600], "id": d["solicitud_id"]})
    _evento(d["solicitud_id"], ETAPA_CREACION, f"Cargue #{cargue_id}: {item_msg} {param_msg}", quien)


def _cerrar_fila(d, estado, item_ok, item_msg, param_ok, param_msg,
                 http=None, codigo=None, payload=None, solo_en_cola=False) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE items.cargue_detalle
               SET estado = :estado, item_ok = :iok, item_mensaje = :imsg,
                   param_ok = :pok, param_mensaje = :pmsg, param_http = :http,
                   param_codigo = :cod, param_payload = :payload, fecha = SYSUTCDATETIME()
             WHERE id = :id
        """ + (" AND estado = 'En cola'" if solo_en_cola else "")), {"estado": estado, "iok": item_ok, "imsg": (item_msg or "")[:1000] or None,
               "pok": param_ok, "pmsg": (param_msg or "")[:1000] or None, "http": http,
               "cod": codigo, "id": d["id"],
               "payload": json.dumps(payload, ensure_ascii=False) if payload else None})


def _evento(solicitud_id: int, etapa: int, obs: str, quien: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO items.seguimiento (solicitud_id, etapa_id, observacion, usuario_nombre)
            VALUES (:id, :etapa, :obs, :quien)
        """), {"id": solicitud_id, "etapa": etapa, "obs": obs[:2000], "quien": quien})


def recuperar_interrumpidos() -> None:
    """Al arrancar: un cargue que quedo 'En proceso' murio con el servidor."""
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE items.cargue_detalle
               SET estado = 'Error', fecha = SYSUTCDATETIME(),
                   item_mensaje = COALESCE(item_mensaje, 'Interrumpido: el servidor se reinició '
                                  + 'durante el cargue. Revisa en Siesa si el item quedó creado.')
             WHERE estado = 'En cola'
        """))
        conn.execute(text("""
            UPDATE c SET estado = 'Terminado', fecha_fin = SYSUTCDATETIME(),
                   exitosos  = (SELECT COUNT(1) FROM items.cargue_detalle d WHERE d.cargue_id = c.id AND d.estado = 'Exitoso'),
                   con_error = (SELECT COUNT(1) FROM items.cargue_detalle d WHERE d.cargue_id = c.id AND d.estado = 'Error')
              FROM items.cargues c WHERE c.estado = 'En proceso'
        """))


def historial(limite: int = 50, cargue_id: int | None = None) -> list[dict]:
    return consultar("""
        SELECT TOP (:n) c.id, c.fecha, c.fecha_fin, c.usuario, c.estado, c.total,
               (SELECT COUNT(1) FROM items.cargue_detalle d WHERE d.cargue_id = c.id AND d.estado = 'Exitoso') AS exitosos,
               (SELECT COUNT(1) FROM items.cargue_detalle d WHERE d.cargue_id = c.id AND d.estado = 'Error')   AS con_error
          FROM items.cargues c
         WHERE (:id IS NULL OR c.id = :id)
         ORDER BY c.id DESC
    """, n=limite, id=cargue_id)


def detalle_cargue(cargue_id: int) -> dict | None:
    cab = historial(1, cargue_id)
    if not cab:
        return None
    filas = consultar("""
        SELECT d.id, d.solicitud_id, d.referencia, b.descripcion AS item_base, d.item_codigo,
               d.marca_id, m.descripcion AS marca, d.calibre_id, d.ruta_id, d.bodega,
               d.estado, d.item_ok, d.item_mensaje, d.param_ok, d.param_mensaje,
               d.param_http, d.param_codigo, d.fecha
          FROM items.cargue_detalle d
          LEFT JOIN items.cat_items_base b ON b.referencia = d.referencia
          LEFT JOIN items.cat_marcas m     ON m.id = d.marca_id
         WHERE d.cargue_id = :c ORDER BY d.id
    """, c=cargue_id)
    return {"cargue": cab[0], "filas": filas}
