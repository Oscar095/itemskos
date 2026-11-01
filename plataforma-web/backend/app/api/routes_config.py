# -*- coding: utf-8 -*-
"""Configuracion: listas que usa el formulario de solicitudes (tipos de material y de solicitud)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import opciones
from app.auth import seguridad as seg
from app.db.session import consultar, engine

router = APIRouter(prefix="/config", tags=["config"])


class OpcionNueva(BaseModel):
    nombre: str


class OpcionEstado(BaseModel):
    activo: bool


def _lista(lista: str) -> str:
    if lista not in opciones.LISTAS:
        raise HTTPException(404, "Lista no encontrada")
    return lista


def _filas(lista: str, id_: int | None = None) -> list[dict]:
    filas = consultar("""
        SELECT id, lista, nombre, activo, orden, created_at, creado_por
          FROM items.config_opciones
         WHERE lista = :l AND (:id IS NULL OR id = :id)
         ORDER BY orden, nombre
    """, l=lista, id=id_)
    for f in filas:
        f["protegida"] = opciones.protegida(lista, f["nombre"])
    return filas


@router.get("/listas")
def listas(_=Depends(seg.requiere("configuracion", "ver"))):
    return [{"clave": k, "label": v} for k, v in opciones.LISTAS.items()]


@router.get("/opciones/{lista}")
def ver(lista: str, _=Depends(seg.requiere("configuracion", "ver"))):
    return _filas(_lista(lista))


@router.post("/opciones/{lista}", status_code=201)
def agregar(lista: str, body: OpcionNueva, usuario: dict = Depends(seg.requiere("configuracion", "crear"))):
    _lista(lista)
    nombre = " ".join(body.nombre.split())   # sin espacios dobles ni en los extremos
    if not nombre:
        raise HTTPException(400, "Escribe un nombre.")
    if len(nombre) > opciones.MAX_NOMBRE:
        raise HTTPException(400, f"Máximo {opciones.MAX_NOMBRE} caracteres.")
    if "," in nombre:
        # El historico guarda varios tipos de solicitud separados por coma.
        raise HTTPException(400, "El nombre no puede llevar comas.")
    try:
        with engine.begin() as conn:
            nuevo = conn.execute(text("""
                INSERT INTO items.config_opciones (lista, nombre, orden, creado_por)
                OUTPUT INSERTED.id
                VALUES (:l, :n, (SELECT ISNULL(MAX(orden), 0) + 1 FROM items.config_opciones WHERE lista = :l), :por)
            """), {"l": lista, "n": nombre, "por": usuario["nombre"]}).first()[0]
    except IntegrityError:
        previa = consultar("SELECT activo FROM items.config_opciones WHERE lista = :l AND nombre = :n",
                           l=lista, n=nombre)
        if previa and not previa[0]["activo"]:
            raise HTTPException(400, f"«{nombre}» ya existe pero está inactiva: actívala en la lista.")
        raise HTTPException(400, f"«{nombre}» ya existe.")
    return _filas(lista, nuevo)[0]


@router.patch("/opciones/{lista}/{opcion_id}")
def cambiar_estado(lista: str, opcion_id: int, body: OpcionEstado,
                   _=Depends(seg.requiere("configuracion", "editar"))):
    _lista(lista)
    actual = _filas(lista, opcion_id)
    if not actual:
        raise HTTPException(404, "Opción no encontrada")
    if not body.activo and actual[0]["protegida"]:
        raise HTTPException(400, f"«{actual[0]['nombre']}» no se puede desactivar. {actual[0]['protegida']}")
    with engine.begin() as conn:
        # Serializa por lista: dos desactivaciones a la vez (con RCSI) podrian dejarla en cero.
        conn.execute(text("EXEC sp_getapplock @Resource = :r, @LockMode = 'Exclusive', "
                          "@LockOwner = 'Transaction', @LockTimeout = 15000"), {"r": f"items_config_{lista}"})
        conn.execute(text("UPDATE items.config_opciones SET activo = :a WHERE id = :id AND lista = :l"),
                     {"a": body.activo, "id": opcion_id, "l": lista})
        quedan = conn.execute(text("SELECT COUNT(1) FROM items.config_opciones WHERE lista = :l AND activo = 1"),
                              {"l": lista}).scalar()
        if not quedan:
            # Sin ninguna activa nadie podria crear solicitudes.
            raise HTTPException(400, f"Debe quedar al menos un {opciones.LISTAS[lista].lower()} activo.")
    return _filas(lista, opcion_id)[0]
