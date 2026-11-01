# -*- coding: utf-8 -*-
"""
Configuracion del backend.

Lee el .env (antes .env.txt) de la raiz del proyecto (dos niveles arriba), que es donde ya
viven las credenciales de Siesa y de la base. Deliberadamente NO se copian a un
.env propio del backend: duplicar secretos en dos archivos es como se terminan
filtrando, y ese archivo ya es la fuente de verdad para analizar.py / crear.py.

En Azure App Service no hay .env (no se sube al repositorio): las mismas claves se
definen como variables de entorno de la Web App y, si existen, mandan sobre el archivo.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent      # .../plataforma-web/backend
RAIZ = BASE_DIR.parent.parent                           # .../Creacion items
# Se renombro a .env (2026-10-31); .env.txt queda como respaldo.
ENV_PATH = next((p for p in (RAIZ / ".env", RAIZ / ".env.txt") if p.exists()), RAIZ / ".env")


def _cargar(path: Path) -> dict:
    cfg = {}
    if not path.exists():
        return cfg
    for linea in path.read_text(encoding="utf-8-sig").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or linea.startswith("{"):
            continue
        clave, sep, valor = linea.partition("=")
        if sep:
            cfg[clave.strip()] = valor.strip()
    return cfg


_ARCHIVO = _cargar(ENV_PATH)


def _cfg(clave: str, defecto: str = "") -> str:
    # En Linux el nombre de la variable respeta mayusculas; se acepta tambien en mayusculas.
    return os.environ.get(clave) or os.environ.get(clave.upper()) or _ARCHIVO.get(clave, defecto)


class Settings:
    # --- Siesa Connekta ---
    siesa_conni_key: str = _cfg("ConniKey", "")
    siesa_conni_token: str = _cfg("ConniToken", "")
    siesa_id_compania: str = "7501"
    siesa_api_creacion_items: str = _cfg("API_CREACION_ITEMS", "")
    # La URL del .env.txt trae el marcador literal {idSistema}; se reemplaza en
    # app.siesa.client. Cualquier entero pasa la validacion de estructura.
    siesa_api_creacion_marcas: str = _cfg("API_CREACION_MARCAS", "")
    siesa_id_sistema: str = _cfg("ID_SISTEMA", "2")
    # Parametros de planeacion (conector PARAMETROS_ITEMS_V5) y su catalogo de rutas.
    siesa_api_param_planeacion: str = _cfg("API_CREACION_PARAM_PLANEACION", "")
    siesa_api_rutas: str = _cfg("API_RUTAS", "")

    # --- Sesion: en produccion (HTTPS) COOKIE_SECURE=1 (variable de la Web App) ---
    cookie_secure: bool = _cfg("COOKIE_SECURE", "0").lower() in ("1", "true", "si")

    # --- Azure SQL (base kx_ecommerce, esquema `items`) ---
    bd_host: str = _cfg("BD_HOST", "")
    bd_name: str = _cfg("BD_NAME", "")
    bd_user: str = _cfg("BD_USER", "")
    bd_password: str = _cfg("BD_PASSWORD", "")
    esquema: str = "items"

    # --- Datalake (cuenta datalakekos) para adjuntos ---
    azure_storage_conn: str = _cfg("AZURE_STORAGE_ACCOUNT", "")
    # Contenedor propio, siguiendo la convencion de la cuenta (pqrs-attachments,
    # evaluaciones, facturas...): una aplicacion, un contenedor.
    contenedor_adjuntos: str = "items-adjuntos"

    # --- SharePoint (lista que esta plataforma reemplaza) ---
    sharepoint_site_url: str = "https://koscolombiacali.sharepoint.com/sites/INTRANETKOS"
    sharepoint_list_id: str = "c0b3e740-d705-4f48-9c6a-d8e88082bae0"

    catalogo_refresco_minutos: int = 60

    @property
    def sqlalchemy_url(self) -> str:
        # pymssql, no pyodbc: ver el comentario en requirements.txt
        return (f"mssql+pymssql://{self.bd_user}:{self.bd_password}"
                f"@{self.bd_host}/{self.bd_name}")


settings = Settings()
