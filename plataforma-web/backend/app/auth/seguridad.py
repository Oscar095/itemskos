# -*- coding: utf-8 -*-
"""
Autenticacion y permisos.

Mismo modelo que produccionweb (roles dinamicos + matriz de permisos por
modulo), con dos diferencias deliberadas:

  * La sesion es un token aleatorio en cookie HttpOnly, guardado en
    items.sesiones como SHA-256. Desactivar un usuario o cerrar sesion la
    corta en el acto; con un JWT en localStorage seguiria valiendo hasta que
    expire, y cualquier script de la pagina podria leerlo.
  * El backend valida cada endpoint contra la matriz (modulo + accion), no
    contra el nombre del rol: asi lo que el Admin edita en "Roles y
    Permisos" es lo que de verdad se aplica.
"""
import hashlib
import hmac
import re
import secrets
import threading
import time
import unicodedata
from base64 import b64decode, b64encode
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import text

from app import opciones
from app.config import settings
from app.db.session import consultar, engine

COOKIE = "kos_items_sesion"
DURACION = timedelta(hours=8)          # igual que el JWT de produccionweb
RENOVAR_SI_QUEDA = timedelta(hours=4)  # sesion deslizante mientras se use...
VIDA_MAXIMA = timedelta(hours=12)      # ...pero nunca mas de esto desde el login
MIN_CLAVE = 8
# Encabezado que exige toda escritura (ver main.py): un formulario o un fetch
# "simple" desde otra pagina no puede ponerlo sin un preflight CORS, y este
# backend no responde CORS a nadie.
CSRF_HEADER = "X-KOS"
USUARIO_VALIDO = re.compile(r"^[a-z0-9._-]{3,50}$")
EMAIL_VALIDO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# El cargo (area de la persona, distinta del rol, que solo define permisos) es
# una lista de Configuracion: app.opciones, lista "cargos". La usara el workflow
# de n8n para saber a quien notificar cada avance.

# Modulos que se pueden permisionar. Fuente de verdad (como MODULOS en
# produccionweb/routers/roles.py): agregar uno aqui, en el NAV del frontend y,
# si aplica, en ROLES_POR_DEFECTO. `acciones` explica que significa cada
# casilla en este modulo; la UI lo muestra en la matriz.
MODULOS = [
    {"clave": "seguimiento", "label": "Seguimiento",
     "acciones": {"ver": "Ver solicitudes y su ficha", "editar": "Subir adjuntos"}},
    {"clave": "solicitudes", "label": "Nueva solicitud",
     "acciones": {"crear": "Crear solicitudes de item"}},
    {"clave": "marcas", "label": "Marcas (Ext1)",
     "acciones": {"crear": "Crear marcas nuevas en Siesa"}},
    {"clave": "diseno", "label": "Etapas de Diseño",
     "acciones": {"editar": "Registrar Solicitud de Diseño, Aprobación de Diseño y Llegada de Planchas"}},
    {"clave": "pedidos", "label": "Digitación de Pedido",
     "acciones": {"editar": "Registrar la etapa Digitación de Pedido"}},
    {"clave": "planeacion", "label": "Planeación",
     "acciones": {"ver": "Ver items listos a crear e historial de cargues",
                  "crear": "Lanzar cargues a Siesa",
                  "editar": "Elegir ruta y bodega; registrar Creación de item y En producción"}},
    {"clave": "configuracion", "label": "Configuración",
     "acciones": {"ver": "Ver las listas (tipos de material, tipos de solicitud y cargos)",
                  "crear": "Agregar opciones a las listas",
                  "editar": "Activar o desactivar opciones"}},
    {"clave": "usuarios", "label": "Usuarios y Roles",
     "acciones": {"ver": "Ver usuarios y roles", "crear": "Crear usuarios y roles",
                  "editar": "Editar usuarios, contraseñas y permisos", "eliminar": "Desactivar usuarios y roles"}},
]
CLAVES_MODULOS = [m["clave"] for m in MODULOS]
ACCIONES = ("ver", "crear", "editar", "eliminar")


def _p(ver=False, crear=False, editar=False, eliminar=False):
    return {"ver": ver or crear or editar or eliminar, "crear": crear, "editar": editar, "eliminar": eliminar}


TODO = _p(True, True, True, True)
ROLES_POR_DEFECTO = {
    "Admin": ("Acceso total, incluida la gestión de usuarios y roles",
              {m: TODO for m in CLAVES_MODULOS}),
    "Comercial": ("Crea solicitudes y marcas, registra la digitación del pedido", {
        "seguimiento": _p(ver=True, editar=True), "solicitudes": _p(crear=True),
        "marcas": _p(crear=True), "pedidos": _p(editar=True)}),
    "Diseño": ("Valida y aprueba diseños; registra la llegada de planchas", {
        "seguimiento": _p(ver=True, editar=True), "diseno": _p(editar=True)}),
    "Planeación": ("Confirma ruta y bodega y lanza los cargues a Siesa", {
        "seguimiento": _p(ver=True, editar=True), "planeacion": _p(ver=True, crear=True, editar=True)}),
}


# --- claves ------------------------------------------------------------------

_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}


def hash_clave(clave: str) -> str:
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(clave.encode("utf-8"), salt=sal, dklen=32, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${b64encode(sal).decode()}${b64encode(h).decode()}"


def verificar_clave(clave: str, guardado: str) -> bool:
    try:
        algo, n, r, p, sal, h = guardado.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(clave.encode("utf-8"), salt=b64decode(sal), dklen=len(b64decode(h)),
                              n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(calc, b64decode(h))
    except Exception:
        return False


# Para que "usuario inexistente" tarde lo mismo que "clave mala" y no delate
# que usuarios existen.
_HASH_SEÑUELO = hash_clave(secrets.token_urlsafe(16))


def normalizar_email(email: str | None) -> str:
    """Correo obligatorio y bien formado, en minusculas (es el destino de las notificaciones)."""
    e = (email or "").strip().lower()
    if not e:
        raise HTTPException(400, "El correo electrónico es obligatorio.")
    if len(e) > 200 or not EMAIL_VALIDO.match(e):
        raise HTTPException(400, "El correo electrónico no es válido.")
    return e


def validar_cargo(cargo: str | None, actual: str | None = None) -> str | None:
    """
    Cargo activo de Configuracion, con su nombre canonico. El cargo que el usuario
    YA tiene se acepta aunque lo hayan desactivado: si no, editarlo para otra cosa
    (p. ej. el correo) obligaria a cambiarle el cargo.
    """
    if not cargo or not cargo.strip():
        return None
    if actual and cargo.strip().lower() == actual.lower():
        return actual
    canon = opciones.canonica("cargos", cargo)
    if not canon:
        raise HTTPException(400, f"Cargo inválido. Opciones: {', '.join(opciones.activas('cargos'))}.")
    return canon


def validar_clave_nueva(clave: str) -> None:
    if len(clave or "") < MIN_CLAVE:
        raise HTTPException(400, f"La contraseña debe tener al menos {MIN_CLAVE} caracteres.")


# --- freno a la fuerza bruta (por usuario, en memoria) ------------------------
#
# El intento se RESERVA antes de verificar la clave (bajo lock): asi 40
# peticiones en paralelo cuentan como 40 intentos y no se cuelan antes del
# primer fallo. El usuario llega ya normalizado (normalizar_usuario), asi que
# variantes Unicode del mismo nombre caen en el mismo contador.

MAX_FALLOS, BLOQUEO_SEG, MAX_ENTRADAS = 5, 300, 5000
_fallos: dict[str, tuple[int, float]] = {}
_fallos_lock = threading.Lock()


def normalizar_usuario(username: str) -> str:
    return unicodedata.normalize("NFKC", username or "").strip().lower()


def reservar_intento(username: str) -> int:
    """0 si puede intentar (y cuenta el intento); si no, segundos de bloqueo restantes."""
    ahora = time.time()
    with _fallos_lock:
        if len(_fallos) > MAX_ENTRADAS:   # no crecer sin limite con nombres al azar
            for k in [k for k, (_, t) in _fallos.items() if t < ahora]:
                del _fallos[k]
        n, hasta = _fallos.get(username, (0, 0.0))
        if n >= MAX_FALLOS:
            if hasta > ahora:
                return int(hasta - ahora) + 1
            n = 0                          # ya cumplio el bloqueo anterior
        n += 1
        _fallos[username] = (n, ahora + BLOQUEO_SEG)
        return 0


def limpiar_fallos(username: str) -> None:
    with _fallos_lock:
        _fallos.pop(username, None)


# --- sesiones ----------------------------------------------------------------

def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)   # la base guarda UTC sin zona


def crear_sesion(usuario_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM items.sesiones WHERE expira < SYSUTCDATETIME()"))
        conn.execute(text("""
            INSERT INTO items.sesiones (token_hash, usuario_id, expira) VALUES (:t, :u, :e)
        """), {"t": _sha(token), "u": usuario_id, "e": _ahora() + DURACION})
        conn.execute(text("UPDATE items.usuarios SET ultimo_ingreso = SYSUTCDATETIME() WHERE id = :u"),
                     {"u": usuario_id})
    return token


def cerrar_sesion(token: str | None) -> None:
    if token:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM items.sesiones WHERE token_hash = :t"), {"t": _sha(token)})


def cerrar_sesiones_de(usuario_id: int, salvo_token: str | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM items.sesiones WHERE usuario_id = :u AND token_hash <> :t"),
                     {"u": usuario_id, "t": _sha(salvo_token) if salvo_token else ""})


def poner_cookie(response, token: str) -> None:
    response.set_cookie(COOKIE, token, max_age=int(DURACION.total_seconds()), httponly=True,
                        samesite="lax", secure=settings.cookie_secure, path="/")


def borrar_cookie(response) -> None:
    response.delete_cookie(COOKIE, path="/", samesite="lax", secure=settings.cookie_secure, httponly=True)


# --- permisos ----------------------------------------------------------------

def mapa_permisos(filas: list[dict]) -> dict:
    """Filas de rol_permisos (modulo, puede_*) -> {modulo: {ver, crear, editar, eliminar}} completo."""
    mapa = {f["modulo"]: f for f in filas if f.get("modulo")}
    return {m: {a: bool(mapa[m][f"puede_{a}"]) if m in mapa else False for a in ACCIONES}
            for m in CLAVES_MODULOS}


def permisos_de_rol(rol_id: int) -> dict:
    return mapa_permisos(consultar("""
        SELECT modulo, puede_ver, puede_crear, puede_editar, puede_eliminar
          FROM items.rol_permisos WHERE rol_id = :r
    """, r=rol_id))


def usuario_actual(request: Request, response: Response) -> dict:
    """Dependencia: el usuario de la sesion, con sus permisos. 401 si no hay."""
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Inicia sesión para continuar.")
    # Una sola consulta (sesion + usuario + permisos): cada ida a Azure SQL
    # cuesta ~0,5 s y esto corre en TODAS las peticiones.
    filas = consultar("""
        SELECT u.id, u.username, u.nombre, u.email, u.cargo, u.rol_id, r.nombre AS rol, u.vendedor_id,
               v.nombre AS vendedor_nombre, v.email AS vendedor_email, s.expira,
               p.modulo, p.puede_ver, p.puede_crear, p.puede_editar, p.puede_eliminar
          FROM items.sesiones s
          JOIN items.usuarios u ON u.id = s.usuario_id
          JOIN items.roles r    ON r.id = u.rol_id
          LEFT JOIN items.vendedores v   ON v.id = u.vendedor_id
          LEFT JOIN items.rol_permisos p ON p.rol_id = r.id
         WHERE s.token_hash = :t AND s.expira > SYSUTCDATETIME()
           AND s.creada > DATEADD(hour, -:vida, SYSUTCDATETIME())
           AND u.activo = 1 AND r.activo = 1
    """, t=_sha(token), vida=int(VIDA_MAXIMA.total_seconds() // 3600))
    if not filas:
        raise HTTPException(401, "Tu sesión expiró. Vuelve a iniciar sesión.")
    u = {k: filas[0][k] for k in ("id", "username", "nombre", "email", "cargo", "rol_id", "rol",
                                  "vendedor_id", "vendedor_nombre", "vendedor_email", "expira")}
    if u.pop("expira") - _ahora() < RENOVAR_SI_QUEDA:
        with engine.begin() as conn:
            conn.execute(text("UPDATE items.sesiones SET expira = :e WHERE token_hash = :t"),
                         {"e": _ahora() + DURACION, "t": _sha(token)})
        poner_cookie(response, token)   # sin esto el navegador la tiraria a las 8 h igual
    u["permisos"] = mapa_permisos(filas)
    return u


def tiene(usuario: dict, modulo: str, accion: str = "ver") -> bool:
    return bool(usuario["permisos"].get(modulo, {}).get(accion))


def requiere(modulo: str, accion: str = "ver"):
    """Dependencia: exige un permiso de la matriz. 403 si el rol no lo tiene."""
    def _dep(usuario: dict = Depends(usuario_actual)) -> dict:
        if not tiene(usuario, modulo, accion):
            raise HTTPException(403, "Tu rol no tiene permiso para esta acción.")
        return usuario
    return _dep


def exigir(usuario: dict, modulo: str, accion: str) -> None:
    if not tiene(usuario, modulo, accion):
        raise HTTPException(403, "Tu rol no tiene permiso para esta acción.")


def cubre(actor: dict, permisos_objetivo: dict) -> bool:
    """El actor tiene, como minimo, todos los permisos de `permisos_objetivo`."""
    return all(actor["permisos"].get(m, {}).get(a, False)
               for m, acc in permisos_objetivo.items() for a, v in acc.items() if v)


def exigir_cubre(actor: dict, permisos_objetivo: dict, que: str) -> None:
    """Regla de no escalar: nadie otorga ni toca lo que el mismo no tiene."""
    if not cubre(actor, permisos_objetivo):
        raise HTTPException(403, f"No puedes {que}: tiene permisos que tu rol no tiene.")


def candado_admins(conn) -> None:
    """Serializa los cambios que pueden dejar el sistema sin administradores.
    Con READ_COMMITTED_SNAPSHOT (por defecto en Azure SQL) dos transacciones
    podrian contar al otro admin todavia activo y quedar ambas en cero."""
    conn.execute(text("EXEC sp_getapplock @Resource = 'items_admin_guard', @LockMode = 'Exclusive', "
                      "@LockOwner = 'Transaction', @LockTimeout = 15000"))


# --- siembra -----------------------------------------------------------------

def sembrar_roles() -> None:
    """Al arrancar: crea los 4 roles base si no existen. No toca los permisos de
    los ya creados (los administra el Admin desde la UI), salvo una cosa: si
    aparece un MODULO NUEVO, el rol Admin lo recibe completo. Sin eso nadie
    podria ver el modulo (ni darse permisos sobre el, por la regla de no escalar).
    "Nuevo" = ningun rol tiene fila para ese modulo: asi un rol creado despues con
    el nombre "Admin" (y permisos limitados) no se lleva todo en el siguiente arranque."""
    with engine.begin() as conn:
        admin = conn.execute(text("SELECT id FROM items.roles WHERE nombre = 'Admin' AND activo = 1")).first()
        if admin:
            for modulo in CLAVES_MODULOS:
                conn.execute(text("""
                    IF NOT EXISTS (SELECT 1 FROM items.rol_permisos WHERE modulo = :m)
                        INSERT INTO items.rol_permisos (rol_id, modulo, puede_ver, puede_crear, puede_editar, puede_eliminar)
                        VALUES (:r, :m, 1, 1, 1, 1)
                """), {"r": admin[0], "m": modulo})
        for nombre, (desc, permisos) in ROLES_POR_DEFECTO.items():
            existe = conn.execute(text("SELECT id FROM items.roles WHERE nombre = :n"), {"n": nombre}).first()
            if existe:
                continue
            rol_id = conn.execute(text("""
                INSERT INTO items.roles (nombre, descripcion) OUTPUT INSERTED.id VALUES (:n, :d)
            """), {"n": nombre, "d": desc}).first()[0]
            for modulo, p in permisos.items():
                conn.execute(text("""
                    INSERT INTO items.rol_permisos (rol_id, modulo, puede_ver, puede_crear, puede_editar, puede_eliminar)
                    VALUES (:r, :m, :v, :c, :e, :x)
                """), {"r": rol_id, "m": modulo, "v": p["ver"], "c": p["crear"], "e": p["editar"], "x": p["eliminar"]})
