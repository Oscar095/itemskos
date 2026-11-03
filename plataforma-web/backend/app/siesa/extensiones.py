# -*- coding: utf-8 -*-
"""
Items-extension que ya existen en Siesa, consultados EN VIVO.

Hasta el 2026-11-03 la plataforma solo miraba items.cat_extensiones_existentes,
una copia que se refresca con el sync manual: la consulta de items tardaba
~10 min por la columna de costo y no se podia llamar en cada validacion. Lo
creado en Siesa despues del ultimo sync no se veia y se podia volver a pedir.

Sin el costo la consulta responde en ~1 s (9.859 filas, ~1 MB): se trae
completa, se indexa por (referencia, marca, calibre) y se guarda en memoria
TTL_SEGUNDOS para no consultar Siesa en cada cambio del formulario. Guardar,
aprobar o cargar una solicitud pide el dato fresco (forzar=True).

Si Siesa no responde (o devuelve algo inservible) se usa la copia, y el
resultado lo dice (fuente="copia") para no afirmar algo que no se verifico.
"""
import logging
import threading
import time

from app.db.session import consultar
from app.siesa import client

TTL_SEGUNDOS = 60        # el formulario verifica en cada cambio de item/marca/calibre
ESPERA_TRAS_FALLO = 30   # con Siesa caido no se le insiste en cada request
# (conectar, esperar respuesta). Medido el 2026-11-03: 16 de 17 llamadas entre
# 0,9 y 1,2 s y una de 27,7 s. Con el tope, un pico cae a la copia en vez de
# dejar al vendedor esperando.
TIMEOUT_SEGUNDOS = (5, 15)

_log = logging.getLogger(__name__)
_lock = threading.Lock()
_cache = {"t": 0.0, "indice": None, "fallo": 0.0}


def _clave(referencia, marca_id, calibre_id) -> tuple:
    # Igual que compara SQL Server (collation CI): sin mayusculas ni espacios de relleno.
    return tuple((v or "").strip().upper() for v in (referencia, marca_id, calibre_id))


def _indice(forzar: bool) -> dict:
    """{(ref, marca, calibre): (sku, estado)} de Siesa. RuntimeError si Siesa no sirve."""
    with _lock:
        ahora = time.time()
        if not forzar and _cache["indice"] is not None and ahora - _cache["t"] < TTL_SEGUNDOS:
            return _cache["indice"]
        if ahora - _cache["fallo"] < ESPERA_TRAS_FALLO:
            raise RuntimeError("Siesa no respondió hace instantes")
        try:
            filas = client.consultar("items", reintentos=1, timeout=TIMEOUT_SEGUNDOS)
            if not filas:
                # Una consulta mal editada en Connekta haria pasar todo por "nuevo".
                raise RuntimeError("la consulta de items vino vacía")
            indice = {_clave(f["REFERENCIA"], f["MARCA ID"], f["CALIBRE"]):
                      (f["SKU_SIESA"], f.get("ESTADO EXT")) for f in filas}
        except Exception as exc:
            _cache["fallo"] = time.time()
            _log.warning("Duplicados contra la copia del catálogo: %s", exc)
            raise RuntimeError(str(exc)) from exc
        _cache.update(t=time.time(), indice=indice, fallo=0.0)
        return indice


def sku_existente(referencia: str, marca_id: str, calibre_id: str, forzar: bool = False) -> dict:
    """
    El SKU de esa combinacion si ya existe en Siesa:
    {"sku": int|None, "activo": bool|None, "fuente": "siesa" | "copia"}.
    """
    try:
        sku, estado = _indice(forzar).get(_clave(referencia, marca_id, calibre_id), (None, None))
        fuente = "siesa"
    except RuntimeError:
        filas = consultar("""
            SELECT TOP 1 sku_siesa, estado_ext FROM items.cat_extensiones_existentes
             WHERE referencia = :ref AND marca_id = :marca AND calibre_id = :cal
        """, ref=referencia, marca=marca_id, cal=calibre_id)
        sku, estado = (filas[0]["sku_siesa"], filas[0]["estado_ext"]) if filas else (None, None)
        fuente = "copia"
    activo = None if sku is None or estado is None else str(estado).strip() == "1"
    return {"sku": sku, "activo": activo, "fuente": fuente}
