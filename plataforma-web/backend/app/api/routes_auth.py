# -*- coding: utf-8 -*-
"""Login, sesion y administracion de usuarios (mismos endpoints que produccionweb)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import opciones
from app.auth import seguridad as seg
from app.db.session import consultar, engine

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class ClaveIn(BaseModel):
    actual: str
    nueva: str


class UsuarioCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    nombre: str = Field(min_length=1, max_length=100)
    email: str                      # obligatorio: destino de las notificaciones (n8n)
    cargo: Optional[str] = None     # de la lista "cargos" de Configuracion
    password: str
    rol_id: int
    activo: bool = True             # inactivo = solo historial (p. ej. un vendedor que ya no esta)


class UsuarioUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[str] = None     # None = no cambia; vacio = error (es obligatorio)
    cargo: Optional[str] = None     # None = no cambia; "" = sin cargo
    rol_id: Optional[int] = None
    activo: Optional[bool] = None


class ResetPasswordIn(BaseModel):
    nueva_password: str


def _yo(u: dict) -> dict:
    return {"id": u["id"], "username": u["username"], "nombre": u["nombre"], "email": u.get("email"),
            "cargo": u.get("cargo"), "rol": u["rol"], "rol_id": u["rol_id"], "vendedor_id": u["vendedor_id"],
            "vendedor_nombre": u.get("vendedor_nombre"), "permisos": u["permisos"]}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    username = seg.normalizar_usuario(body.username)
    if not seg.USUARIO_VALIDO.match(username):
        # Ni se consulta: un nombre con letras de ancho completo igualaria a
        # "oscar" en la collation de SQL Server y saltaria el contador.
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    espera = seg.reservar_intento(username)
    if espera:
        raise HTTPException(429, f"Demasiados intentos fallidos. Intenta de nuevo en {espera // 60 + 1} min.")
    filas = consultar("""
        SELECT u.id, u.password_hash FROM items.usuarios u JOIN items.roles r ON r.id = u.rol_id
         WHERE u.username = :u AND u.activo = 1 AND r.activo = 1
    """, u=username)
    guardado = filas[0]["password_hash"] if filas else seg._HASH_SEÑUELO
    if not seg.verificar_clave(body.password, guardado) or not filas:
        raise HTTPException(401, "Usuario o contraseña incorrectos")   # el intento ya quedo contado
    seg.limpiar_fallos(username)
    seg.cerrar_sesion(request.cookies.get(seg.COOKIE))   # la sesion previa de este navegador no queda viva
    token = seg.crear_sesion(filas[0]["id"])
    seg.poner_cookie(response, token)
    # Mismo contrato que produccionweb (nombre, rol, rol_id, permisos), sin token:
    # la sesion viaja en la cookie HttpOnly.
    u = consultar("""
        SELECT u.id, u.username, u.nombre, u.email, u.cargo, u.rol_id, r.nombre AS rol, u.vendedor_id,
               v.nombre AS vendedor_nombre
          FROM items.usuarios u JOIN items.roles r ON r.id = u.rol_id
          LEFT JOIN items.vendedores v ON v.id = u.vendedor_id WHERE u.id = :id
    """, id=filas[0]["id"])[0]
    u["permisos"] = seg.permisos_de_rol(u["rol_id"])
    return _yo(u)


@router.post("/logout")
def logout(request: Request, response: Response):
    seg.cerrar_sesion(request.cookies.get(seg.COOKIE))
    seg.borrar_cookie(response)
    return {"ok": True}


@router.get("/yo")
def yo(usuario: dict = Depends(seg.usuario_actual)):
    return _yo(usuario)


@router.get("/cargos")
def cargos(_=Depends(seg.usuario_actual)):
    """Cargos activos (se administran en Configuracion)."""
    return opciones.activas("cargos")


@router.post("/clave")
def cambiar_mi_clave(body: ClaveIn, request: Request, usuario: dict = Depends(seg.usuario_actual)):
    guardado = consultar("SELECT password_hash FROM items.usuarios WHERE id = :id", id=usuario["id"])[0]
    if not seg.verificar_clave(body.actual, guardado["password_hash"]):
        raise HTTPException(400, "La contraseña actual no es correcta.")
    seg.validar_clave_nueva(body.nueva)
    with engine.begin() as conn:
        conn.execute(text("UPDATE items.usuarios SET password_hash = :h WHERE id = :id"),
                     {"h": seg.hash_clave(body.nueva), "id": usuario["id"]})
    # Las demas sesiones abiertas (otro equipo) se cierran; esta sigue.
    seg.cerrar_sesiones_de(usuario["id"], salvo_token=request.cookies.get(seg.COOKIE))
    return {"ok": True}


# --- administracion de usuarios ---------------------------------------------

def _usuario_out(id_: int | None = None) -> list[dict]:
    return consultar("""
        SELECT u.id, u.username, u.nombre, u.email, u.cargo, u.activo, u.rol_id,
               r.nombre AS rol_nombre, r.nombre AS rol,
               u.vendedor_id, v.nombre AS vendedor_nombre, u.created_at, u.ultimo_ingreso
          FROM items.usuarios u
          JOIN items.roles r ON r.id = u.rol_id
          LEFT JOIN items.vendedores v ON v.id = u.vendedor_id
         WHERE (:id IS NULL OR u.id = :id)
         ORDER BY u.activo DESC, u.nombre
    """, id=id_)


def _permisos_usuario(usuario_id: int) -> dict:
    rol = consultar("SELECT rol_id FROM items.usuarios WHERE id = :id", id=usuario_id)[0]["rol_id"]
    return seg.permisos_de_rol(rol)


def _puede_tocar(actor: dict, usuario_id: int, que: str) -> None:
    """No se administra a quien tiene mas permisos que uno (p. ej. resetear la clave de un Admin)."""
    seg.exigir_cubre(actor, _permisos_usuario(usuario_id), que)


def _rol_activo(rol_id: int) -> dict:
    r = consultar("SELECT id, nombre FROM items.roles WHERE id = :id AND activo = 1", id=rol_id)
    if not r:
        raise HTTPException(404, "Rol no encontrado")
    return r[0]


def _duplicado(exc: IntegrityError) -> HTTPException:
    if "UX_usuarios_email" in str(exc.orig):
        return HTTPException(400, "Ese correo ya está registrado en otro usuario.")
    return HTTPException(400, "El usuario ya existe")


def sincronizar_vendedor(conn, usuario_id: int) -> None:
    """
    Usuario con cargo Comercial <-> su registro en items.vendedores, por correo
    (unico en ambas tablas). Asi el desplegable de vendedor de una solicitud son
    los comerciales activos, y quien ya vendia antes de la plataforma (vendedor
    migrado de SharePoint con el mismo correo) conserva su historial.
    vendedores.activo queda como espejo: activo si algun comercial activo lo usa.
    """
    u = conn.execute(text("SELECT nombre, email, cargo, activo, vendedor_id FROM items.usuarios WHERE id = :id"),
                     {"id": usuario_id}).mappings().first()
    afectados = {u["vendedor_id"]} - {None}
    if u["cargo"] == "Comercial":
        if not u["email"]:
            raise HTTPException(400, "Un usuario Comercial necesita correo: con él se liga a su historial de vendedor.")
        con_correo = conn.execute(text("SELECT id FROM items.vendedores WHERE email = :e"), {"e": u["email"]}).first()
        propio = conn.execute(text("SELECT id, email FROM items.vendedores WHERE id = :v"),
                              {"v": u["vendedor_id"]}).mappings().first() if u["vendedor_id"] else None
        if propio and propio["email"].lower() != u["email"].lower():
            # Le cambiaron el correo a un Comercial que ya tiene vendedor: se corrige ESE
            # registro, para no partir su historial entre dos vendedores.
            if not con_correo:
                conn.execute(text("UPDATE items.vendedores SET email = :e, nombre = :n WHERE id = :v"),
                             {"e": u["email"], "n": u["nombre"], "v": propio["id"]})
                con_correo = (propio["id"],)
            elif conn.execute(text("SELECT TOP 1 1 FROM items.solicitudes WHERE vendedor_id = :v"),
                              {"v": propio["id"]}).first():
                raise HTTPException(400, f"El correo {u['email']} ya es de otro vendedor con su propio historial; "
                                         "no se pueden unir automáticamente.")
        vid = con_correo[0] if con_correo else conn.execute(text("""
            INSERT INTO items.vendedores (email, nombre, activo) OUTPUT INSERTED.id VALUES (:e, :n, :a)
        """), {"e": u["email"], "n": u["nombre"], "a": bool(u["activo"])}).first()[0]
        otro = conn.execute(text("SELECT TOP 1 username FROM items.usuarios WHERE vendedor_id = :v AND id <> :id"),
                            {"v": vid, "id": usuario_id}).first()
        if otro:
            raise HTTPException(400, f"Ese vendedor ya está ligado al usuario {otro[0]}.")
        if u["vendedor_id"] != vid:
            conn.execute(text("UPDATE items.usuarios SET vendedor_id = :v WHERE id = :id"), {"v": vid, "id": usuario_id})
        afectados.add(vid)
    for vid in afectados:
        conn.execute(text("""
            UPDATE items.vendedores SET activo = CASE WHEN EXISTS (
                       SELECT 1 FROM items.usuarios WHERE vendedor_id = :v AND activo = 1 AND cargo = 'Comercial')
                   THEN 1 ELSE 0 END
             WHERE id = :v
        """), {"v": vid})


@router.get("/usuarios")
def listar_usuarios(_=Depends(seg.requiere("usuarios", "ver"))):
    return _usuario_out()


@router.post("/usuarios", status_code=201)
def crear_usuario(body: UsuarioCreate, admin: dict = Depends(seg.requiere("usuarios", "crear"))):
    # La MISMA regla que el login: antes se aceptaba "josé" (isalnum) y luego no podia entrar.
    username = seg.normalizar_usuario(body.username)
    if not seg.USUARIO_VALIDO.match(username):
        raise HTTPException(400, "El usuario admite de 3 a 50 caracteres: letras sin tilde, números, punto, guion y guion bajo.")
    email = seg.normalizar_email(body.email)
    cargo = seg.validar_cargo(body.cargo)
    seg.validar_clave_nueva(body.password)
    _rol_activo(body.rol_id)
    seg.exigir_cubre(admin, seg.permisos_de_rol(body.rol_id), "asignar ese rol")
    try:
        with engine.begin() as conn:
            nuevo = conn.execute(text("""
                INSERT INTO items.usuarios (username, nombre, email, cargo, password_hash, rol_id, activo, creado_por)
                OUTPUT INSERTED.id VALUES (:u, :n, :e, :c, :h, :r, :a, :por)
            """), {"u": username, "n": body.nombre.strip(), "e": email, "c": cargo,
                   "h": seg.hash_clave(body.password), "r": body.rol_id, "a": body.activo,
                   "por": admin["nombre"]}).first()[0]
            sincronizar_vendedor(conn, nuevo)
    except IntegrityError as exc:
        raise _duplicado(exc)
    return _usuario_out(nuevo)[0]


@router.patch("/usuarios/{usuario_id}")
def editar_usuario(usuario_id: int, body: UsuarioUpdate, admin: dict = Depends(seg.requiere("usuarios", "editar"))):
    actual = _usuario_out(usuario_id)
    if not actual:
        raise HTTPException(404, "Usuario no encontrado")
    _puede_tocar(admin, usuario_id, "editar a ese usuario")
    cambios = {}
    if body.nombre is not None:
        cambios["nombre"] = body.nombre.strip()
    if body.email is not None:
        cambios["email"] = seg.normalizar_email(body.email)
    if body.cargo is not None:
        cambios["cargo"] = seg.validar_cargo(body.cargo, actual[0]["cargo"])
    if body.rol_id is not None and body.rol_id != actual[0]["rol_id"]:
        if usuario_id == admin["id"]:
            raise HTTPException(400, "No puedes cambiar tu propio rol.")
        _rol_activo(body.rol_id)
        seg.exigir_cubre(admin, seg.permisos_de_rol(body.rol_id), "asignar ese rol")
        cambios["rol_id"] = body.rol_id
    if body.activo is not None and body.activo != actual[0]["activo"]:
        if body.activo is False:
            # Desactivar es "eliminar", igual que DELETE: mismas reglas por ambas vias.
            seg.exigir(admin, "usuarios", "eliminar")
            if usuario_id == admin["id"]:
                raise HTTPException(400, "No puedes desactivar tu propio usuario.")
        cambios["activo"] = body.activo
    if not cambios:
        return _usuario_out(usuario_id)[0]

    try:
        with engine.begin() as conn:
            seg.candado_admins(conn)
            # Las claves salen de la lista fija de arriba, nunca del cuerpo de la peticion.
            sets = ", ".join(f"{k} = :{k}" for k in cambios)
            conn.execute(text(f"UPDATE items.usuarios SET {sets} WHERE id = :id"), {**cambios, "id": usuario_id})
            sincronizar_vendedor(conn, usuario_id)
            # Revalidar DENTRO de la transaccion: que no quede nadie que administre usuarios.
            if ("rol_id" in cambios or cambios.get("activo") is False) and not _queda_admin(conn):
                raise HTTPException(400, "Debe quedar al menos un usuario activo que pueda administrar usuarios.")
    except IntegrityError as exc:
        raise _duplicado(exc)
    if cambios.get("activo") is False:
        seg.cerrar_sesiones_de(usuario_id)
    return _usuario_out(usuario_id)[0]


def _queda_admin(conn) -> bool:
    return bool(conn.execute(text("""
        SELECT COUNT(1) FROM items.usuarios u
          JOIN items.roles r ON r.id = u.rol_id AND r.activo = 1
          JOIN items.rol_permisos p ON p.rol_id = r.id AND p.modulo = 'usuarios' AND p.puede_editar = 1
         WHERE u.activo = 1
    """)).scalar())


@router.delete("/usuarios/{usuario_id}")
def desactivar_usuario(usuario_id: int, admin: dict = Depends(seg.requiere("usuarios", "eliminar"))):
    """Desactiva (no borra): sus solicitudes y eventos siguen apuntando a su nombre."""
    if usuario_id == admin["id"]:
        raise HTTPException(400, "No puedes desactivar tu propio usuario.")
    if not _usuario_out(usuario_id):
        raise HTTPException(404, "Usuario no encontrado")
    _puede_tocar(admin, usuario_id, "desactivar a ese usuario")
    with engine.begin() as conn:
        seg.candado_admins(conn)
        conn.execute(text("UPDATE items.usuarios SET activo = 0 WHERE id = :id"), {"id": usuario_id})
        sincronizar_vendedor(conn, usuario_id)
        if not _queda_admin(conn):
            raise HTTPException(400, "Debe quedar al menos un usuario activo que pueda administrar usuarios.")
    seg.cerrar_sesiones_de(usuario_id)
    return _usuario_out(usuario_id)[0]


@router.post("/usuarios/{usuario_id}/password")
def resetear_clave(usuario_id: int, body: ResetPasswordIn, admin: dict = Depends(seg.requiere("usuarios", "editar"))):
    if not _usuario_out(usuario_id):
        raise HTTPException(404, "Usuario no encontrado")
    _puede_tocar(admin, usuario_id, "cambiar la contraseña de ese usuario")
    seg.validar_clave_nueva(body.nueva_password)
    with engine.begin() as conn:
        conn.execute(text("UPDATE items.usuarios SET password_hash = :h WHERE id = :id"),
                     {"h": seg.hash_clave(body.nueva_password), "id": usuario_id})
    seg.cerrar_sesiones_de(usuario_id)   # quien tenia la clave vieja queda fuera
    return {"ok": True}
