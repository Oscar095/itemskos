# -*- coding: utf-8 -*-
"""
Crea (o restablece) un usuario Admin desde la consola. Sirve para el primer
ingreso y para recuperar el acceso si nadie recuerda la clave de un Admin.

    python -m app.auth.crear_admin --usuario oscar --nombre "Oscar Orozco"

Pide la contraseña sin mostrarla. Con --generar crea una aleatoria y la
imprime una sola vez.
"""
import argparse
import getpass
import secrets
import sys

from fastapi import HTTPException
from sqlalchemy import text

from app.auth import seguridad as seg
from app.db.session import consultar, engine


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--usuario", required=True)
    ap.add_argument("--nombre", required=True)
    ap.add_argument("--email", help="correo para notificaciones (se puede poner luego en Usuarios)")
    ap.add_argument("--cargo", help="uno de los cargos activos de Configuracion")
    ap.add_argument("--generar", action="store_true", help="genera una contraseña aleatoria")
    a = ap.parse_args()

    seg.sembrar_roles()
    rol = consultar("SELECT id FROM items.roles WHERE nombre = 'Admin' AND activo = 1")
    if not rol:
        print("No existe el rol Admin activo.", file=sys.stderr)
        return 1

    if a.generar:
        clave = secrets.token_urlsafe(9)
    else:
        clave = getpass.getpass("Contraseña: ")
        if clave != getpass.getpass("Repítela: "):
            print("No coinciden.", file=sys.stderr)
            return 1
    if len(clave) < seg.MIN_CLAVE:
        print(f"Mínimo {seg.MIN_CLAVE} caracteres.", file=sys.stderr)
        return 1

    username = seg.normalizar_usuario(a.usuario)
    if not seg.USUARIO_VALIDO.match(username):
        print("Usuario inválido: 3 a 50 caracteres, letras sin tilde, números, punto, guion.", file=sys.stderr)
        return 1
    try:
        email = seg.normalizar_email(a.email) if a.email else None
        a.cargo = seg.validar_cargo(a.cargo)
    except HTTPException as exc:
        print(exc.detail, file=sys.stderr)
        return 1
    with engine.begin() as conn:
        existe = conn.execute(text("SELECT id FROM items.usuarios WHERE username = :u"), {"u": username}).first()
        if existe:
            conn.execute(text("""
                UPDATE items.usuarios SET password_hash = :h, rol_id = :r, activo = 1, nombre = :n,
                       email = COALESCE(:e, email), cargo = COALESCE(:c, cargo) WHERE id = :id
            """), {"h": seg.hash_clave(clave), "r": rol[0]["id"], "n": a.nombre, "e": email,
                   "c": a.cargo, "id": existe[0]})
            uid = existe[0]
        else:
            uid = conn.execute(text("""
                INSERT INTO items.usuarios (username, nombre, email, cargo, password_hash, rol_id, creado_por)
                OUTPUT INSERTED.id VALUES (:u, :n, :e, :c, :h, :r, 'consola')
            """), {"u": username, "n": a.nombre, "e": email, "c": a.cargo, "h": seg.hash_clave(clave),
                   "r": rol[0]["id"]}).first()[0]
        from app.api.routes_auth import sincronizar_vendedor
        sincronizar_vendedor(conn, uid)
    seg.cerrar_sesiones_de(uid)
    print(f"Admin listo: {username}" + (f"  contraseña: {clave}" if a.generar else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
