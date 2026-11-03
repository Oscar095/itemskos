# -*- coding: utf-8 -*-
"""
Cliente de las APIs de Siesa Enterprise (Connekta v3) de KOS Colombia.

Adaptado de siesa_api.py (el script original de creacion masiva) para leer
la configuracion de app.config.settings en vez de un .env.txt suelto. La
logica de red y el contrato del conector son EXACTAMENTE los mismos, ya
verificados contra el servicio real el 2026-09-02/03 — ver las notas abajo,
son el resultado de varias horas de prueba y error, no adivinanza.

NOTAS DE CAMPO:

  * `paginacion=numPag=...` rompe las consultas (HTTP 500, ORDER BY invalido).
    Nunca se manda.
  * La respuesta es UTF-8 sin charset en el header: hay que decodificar a mano.
  * El endpoint de importacion es POST unicamente (405 a GET).
  * Contrato del POST (plano de ancho fijo, registro tipo 121):
      F_CIA               = "1"        (no el 7501 de la URL, que es la clave Connekta)
      F_ACTUALIZA_REG     = "0"        obligatorio y NUMERICO
      f121_fecha_creacion = "yyyyMMdd" 8 posiciones exactas
      f120_id                          vacio se resuelve por f120_referencia
    HTTP 200 / codigo 0 significa "el conector acepto el plano", NO "inserto
    una fila nueva": responde igual si la combinacion ya existia. La unica
    forma de confirmar una insercion es comparar el catalogo antes/despues.

  * koscolombia_Items_odoo_crm tenia un EXISTS que ocultaba items sin costo
    (incluidos los recien creados). Corregido en
    sql/koscolombia_Items_odoo_crm_v2.sql, pero con la columna de costo
    tardaba ~10 min (564 s el 2026-10-31).
  * Desde el 2026-11-03 va SIN costo y responde en ~1 s (9.859 filas): la
    plataforma la consulta en vivo para detectar duplicados
    (app.siesa.extensiones). La copia cat_extensiones_existentes queda de
    respaldo por si Siesa no responde.
"""
import json
import time
from datetime import date

import requests

from app.config import settings

TIMEOUT = 900  # margen para los conectores de escritura; la consulta de items ya no lo necesita

CONSULTAS = {
    "ext1": "koscolombia_ext1_odoo",
    "ext2": "koscolombia_ext2_Odoo",
    "items": settings.siesa_consulta_items,   # ~1 s desde el 2026-11-03 (antes ~10 min)
    "rutas": "koscolombia_MF_Rutas",   # ~0.5s, 64 rutas (f808_id viene con relleno a 20)
}
URL_CONSULTA = "https://servicios.siesacloud.com/api/connekta/v3/ejecutarconsulta"


def _headers():
    return {
        "ConniKey": settings.siesa_conni_key,
        "ConniToken": settings.siesa_conni_token,
        "Content-Type": "application/json",
    }


def consultar(clave: str, reintentos: int = 3,
              timeout: float | tuple[float, float] = TIMEOUT) -> list[dict]:
    """Ejecuta una consulta guardada de Connekta y devuelve detalle.Table."""
    descripcion = CONSULTAS.get(clave, clave)
    url = f"{URL_CONSULTA}?idCompania={settings.siesa_id_compania}&descripcion={descripcion}"
    ultimo = None
    for intento in range(1, reintentos + 1):
        try:
            r = requests.get(url, headers=_headers(), timeout=timeout)
            if r.status_code != 200:
                ultimo = f"HTTP {r.status_code}: {r.text[:300]}"
            else:
                data = json.loads(r.content.decode("utf-8"))
                if data.get("codigo") != 0:
                    ultimo = f"codigo={data.get('codigo')} {data.get('mensaje')}"
                else:
                    return data["detalle"]["Table"]
        except Exception as exc:
            ultimo = f"{type(exc).__name__}: {exc}"
        if intento < reintentos:
            time.sleep(2 * intento)
    raise RuntimeError(f"Consulta '{descripcion}' fallo tras {reintentos} intentos -> {ultimo}")


def construir_payload_creacion(referencia: str, ext1_id: str, ext2_id: str) -> dict:
    """Arma el JSON del POST con el contrato ya confirmado (ver docstring del modulo)."""
    registro = {
        "F_CIA": "1",
        "F_ACTUALIZA_REG": "0",
        "f120_id": "",
        "f120_referencia": referencia,
        "f121_id_ext1_detalle": ext1_id,
        "f121_id_ext2_detalle": ext2_id,
        "f121_ind_estado": "1",
        "f121_fecha_inactivacion": "",
        "f121_fecha_creacion": date.today().strftime("%Y%m%d"),
        "f120_id_item_ext_generico": "",
        "f120_referencia_item_ext_gen": "",
        "f121_id_ext1_detalle_gen": "",
        "f121_id_ext2_detalle_gen": "",
    }
    return {"Inicial": [{"F_CIA": "1"}], "Version": [registro], "Final": [{"F_CIA": "1"}]}


# --- Conector "Creacion Extensiones" (idDocumento 260981), alta de marcas en Ext1.
#
# Contrato verificado contra el servicio el 2026-10-31 con payloads que no crean nada:
#   * 6 campos obligatorios + f116_descripcion_corta opcional. Anchos: f116_id 2,
#     descripciones 40, cortas 9, f116_id_ext_detalle 20. Si se pasan, responde
#     400 "Error en la Estructura" sin tocar Siesa.
#   * f116_tipo_extension elige el stored procedure: con "9" responde
#     "sp_extension_existe no existe". Solo 1 (Ext1) o 2 (Ext2).
#   * idSistema debe ser entero (vacio o texto -> 400 de formato).
#   * f116_descripcion es la del ENCABEZADO de la extension, no la de la marca.
#     Se manda siempre la que ya tiene MK en Siesa para no renombrarlo.
EXT1_TIPO = "1"
EXT1_ID = "MK"
EXT1_DESCRIPCION = "MARCA KOS"
ANCHO_DESCRIPCION = 40
ANCHO_CORTA = 9


def construir_payload_marca(marca_id: str, descripcion: str) -> dict:
    return {"Version": [{
        "f116_tipo_extension": EXT1_TIPO,
        "f116_id": EXT1_ID,
        "f116_descripcion": EXT1_DESCRIPCION,
        "f116_descripcion_corta": EXT1_DESCRIPCION[:ANCHO_CORTA],
        "f116_id_ext_detalle": marca_id,
        "f116_descripcion_detalle": descripcion[:ANCHO_DESCRIPCION],
        # Igual que las marcas creadas a mano: los primeros 9 caracteres.
        "f116_descripcion_detalle_corta": descripcion[:ANCHO_CORTA],
    }]}


def crear_marca(marca_id: str, descripcion: str) -> tuple[int | None, dict | str]:
    """POST al conector de extensiones. Devuelve (http_status, cuerpo)."""
    url = settings.siesa_api_creacion_marcas.replace("{idSistema}", settings.siesa_id_sistema)
    payload = construir_payload_marca(marca_id, descripcion)
    try:
        r = requests.post(url, headers=_headers(), data=json.dumps(payload), timeout=120)
        try:
            cuerpo = json.loads(r.content.decode("utf-8"))
        except Exception:
            cuerpo = r.content.decode("utf-8", errors="replace")
        return r.status_code, cuerpo
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def crear_extension(referencia: str, ext1_id: str, ext2_id: str) -> tuple[int | None, dict | str]:
    """POST al conector de importacion. Devuelve (http_status, cuerpo)."""
    payload = construir_payload_creacion(referencia, ext1_id, ext2_id)
    try:
        r = requests.post(settings.siesa_api_creacion_items, headers=_headers(),
                           data=json.dumps(payload), timeout=TIMEOUT)
        try:
            cuerpo = json.loads(r.content.decode("utf-8"))
        except Exception:
            cuerpo = r.content.decode("utf-8", errors="replace")
        return r.status_code, cuerpo
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


# --- Conector "PARAMETROS_ITEMS_V5" (idDocumento 261373), parametros de planeacion.
#
# Contrato verificado contra el servicio el 2026-10-31 con payloads que no tocan nada:
#   * La seccion se llama "Versión" CON tilde ("Version" -> "la seccion no existe").
#     Los nombres de campo llevan espacios y tilde tal cual. Por eso el cuerpo se
#     manda en UTF-8 con ensure_ascii=False.
#   * Anchos: Ruta 20, Bodega de asignación 5, Codigo item 7 (es el f120_id
#     NUMERICO, no la referencia: KPT0009347 no cabe), Extension 1/2 20.
#   * La respuesta viene en latin-1, no UTF-8 como las demas.
#   * Genera registros tipo 132 (parametros del item por instalacion). Validaciones
#     confirmadas (2026-10-31, tras corregir el conector en Connekta), devuelven 400
#     sin escribir nada:
#       "Items parametros: El item - extensión no existe."   (codigo + ext1 + ext2)
#       "Items parametros: La ruta no es valida."
#       "Items parametros: La bodega de asignación no es valida."
#     "VASO 12 OZ" (con espacios), 020 y 018 pasan la validacion.
#   * El conector agrega por su cuenta la unidad de medida "UND"; ver la nota de
#     prueba en ARQUITECTURA.md.
SECCION_PLANEACION = "Versión"
ANCHO_RUTA = 20
BODEGAS_ASIGNACION = ("020", "018")


def _decodificar(contenido: bytes):
    try:
        texto = contenido.decode("utf-8")
    except UnicodeDecodeError:
        texto = contenido.decode("latin-1")
    try:
        return json.loads(texto)
    except Exception:
        return texto


def construir_payload_planeacion(item_codigo: int, ext1_id: str, ext2_id: str,
                                 ruta: str, bodega: str) -> dict:
    return {SECCION_PLANEACION: [{
        "Ruta": ruta.strip()[:ANCHO_RUTA],
        "Bodega de asignación": bodega,
        "Codigo item": str(item_codigo),
        "Extension 1": ext1_id,
        "Extension 2": ext2_id,
    }]}


def crear_parametros_planeacion(item_codigo: int, ext1_id: str, ext2_id: str,
                                ruta: str, bodega: str) -> tuple[int | None, dict | str]:
    """POST al conector de parametros de planeacion. Devuelve (http_status, cuerpo)."""
    payload = construir_payload_planeacion(item_codigo, ext1_id, ext2_id, ruta, bodega)
    try:
        r = requests.post(settings.siesa_api_param_planeacion, headers=_headers(),
                          data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                          timeout=120)
        return r.status_code, _decodificar(r.content)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
