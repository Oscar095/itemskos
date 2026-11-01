# -*- coding: utf-8 -*-
"""
Marcas (Ext1 / MK): catalogo al dia y alta de marcas nuevas en Siesa.

Por que el catalogo se refresca aqui y no solo con app.siesa.sync:

  La consulta koscolombia_ext1_odoo tarda ~2 s (la lenta es la de items), y las
  marcas se siguen creando a mano en Siesa a diario. Con items.cat_marcas
  congelada en la ultima corrida de sync, el vendedor no ve las marcas nuevas,
  pide crearla otra vez y queda duplicada (paso con NOOK: K1949 y K1968).
  Ademas solicitudes.marca_id tiene FK a cat_marcas: una marca que existe en
  Siesa pero no en la cache no se podria ni guardar.

  Por eso refrescar() trae Ext1 en vivo y hace upsert, nunca DELETE (la FK lo
  impide y las marcas no se borran en Siesa).

El consecutivo (verificado contra el catalogo en vivo el 2026-10-31):

  * Los codigos son K/k + numero, y la numeracion es UNA sola compartida por
    ambas letras (K2005 -> k2006 -> ... -> k2018, sin solapes).
  * Existe ademas un bloque K4000-K4077 de cargas masivas (2023 y 2026-09-02)
    que NO es parte del consecutivo diario. Se ignora con TOPE_CONSECUTIVO.
  * Las marcas nuevas se crean con K mayuscula (decision del 2026-10-31).

El conector, como el de items, puede responder "exitosa" sin haber insertado.
Por eso despues del POST se vuelve a consultar Ext1 y solo se da por creada
si el codigo aparece alla.
"""
import json
import re
import threading
import time

from sqlalchemy import text

from app.db.session import consultar, engine
from app.siesa import client
from app.siesa.matcher import norm

PREFIJO = "K"
TOPE_CONSECUTIVO = 4000          # desde aqui es el bloque de cargas masivas
REFRESCO_SEGUNDOS = 300

_PATRON_ID = re.compile(r"^[Kk]\s*(\d+)$")
_lock_refresco = threading.Lock()
# Serializa las altas dentro del proceso: dos vendedores creando a la vez
# calcularian el mismo consecutivo.
_lock_creacion = threading.Lock()
_ultimo_refresco = 0.0


class ErrorMarca(Exception):
    """Error con mensaje apto para mostrarse al vendedor."""


def limpiar_descripcion(texto: str) -> str:
    """Como se guardan en Siesa: mayusculas y espacios simples."""
    return " ".join((texto or "").split()).upper()


def _filas_ext1() -> list[dict]:
    return [{"id": f["f117_id"].strip(), "descripcion": f["f117_descripcion"].strip(),
             "fecha_siesa": f.get("f117_ts")}
            for f in client.consultar("ext1")]


def _upsert(filas: list[dict]):
    """Inserta las marcas que faltan y corrige descripciones cambiadas en Siesa."""
    if not filas:
        return
    with engine.begin() as conn:
        # La conexion viene del pool: si una carga anterior fallo a medias, la
        # tabla temporal sigue viva en esta sesion.
        conn.execute(text("IF OBJECT_ID('tempdb..#ext1') IS NOT NULL DROP TABLE #ext1"))
        conn.execute(text("CREATE TABLE #ext1 (id NVARCHAR(20) COLLATE DATABASE_DEFAULT PRIMARY KEY, "
                          "descripcion NVARCHAR(200), fecha_siesa DATETIME2)"))
        # 3 parametros por fila; SQL Server admite 2100 por sentencia.
        for i in range(0, len(filas), 600):
            trozo = filas[i:i + 600]
            valores = ", ".join(f"(:i{n}, :d{n}, :f{n})" for n in range(len(trozo)))
            params = {}
            for n, f in enumerate(trozo):
                params.update({f"i{n}": f["id"], f"d{n}": f["descripcion"], f"f{n}": f["fecha_siesa"]})
            conn.execute(text(f"INSERT INTO #ext1 (id, descripcion, fecha_siesa) VALUES {valores}"), params)
        conn.execute(text("""
            MERGE items.cat_marcas AS t
            USING #ext1 AS s ON t.id = s.id
            WHEN MATCHED AND (t.descripcion <> s.descripcion
                              OR ISNULL(t.fecha_siesa, '19000101') <> ISNULL(s.fecha_siesa, '19000101'))
                THEN UPDATE SET descripcion = s.descripcion, fecha_siesa = s.fecha_siesa,
                                actualizado = SYSUTCDATETIME()
            WHEN NOT MATCHED BY TARGET
                THEN INSERT (id, descripcion, fecha_siesa) VALUES (s.id, s.descripcion, s.fecha_siesa);
        """))
        conn.execute(text("DROP TABLE #ext1"))


def refrescar(forzar: bool = False) -> list[dict] | None:
    """
    Trae Ext1 de Siesa y actualiza items.cat_marcas. Devuelve las filas en vivo,
    o None si no hizo falta (cache fresca) o si Siesa fallo: el selector sigue
    funcionando con la cache, que es mejor que dejarlo vacio.
    """
    global _ultimo_refresco
    if not forzar and time.time() - _ultimo_refresco < REFRESCO_SEGUNDOS:
        return None
    with _lock_refresco:
        if not forzar and time.time() - _ultimo_refresco < REFRESCO_SEGUNDOS:
            return None   # otro request lo refresco mientras se esperaba el lock
        try:
            filas = _filas_ext1()
        except RuntimeError:
            if forzar:
                raise
            return None
        _upsert(filas)
        _ultimo_refresco = time.time()
        return filas


def siguiente_id(filas: list[dict]) -> str:
    numeros = [int(m.group(1)) for f in filas
               if (m := _PATRON_ID.match(f["id"])) and int(m.group(1)) < TOPE_CONSECUTIVO]
    return f"{PREFIJO}{max(numeros, default=0) + 1}"


def iguales(descripcion: str, filas: list[dict]) -> list[dict]:
    """Marcas que ya se llaman igual (sin distinguir acentos, signos ni mayusculas)."""
    clave = norm(descripcion)
    return [f for f in filas if norm(f["descripcion"]) == clave]


def _registrar(usuario, marca_id, descripcion, http, codigo, mensaje, payload):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO items.log_marcas
                (usuario_web, marca_id, descripcion, http_status, codigo_conector, mensaje, payload_enviado)
            VALUES (:usuario, :id, :desc, :http, :codigo, :mensaje, :payload)
        """), {"usuario": usuario, "id": marca_id, "desc": descripcion, "http": http,
               "codigo": codigo, "mensaje": (mensaje or "")[:3000] or None,
               "payload": json.dumps(payload, ensure_ascii=False) if payload else None})


def _motivo(cuerpo) -> str:
    if isinstance(cuerpo, dict) and isinstance(cuerpo.get("detalle"), list):
        partes = [(d.get("f_detalle") or "").strip() for d in cuerpo["detalle"] if isinstance(d, dict)]
        partes = [p for p in dict.fromkeys(partes) if p and not p.startswith("Advertencia")]
        if partes:
            return " | ".join(partes)[:600]
    if isinstance(cuerpo, dict):
        return f"{cuerpo.get('mensaje', '')} {cuerpo.get('detalle', '')}".strip()[:600]
    return str(cuerpo)[:600]


def vista_previa(descripcion: str) -> dict:
    """Lo que pasaria al crear, sin crear nada: codigo que tocaria y duplicados."""
    desc = limpiar_descripcion(descripcion)
    filas = refrescar(forzar=True)
    return {"descripcion": desc, "id_propuesto": siguiente_id(filas),
            "existentes": iguales(desc, filas) if desc else []}


def crear(descripcion: str, usuario: str | None = None) -> dict:
    """
    Da de alta la marca en Ext1 con el siguiente consecutivo y la deja en
    items.cat_marcas. Lanza ErrorMarca con un mensaje legible si no se pudo.
    """
    desc = limpiar_descripcion(descripcion)
    if not desc:
        raise ErrorMarca("Escribe el nombre de la marca.")
    if len(desc) > client.ANCHO_DESCRIPCION:
        raise ErrorMarca(f"El nombre tiene {len(desc)} caracteres; Siesa admite "
                         f"{client.ANCHO_DESCRIPCION}.")

    with _lock_creacion:
        # Siempre contra Siesa en vivo, no contra la cache: alguien pudo crearla
        # a mano hace un minuto, o haber usado ya el consecutivo.
        try:
            filas = refrescar(forzar=True)
        except RuntimeError as exc:
            raise ErrorMarca(f"No se pudo consultar Ext1 en Siesa: {exc}") from exc

        ya = iguales(desc, filas)
        if ya:
            codigos = ", ".join(f"{f['id']} ({f['descripcion']})" for f in ya)
            raise ErrorMarca(f"La marca ya existe en Siesa: {codigos}. Selecciónala de la lista.")

        marca_id = siguiente_id(filas)
        payload = client.construir_payload_marca(marca_id, desc)
        http, cuerpo = client.crear_marca(marca_id, desc)
        codigo = cuerpo.get("codigo") if isinstance(cuerpo, dict) else None

        if not (http == 200 and codigo == 0):
            msg = f"Siesa rechazó la creación: {_motivo(cuerpo)}"
            _registrar(usuario, marca_id, desc, http, codigo, msg, payload)
            raise ErrorMarca(msg)

        # Confirmacion real: el codigo tiene que aparecer en Ext1.
        try:
            despues = refrescar(forzar=True)
        except RuntimeError:
            despues = None
        nueva = next((f for f in despues or [] if f["id"].upper() == marca_id.upper()), None)
        if not nueva:
            msg = (f"Siesa respondió 'exitosa' pero {marca_id} no aparece en Ext1. "
                   f"Revisar en Siesa antes de reintentar.")
            _registrar(usuario, marca_id, desc, http, codigo, msg, payload)
            raise ErrorMarca(msg)

        msg = f"Marca creada en Siesa: {nueva['id']} {nueva['descripcion']}."
        _registrar(usuario, nueva["id"], nueva["descripcion"], http, codigo, msg, payload)
        return {"id": nueva["id"], "descripcion": nueva["descripcion"], "mensaje": msg}
