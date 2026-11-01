# -*- coding: utf-8 -*-
"""Conexion a Azure SQL (base kx_ecommerce, esquema `items`)."""
from sqlalchemy import create_engine, text

from app.config import settings

# pool_pre_ping: Azure SQL corta conexiones ociosas sin avisar; sin esto la
# primera consulta despues de un rato falla con "connection reset".
engine = create_engine(settings.sqlalchemy_url, pool_pre_ping=True, pool_recycle=1800)


def consultar(sql: str, **params) -> list[dict]:
    """Ejecuta un SELECT y devuelve filas como diccionarios."""
    with engine.connect() as conn:
        filas = conn.execute(text(sql), params)
        columnas = filas.keys()
        return [dict(zip(columnas, fila)) for fila in filas]
