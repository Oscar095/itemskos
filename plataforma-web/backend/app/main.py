# -*- coding: utf-8 -*-
"""
Punto de entrada del backend.

Correr con:  uvicorn app.main:app --reload
Documentacion interactiva en /docs
En Azure (frontend + API en un solo servicio):  uvicorn app.main:servidor
"""
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (routes_auth, routes_catalogo, routes_config, routes_migracion, routes_planeacion,
                     routes_roles, routes_solicitudes)
from app.auth import seguridad
from app.db.session import consultar
from app.siesa import planeacion

app = FastAPI(title="KOS - Plataforma de Items", version="0.6.0")

# Sin CORS a proposito: el frontend llega same-origin por el proxy /api (o
# servido por este mismo backend). Con el encabezado X-KOS que exige toda
# escritura, otra pagina (aunque sea otra app en localhost:otro-puerto) no
# puede mandar un POST con la sesion de alguien: poner ese encabezado obliga a
# un preflight CORS que aqui nadie aprueba. (Antes habia CORS para la
# migracion desde SharePoint, ya terminada.)
@app.middleware("http")
async def _anti_csrf(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(seguridad.CSRF_HEADER) != "1":
        return JSONResponse({"detail": "Petición rechazada: falta el encabezado de la aplicación."}, status_code=403)
    return await call_next(request)


# Todo exige sesion salvo /auth/login, /auth/logout y /health. Los permisos
# finos (modulo + accion) los pide cada endpoint con seguridad.requiere().
SESION = [Depends(seguridad.usuario_actual)]
app.include_router(routes_auth.router)
app.include_router(routes_roles.router, dependencies=SESION)
app.include_router(routes_catalogo.router, dependencies=SESION)
app.include_router(routes_solicitudes.router, dependencies=SESION)
app.include_router(routes_planeacion.router, dependencies=SESION)
app.include_router(routes_config.router, dependencies=SESION)
# La migracion de SharePoint ya se hizo; queda solo para administradores.
app.include_router(routes_migracion.router, dependencies=[Depends(seguridad.requiere("usuarios", "editar"))])


@app.on_event("startup")
def _al_arrancar():
    seguridad.sembrar_roles()
    planeacion.recuperar_interrumpidos()


@app.get("/health")
def health():
    try:
        consultar("SELECT 1 AS ok")
        base = "ok"
    except Exception as exc:
        base = f"error: {type(exc).__name__}"
    return {"status": "ok", "base_datos": base}


# --- produccion: frontend + API en un solo servicio (Azure App Service) -------
# El deploy copia el build del frontend (vite build) a backend/static. Igual que el
# proxy de Vite en desarrollo, /api/* llega a la API sin el prefijo; lo demas es la
# SPA: una ruta del navegador que no es un archivo (/seguimiento, /usuarios...)
# devuelve index.html y React Router la resuelve.
ESTATICOS = Path(__file__).resolve().parent.parent / "static"


class _Spa(StaticFiles):
    async def get_response(self, path, scope):
        try:
            respuesta = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            respuesta = await super().get_response("index.html", scope)
        if respuesta.media_type == "text/html":
            # index.html siempre se revalida: despues de un deploy apunta a los assets nuevos
            respuesta.headers["Cache-Control"] = "no-cache"
        return respuesta


def _con_frontend(api, carpeta: Path):
    spa = _Spa(directory=carpeta, html=True)

    async def asgi(scope, receive, send):
        if scope["type"] == "http":
            ruta = scope["path"]
            if ruta != "/api" and not ruta.startswith("/api/"):
                return await spa(scope, receive, send)
            scope = {**scope, "path": ruta[4:] or "/", "root_path": scope.get("root_path", "") + "/api"}
            if scope.get("raw_path"):
                scope["raw_path"] = scope["raw_path"][4:] or b"/"
        await api(scope, receive, send)   # incluye "lifespan": el arranque de la API corre igual

    return asgi


servidor = _con_frontend(app, ESTATICOS) if (ESTATICOS / "index.html").exists() else app
