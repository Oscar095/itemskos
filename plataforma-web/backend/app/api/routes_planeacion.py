# -*- coding: utf-8 -*-
"""Items listos a crear (planeador), parametros de planeacion e historial de cargues."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.seguridad import requiere
from app.siesa import planeacion

router = APIRouter(prefix="/planeacion", tags=["planeacion"])


class Borrador(BaseModel):
    ruta_id: Optional[str] = None
    bodega_asignacion: Optional[str] = None
    item_codigo: Optional[int] = None


class FilaCargue(BaseModel):
    solicitud_id: int
    ruta_id: str
    bodega: str
    item_codigo: Optional[int] = None


class CargueNuevo(BaseModel):
    usuario: Optional[str] = None  # ignorado: se usa el de la sesion
    items: list[FilaCargue]


@router.get("/opciones")
def opciones(_=Depends(requiere("planeacion", "ver"))):
    try:
        rutas = planeacion.rutas()
    except RuntimeError as exc:
        raise HTTPException(502, f"No se pudo consultar las rutas en Siesa: {exc}")
    return {"rutas": rutas, "bodegas": planeacion.BODEGAS}


@router.get("/listos")
def listos(_=Depends(requiere("planeacion", "ver"))):
    return planeacion.listos()


@router.patch("/listos/{solicitud_id}")
def guardar(solicitud_id: int, b: Borrador, _=Depends(requiere("planeacion", "editar"))):
    try:
        planeacion.guardar_borrador(solicitud_id, b.ruta_id, b.bodega_asignacion, b.item_codigo)
    except planeacion.ErrorPlaneacion as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:  # rutas() sin Siesa y sin cache
        raise HTTPException(502, f"No se pudo validar la ruta contra Siesa: {exc}")
    return {"ok": True}


@router.post("/cargues", status_code=202)
def cargar(c: CargueNuevo, usuario: dict = Depends(requiere("planeacion", "crear"))):
    """Arranca el cargue en segundo plano; el avance se consulta en /cargues/{id}."""
    try:
        cargue_id = planeacion.iniciar_cargue([f.model_dump() for f in c.items], usuario["nombre"])
    except planeacion.ErrorPlaneacion as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(502, f"No se pudo validar las rutas contra Siesa: {exc}")
    return {"id": cargue_id}


@router.get("/cargues")
def historial(limite: int = 50, _=Depends(requiere("planeacion", "ver"))):
    return planeacion.historial(limite)


@router.get("/cargues/{cargue_id}")
def detalle(cargue_id: int, _=Depends(requiere("planeacion", "ver"))):
    d = planeacion.detalle_cargue(cargue_id)
    if not d:
        raise HTTPException(404, "Cargue no encontrado")
    return d
