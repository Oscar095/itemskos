# -*- coding: utf-8 -*-
"""Roles dinamicos y su matriz de permisos (mismo contrato que produccionweb /api/roles)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.auth import seguridad as seg
from app.db.session import consultar, engine

router = APIRouter(prefix="/roles", tags=["roles"])


class PermisoIn(BaseModel):
    modulo: str
    puede_ver: bool = False
    puede_crear: bool = False
    puede_editar: bool = False
    puede_eliminar: bool = False


class RolCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    descripcion: Optional[str] = Field(None, max_length=255)
    permisos: list[PermisoIn] = []


class RolUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=1, max_length=100)
    descripcion: Optional[str] = Field(None, max_length=255)


class PermisosIn(BaseModel):
    permisos: list[PermisoIn]


def _out(rol_id: int | None = None) -> list[dict]:
    roles = consultar("""
        SELECT r.id, r.nombre, r.descripcion, r.activo,
               (SELECT COUNT(1) FROM items.usuarios u WHERE u.rol_id = r.id AND u.activo = 1) AS usuarios
          FROM items.roles r
         WHERE r.activo = 1 AND (:id IS NULL OR r.id = :id)
         ORDER BY r.id
    """, id=rol_id)
    # Permisos de todos los roles en una consulta, no una por rol.
    todos = consultar("""
        SELECT rol_id, modulo, puede_ver, puede_crear, puede_editar, puede_eliminar
          FROM items.rol_permisos WHERE rol_id IN (SELECT id FROM items.roles WHERE activo = 1)
    """)
    for r in roles:
        p = seg.mapa_permisos([f for f in todos if f["rol_id"] == r["id"]])
        # Un objeto por modulo fijo, en el formato puede_* de produccionweb.
        r["permisos"] = [{"modulo": m, **{f"puede_{a}": p[m][a] for a in seg.ACCIONES}}
                         for m in seg.CLAVES_MODULOS]
    return roles


def _como_mapa(permisos: list[PermisoIn]) -> dict:
    """Lista puede_* -> {modulo: {ver, crear, editar, eliminar}} (crear/editar/eliminar implican ver)."""
    mapa = {}
    for p in permisos:
        if p.modulo not in seg.CLAVES_MODULOS:
            raise HTTPException(400, f"Módulo desconocido: {p.modulo}")
        algo = p.puede_crear or p.puede_editar or p.puede_eliminar
        mapa[p.modulo] = {"ver": p.puede_ver or algo, "crear": p.puede_crear,
                          "editar": p.puede_editar, "eliminar": p.puede_eliminar}
    return mapa


def _guardar_permisos(conn, rol_id: int, permisos: list[PermisoIn]) -> None:
    conn.execute(text("DELETE FROM items.rol_permisos WHERE rol_id = :r"), {"r": rol_id})
    for p in permisos:
        if p.modulo not in seg.CLAVES_MODULOS:
            raise HTTPException(400, f"Módulo desconocido: {p.modulo}")
        # Cualquier accion implica poder ver el modulo (igual que la matriz de la UI).
        ver = p.puede_ver or p.puede_crear or p.puede_editar or p.puede_eliminar
        conn.execute(text("""
            INSERT INTO items.rol_permisos (rol_id, modulo, puede_ver, puede_crear, puede_editar, puede_eliminar)
            VALUES (:r, :m, :v, :c, :e, :x)
        """), {"r": rol_id, "m": p.modulo, "v": ver, "c": p.puede_crear,
               "e": p.puede_editar, "x": p.puede_eliminar})


def _queda_admin(conn) -> bool:
    return bool(conn.execute(text("""
        SELECT COUNT(1) FROM items.usuarios u
          JOIN items.roles r ON r.id = u.rol_id AND r.activo = 1
          JOIN items.rol_permisos p ON p.rol_id = r.id AND p.modulo = 'usuarios' AND p.puede_editar = 1
         WHERE u.activo = 1
    """)).scalar())


@router.get("/modulos")
def modulos(_=Depends(seg.usuario_actual)):
    """Modulos permisionables y que significa cada accion en cada uno."""
    return seg.MODULOS


@router.get("")
def listar(_=Depends(seg.requiere("usuarios", "ver"))):
    return _out()


@router.post("", status_code=201)
def crear(body: RolCreate, actor: dict = Depends(seg.requiere("usuarios", "crear"))):
    seg.exigir_cubre(actor, _como_mapa(body.permisos), "crear ese rol")
    try:
        with engine.begin() as conn:
            if conn.execute(text("SELECT 1 FROM items.roles WHERE nombre = :n"), {"n": body.nombre.strip()}).first():
                raise HTTPException(400, "Ya existe un rol con ese nombre")
            rol_id = conn.execute(text("""
                INSERT INTO items.roles (nombre, descripcion) OUTPUT INSERTED.id VALUES (:n, :d)
            """), {"n": body.nombre.strip(), "d": body.descripcion}).first()[0]
            _guardar_permisos(conn, rol_id, body.permisos)
    except IntegrityError:
        raise HTTPException(400, "Ya existe un rol con ese nombre")
    return _out(rol_id)[0]


@router.patch("/{rol_id}")
def editar(rol_id: int, body: RolUpdate, actor: dict = Depends(seg.requiere("usuarios", "editar"))):
    if not _out(rol_id):
        raise HTTPException(404, "Rol no encontrado")
    seg.exigir_cubre(actor, seg.permisos_de_rol(rol_id), "modificar ese rol")
    cambios = body.model_dump(exclude_none=True)
    if cambios:
        try:
            with engine.begin() as conn:
                sets = ", ".join(f"{k} = :{k}" for k in cambios)
                conn.execute(text(f"UPDATE items.roles SET {sets} WHERE id = :id"), {**cambios, "id": rol_id})
        except IntegrityError:
            raise HTTPException(400, "Ya existe un rol con ese nombre")
    return _out(rol_id)[0]


@router.delete("/{rol_id}")
def desactivar(rol_id: int, actor: dict = Depends(seg.requiere("usuarios", "eliminar"))):
    if not _out(rol_id):
        raise HTTPException(404, "Rol no encontrado")
    seg.exigir_cubre(actor, seg.permisos_de_rol(rol_id), "desactivar ese rol")
    activos = consultar("SELECT COUNT(1) n FROM items.usuarios WHERE rol_id = :r AND activo = 1", r=rol_id)[0]["n"]
    if activos:
        raise HTTPException(400, f"No se puede desactivar: {activos} usuario(s) activo(s) usan este rol")
    with engine.begin() as conn:
        # Libera el nombre para poder crear otro rol igual mas adelante.
        conn.execute(text("UPDATE items.roles SET activo = 0, nombre = CONCAT(nombre, ' (inactivo ', id, ')') "
                          "WHERE id = :id"), {"id": rol_id})
    return {"ok": True}


@router.put("/{rol_id}/permisos")
def actualizar_permisos(rol_id: int, body: PermisosIn, actor: dict = Depends(seg.requiere("usuarios", "editar"))):
    if not _out(rol_id):
        raise HTTPException(404, "Rol no encontrado")
    # Ni dar lo que uno no tiene, ni recortar un rol que tiene mas que uno.
    seg.exigir_cubre(actor, _como_mapa(body.permisos), "dar esos permisos")
    seg.exigir_cubre(actor, seg.permisos_de_rol(rol_id), "modificar ese rol")
    with engine.begin() as conn:
        seg.candado_admins(conn)
        _guardar_permisos(conn, rol_id, body.permisos)
        # Nadie puede quitarse a si mismo (ni a todos) la administracion de usuarios.
        if not _queda_admin(conn):
            raise HTTPException(400, "Debe quedar al menos un usuario activo que pueda administrar usuarios.")
    return _out(rol_id)[0]
