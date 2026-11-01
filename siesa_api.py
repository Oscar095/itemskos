# -*- coding: utf-8 -*-
"""
Cliente minimo para las APIs de Siesa Enterprise (Connekta v3) de KOS Colombia.

NOTAS DE CAMPO (verificadas contra el servicio en vivo):

  * El parametro `paginacion=numPag=1|tamPag=100` que trae el .env.txt ROMPE las
    consultas: devuelve HTTP 500 con
      "The ORDER BY clause is invalid in views, inline functions, derived tables,
       subqueries, and common table expressions, unless TOP, OFFSET or FOR XML
       is also specified."
    Por eso `consultar()` arma la URL sin `paginacion` y trae el set completo.

  * La respuesta viene como {"codigo":0,"mensaje":"...","detalle":{"Table":[...]}}
    en UTF-8, pero sin charset en el header. Hay que decodificar a mano
    (r.content.decode('utf-8')) o los acentos salen corruptos.

  * El endpoint de importacion responde 405 a GET: es POST unicamente.

CONTRATO DEL POST (descubierto probando contra el conector API_v1_ItemsExtensiones):

  El conector NO consume el JSON tal cual: lo convierte a un plano de ancho fijo,
  registro tipo 121 (t121_mc_items_ext), subtipo 0, version 3. De ahi que sea
  estricto con formatos y anchos. Lo confirmado:

    F_CIA               = "1"       (las consultas devuelven f_id_cia=1; el 7501 de
                                     la URL es la clave Connekta, no la compania)
    F_ACTUALIZA_REG     = "0"       OBLIGATORIO Y NUMERICO. Con "" responde
                                    "Se esperaba un dato numerico en el campo
                                     'F_ACTUALIZA_REG'."
    f121_fecha_creacion = "yyyyMMdd" 8 posiciones (126-134 del plano). Con
                                    "yyyy-MM-dd" corta a "2026-09-" y responde
                                    "El dato debe ser una fecha valida o vacio."
    f120_id             = campo NUMERICO de 7 posiciones; vacio se envia como
                                    "0000000" y entonces el item se resuelve por
                                    f120_referencia (el conector arma la clave
                                    como "f120_id-f120_referencia").

  Validaciones que SI hace el conector (devuelven HTTP 400, no crean nada):
    - "Extenciones: el item no existe."                      (f120_referencia invalida)
    - "Extenciones: la extension 1 / 2 no existe."            (ext1/ext2 invalidas)
    - "Extenciones: item parametrizado para no manejar extensiones."

  OJO: un payload valido responde HTTP 200 {"codigo":0,"detalle":"Importacion exitosa"}
  tanto si inserto como si no hizo nada. La unica prueba real es volver a consultar.

HISTORIA DE LA CONSULTA DE ITEMS (por que hay cache)

  koscolombia_Items_odoo_crm tenia un EXISTS contra t470_cm_movto_invent que exigia
  al menos un movimiento de inventario con costo. Devolvia 2442 filas y ocultaba
  toda extension sin costo, incluidas las recien creadas: por eso al principio era
  imposible verificar una creacion contra el API.

  Ya corregida (ver sql/koscolombia_Items_odoo_crm_v2.sql) devuelve 6983 filas,
  4541 de ellas con COSTO PROM UNIT en NULL, y si sirve para verificar.

  El costo: tarda ~353 segundos. Por eso `consultar()` guarda en cache/ y los
  scripts aceptan --usar-cache. Si vuelve a dar timeout, aplicar la v2 del SQL
  (o el indice sobre t470 que se sugiere ahi).
"""
import json
import os
import re
import time
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env.txt"

TIMEOUT = int(os.environ.get("SIESA_TIMEOUT", "600"))  # koscolombia_Items_odoo_crm ya corregida tarda ~350s


def cargar_env(path=ENV_PATH):
    """Lee el .env.txt tolerando espacios alrededor del '=' y el bloque JSON del final."""
    cfg = {}
    for linea in Path(path).read_text(encoding="utf-8-sig").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or linea.startswith("{"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$", linea)
        if m:
            cfg[m.group(1)] = m.group(2).strip()
    return cfg


CFG = cargar_env()

HEADERS = {
    "ConniKey": CFG["ConniKey"],
    "ConniToken": CFG["ConniToken"],
    "Content-Type": "application/json",
}

# Nombres de las consultas guardadas, extraidos del .env.txt
CONSULTAS = {
    "ext1": "koscolombia_ext1_odoo",
    "ext2": "koscolombia_ext2_Odoo",
    "items": "koscolombia_Items_odoo_crm",
}

URL_CONSULTA = "https://servicios.siesacloud.com/api/connekta/v3/ejecutarconsulta"
ID_COMPANIA = "7501"


def _url_consulta(descripcion):
    return f"{URL_CONSULTA}?idCompania={ID_COMPANIA}&descripcion={descripcion}"


CACHE_DIR = BASE_DIR / "cache"


def _ruta_cache(clave):
    return CACHE_DIR / ("%s.json" % clave)


def consultar(clave, reintentos=3, usar_cache=False, max_edad=3600):
    """
    Ejecuta una consulta guardada y devuelve la lista de filas (detalle.Table).

    Toda consulta exitosa se guarda en cache/. Con usar_cache=True se reutiliza
    el archivo si tiene menos de `max_edad` segundos. Importa porque
    koscolombia_Items_odoo_crm puede tardar varios minutos: sin cache, analizar.py
    y crear.py la piden por separado y se duplica la espera.
    """
    descripcion = CONSULTAS.get(clave, clave)
    if usar_cache:
        ruta = _ruta_cache(clave)
        if ruta.exists() and (time.time() - ruta.stat().st_mtime) < max_edad:
            edad = int(time.time() - ruta.stat().st_mtime)
            print("  (cache: %s, %ds de antiguedad)" % (ruta.name, edad))
            return json.loads(ruta.read_text(encoding="utf-8"))

    url = _url_consulta(descripcion)
    ultimo = None
    for intento in range(1, reintentos + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                ultimo = f"HTTP {r.status_code}: {r.text[:300]}"
            else:
                data = json.loads(r.content.decode("utf-8"))
                if data.get("codigo") != 0:
                    ultimo = f"codigo={data.get('codigo')} {data.get('mensaje')} {data.get('detalle')}"
                else:
                    filas = data["detalle"]["Table"]
                    CACHE_DIR.mkdir(exist_ok=True)
                    _ruta_cache(clave).write_text(
                        json.dumps(filas, ensure_ascii=False), encoding="utf-8")
                    return filas
        except Exception as exc:  # red intermitente
            ultimo = f"{type(exc).__name__}: {exc}"
        if intento < reintentos:
            time.sleep(2 * intento)
    raise RuntimeError(f"Consulta '{descripcion}' fallo tras {reintentos} intentos -> {ultimo}")


def importar(payload, reintentos=1):
    """POST al conector de importacion estandar. Devuelve (http_status, json_o_texto)."""
    url = CFG["API_CREACION_ITEMS"]
    ultimo = None
    for intento in range(1, reintentos + 1):
        try:
            r = requests.post(url, headers=HEADERS, data=json.dumps(payload), timeout=TIMEOUT)
            try:
                cuerpo = json.loads(r.content.decode("utf-8"))
            except Exception:
                cuerpo = r.content.decode("utf-8", errors="replace")
            return r.status_code, cuerpo
        except Exception as exc:
            ultimo = f"{type(exc).__name__}: {exc}"
            if intento < reintentos:
                time.sleep(2 * intento)
    return None, ultimo
