# -*- coding: utf-8 -*-
"""
Endpoint de ingesta para la migracion desde SharePoint.

El backend no tiene credenciales de Graph API, asi que la extraccion la hace el
navegador con la sesion del usuario y empuja los registros crudos aqui.

Es temporal: cuando el historico este migrado, este router y el CORS que lo
acompana en main.py se pueden quitar.
"""
from typing import Any

from fastapi import APIRouter

from app.db.session import consultar
from app.migracion import sharepoint

router = APIRouter(prefix="/migracion", tags=["migracion"])


@router.post("/lote")
def lote(filas: list[dict[str, Any]]):
    """Recibe un lote de items crudos de SharePoint, los mapea e inserta."""
    return sharepoint.migrar_lote(filas)


@router.post("/verificar")
def verificar(ids_sharepoint: list[int]):
    """
    Compara el set de Ids que hay en SharePoint contra lo migrado.
    Contar filas no basta: esto detecta si falto alguno o si entro algo de mas.
    """
    migrados = {r["sharepoint_item_id"] for r in consultar(
        "SELECT sharepoint_item_id FROM items.solicitudes WHERE sharepoint_item_id IS NOT NULL")}
    en_sp = set(ids_sharepoint)
    faltantes = sorted(en_sp - migrados)
    sobrantes = sorted(migrados - en_sp)
    return {"en_sharepoint": len(en_sp), "migrados": len(migrados),
            "faltantes": faltantes[:50], "total_faltantes": len(faltantes),
            "sobrantes": sobrantes[:50], "total_sobrantes": len(sobrantes),
            "coinciden": not faltantes and not sobrantes}


@router.get("/estado")
def estado():
    """Cuanto se ha migrado y como quedo."""
    total = consultar("""
        SELECT COUNT(1) AS migradas,
               SUM(CASE WHEN item_base_referencia IS NULL THEN 1 ELSE 0 END) AS sin_item_base,
               SUM(CASE WHEN marca_id IS NULL THEN 1 ELSE 0 END)            AS sin_marca,
               SUM(CASE WHEN cliente_id IS NULL THEN 1 ELSE 0 END)          AS sin_cliente_siesa,
               SUM(CASE WHEN vendedor_id IS NULL THEN 1 ELSE 0 END)         AS sin_vendedor
          FROM items.solicitudes
         WHERE origen = 'migracion_sharepoint'
    """)[0]
    por_estado = consultar("""
        SELECT estado, COUNT(1) AS total FROM items.solicitudes
         WHERE origen = 'migracion_sharepoint' GROUP BY estado
    """)
    return {"resumen": total, "por_estado": por_estado}
