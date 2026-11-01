# -*- coding: utf-8 -*-
"""
Adjuntos en el Datalake (cuenta `datalakekos`).

El archivo nunca se guarda en SQL: va a Blob Storage y en la base solo queda
la ruta (items.adjuntos.blob_path). Las descargas se sirven con una SAS de
vida corta, para no exponer la clave de la cuenta ni hacer publico el
contenedor.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from azure.storage.blob import (BlobSasPermissions, BlobServiceClient,
                                generate_blob_sas)

from app.config import settings

_svc: BlobServiceClient | None = None


def _cliente() -> BlobServiceClient:
    global _svc
    if _svc is None:
        _svc = BlobServiceClient.from_connection_string(settings.azure_storage_conn)
        try:
            _svc.create_container(settings.contenedor_adjuntos)
        except Exception:
            pass  # ya existe
    return _svc


def subir(solicitud_id: int, nombre_archivo: str, datos: bytes,
          tipo_contenido: str | None = None) -> str:
    """
    Sube el archivo y devuelve su ruta dentro del contenedor.

    La ruta lleva un uuid para que dos archivos con el mismo nombre en la misma
    solicitud no se pisen, y va agrupada por solicitud para poder listarlas o
    borrarlas en bloque.
    """
    svc = _cliente()
    ruta = f"solicitud-{solicitud_id}/{uuid4().hex}-{nombre_archivo}"
    blob = svc.get_blob_client(settings.contenedor_adjuntos, ruta)
    from azure.storage.blob import ContentSettings
    blob.upload_blob(
        datos,
        overwrite=True,
        content_settings=ContentSettings(content_type=tipo_contenido) if tipo_contenido else None,
    )
    return ruta


def url_temporal(blob_path: str, minutos: int = 30) -> str:
    """URL firmada de solo lectura, valida por `minutos`."""
    svc = _cliente()
    sas = generate_blob_sas(
        account_name=svc.account_name,
        container_name=settings.contenedor_adjuntos,
        blob_name=blob_path,
        account_key=svc.credential.account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(timezone.utc) + timedelta(minutes=minutos),
    )
    return (f"https://{svc.account_name}.blob.core.windows.net/"
            f"{settings.contenedor_adjuntos}/{blob_path}?{sas}")


def borrar(blob_path: str) -> None:
    svc = _cliente()
    svc.get_blob_client(settings.contenedor_adjuntos, blob_path).delete_blob()
