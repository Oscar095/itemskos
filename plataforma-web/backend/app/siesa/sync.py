# -*- coding: utf-8 -*-
"""
Refresca las tablas items.cat_* con los catalogos de Siesa.

Se corre como job (o a mano) porque la consulta de items tarda ~350s contra
Siesa: la web no puede llamarla en vivo cada vez que alguien abre un dropdown.

    python -m app.siesa.sync              # consulta Siesa en vivo (lento)
    python -m app.siesa.sync --cache      # reusa el cache JSON local (rapido)

Marcas, calibres e items base se refrescan con MERGE (altas y cambios, nunca
bajas): items.solicitudes tiene FK a las tres, asi que un DELETE falla en cuanto
existe una sola solicitud. Solo cat_extensiones_existentes, que nadie
referencia, se borra y reinserta completa. Todo en una transaccion.
"""
import argparse
import json
import sys
from pathlib import Path

import pymssql

from app.config import settings
from app.siesa import client

# .../Creacion items/cache — el mismo cache que ya usan analizar.py / crear.py
CACHE_DIR = Path(__file__).resolve().parents[4] / "cache"


def _insertar(cur, tabla: str, columnas: list[str], filas: list[tuple], lote: int = 500):
    """
    Inserta en lotes multi-fila.

    executemany() de pymssql manda una sentencia por fila; contra Azure SQL eso
    son ~9.000 viajes de red y la carga se va a varios minutos. Agrupando en
    INSERT ... VALUES (...),(...),(...) baja a unas pocas decenas de viajes.
    El limite de SQL Server es 1000 filas por INSERT y 2100 parametros, de ahi
    el tamano de lote conservador.
    """
    if not filas:
        return
    cols = ", ".join(columnas)
    marcadores = "(" + ", ".join(["%s"] * len(columnas)) + ")"
    por_lote = max(1, min(lote, 2000 // len(columnas)))
    for i in range(0, len(filas), por_lote):
        trozo = filas[i:i + por_lote]
        valores = ", ".join([marcadores] * len(trozo))
        planos = [v for fila in trozo for v in fila]
        cur.execute(f"INSERT INTO {tabla} ({cols}) VALUES {valores}", tuple(planos))


def _merge(cur, tabla: str, columnas: list[str], clave: str, filas: list[tuple],
           conservar: tuple[str, ...] = ()):
    """
    Upsert via tabla temporal. Las columnas de `conservar` no se pisan con NULL:
    asi un item_id digitado por el planeador sobrevive si Siesa no lo trae.
    """
    tmp = "#sync_" + tabla.split(".")[-1]
    cur.execute(f"IF OBJECT_ID('tempdb..{tmp}') IS NOT NULL DROP TABLE {tmp}")
    cur.execute(f"SELECT TOP 0 {', '.join(columnas)} INTO {tmp} FROM {tabla}")
    _insertar(cur, tmp, columnas, filas)
    otras = [c for c in columnas if c != clave]
    asignar = ", ".join(
        f"{c} = COALESCE(s.{c}, t.{c})" if c in conservar else f"{c} = s.{c}" for c in otras)
    cur.execute(f"""
        MERGE {tabla} AS t
        USING {tmp} AS s ON t.{clave} = s.{clave}
        WHEN MATCHED THEN UPDATE SET {asignar}, actualizado = SYSUTCDATETIME()
        WHEN NOT MATCHED BY TARGET THEN
            INSERT ({', '.join(columnas)}) VALUES ({', '.join('s.' + c for c in columnas)});
    """)
    cur.execute(f"DROP TABLE {tmp}")


def _cargar(clave: str, usar_cache: bool) -> list[dict]:
    if usar_cache:
        ruta = CACHE_DIR / f"{clave}.json"
        if ruta.exists():
            print(f"  {clave}: cache {ruta.name}")
            return json.loads(ruta.read_text(encoding="utf-8"))
        print(f"  {clave}: sin cache, consultando Siesa...")
    return client.consultar(clave)


def sincronizar(usar_cache: bool = False) -> dict:
    print("Trayendo catalogos de Siesa...")
    ext1 = _cargar("ext1", usar_cache)
    ext2 = _cargar("ext2", usar_cache)
    items = _cargar("items", usar_cache)
    print(f"  ext1={len(ext1)}  ext2={len(ext2)}  items={len(items)}")

    # --- marcas: puede haber varios codigos con la misma descripcion
    #     (EMA, 20 DE JULIO, CORRAL VAINILLA). Se cargan TODOS; el desempate
    #     por fecha lo hace quien consulta, no esta carga.
    # Por id unico: MERGE falla si la fuente repite una clave.
    marcas = list({f["f117_id"].strip(): (f["f117_id"].strip(), f["f117_descripcion"].strip(), f["f117_ts"])
                   for f in ext1}.values())

    calibres = list({f["f119_id"].strip(): (f["f119_id"].strip(), f["f119_descripcion"].strip())
                     for f in ext2}.values())

    # --- items base: una fila por REFERENCIA unica. 'ITEM ID' (f120_id) lo pide
    #     el conector de parametros de planeacion; si viene vacio, el MERGE
    #     conserva el que el planeador ya digito a mano.
    base = {}
    for f in items:
        ref = f["REFERENCIA"].strip()
        base[ref] = [ref, f["DESCRIPCION"].strip(), f.get("TIPO ITEM"), f.get("ITEM ID")]

    # --- extensiones (SKUs). MARCA ID puede no venir si la consulta vieja
    #     sigue publicada; en ese caso queda NULL y el selector igual funciona.
    exts = {}
    for f in items:
        exts[f["SKU_SIESA"]] = ((
            f["SKU_SIESA"],
            f["REFERENCIA"].strip(),
            (f.get("MARCA ID") or "").strip() or None,
            (f.get("MARCA KOS") or "").strip() or None,
            (f.get("CALIBRE") or "").strip() or None,
            str(f.get("ESTADO EXT")) if f.get("ESTADO EXT") is not None else None,
            f.get("COSTO PROM UNIT"),
        ))
    exts = list(exts.values())

    conn = pymssql.connect(server=settings.bd_host, user=settings.bd_user,
                           password=settings.bd_password, database=settings.bd_name,
                           timeout=120)
    cur = conn.cursor()
    try:
        _merge(cur, "items.cat_marcas", ["id", "descripcion", "fecha_siesa"], "id", marcas)
        _merge(cur, "items.cat_calibres", ["id", "descripcion"], "id", calibres)
        _merge(cur, "items.cat_items_base", ["referencia", "descripcion", "tipo_item", "item_id"],
               "referencia", [tuple(v) for v in base.values()], conservar=("item_id",))
        # Despues de items base: cat_extensiones_existentes tiene FK a referencia.
        cur.execute("DELETE FROM items.cat_extensiones_existentes")
        _insertar(cur, "items.cat_extensiones_existentes",
                  ["sku_siesa", "referencia", "marca_id", "marca_desc",
                   "calibre_id", "estado_ext", "costo_prom_uni"], exts)
        # El conector de creacion no devuelve el SKU: se completa aqui, cuando
        # el item ya aparece en la consulta.
        cur.execute("""
            UPDATE s SET sku_creado = e.sku_siesa, fecha_modificado = SYSUTCDATETIME()
              FROM items.solicitudes s
              JOIN items.cat_extensiones_existentes e
                ON e.referencia = s.item_base_referencia AND e.marca_id = s.marca_id
               AND e.calibre_id = s.calibre_id
             WHERE s.estado = 'Creado' AND s.sku_creado IS NULL
        """)
        skus = cur.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    resumen = {"marcas": len(marcas), "calibres": len(calibres),
               "items_base": len(base), "extensiones": len(exts), "skus_completados": skus}
    print("Cargado:", resumen)
    return resumen


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", action="store_true",
                    help="reusa cache/*.json en vez de consultar Siesa (la consulta de items tarda ~10 min)")
    args = ap.parse_args()
    sys.exit(0 if sincronizar(args.cache) else 1)
