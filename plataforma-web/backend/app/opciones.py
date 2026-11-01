# -*- coding: utf-8 -*-
"""
Listas editables desde Configuracion (items.config_opciones).

Las usan el formulario de solicitudes (opciones activas) y la validacion del
backend. Se agregan o se desactivan; no se renombran ni se borran, porque las
solicitudes guardan el nombre como texto y el historico no debe cambiar.
"""
from app.db.session import consultar

# clave -> etiqueta. Agregar una lista nueva es agregarla aqui (y sembrarla).
LISTAS = {
    "materiales": "Tipo de material",
    "tipos_solicitud": "Tipo de solicitud",
    "cargos": "Cargo",
}
MAX_NOMBRE = 60

# Opciones que el codigo usa por nombre y por eso no se pueden desactivar.
PROTEGIDAS = {
    ("cargos", "Comercial"): "De este cargo salen los vendedores de las solicitudes.",
}


def protegida(lista: str, nombre: str) -> str | None:
    """El motivo si la opcion no se puede desactivar (comparacion sin mayusculas)."""
    for (l, n), motivo in PROTEGIDAS.items():
        if l == lista and n.lower() == (nombre or "").lower():
            return motivo
    return None


def activas(lista: str) -> list[str]:
    return [f["nombre"] for f in consultar("""
        SELECT nombre FROM items.config_opciones
         WHERE lista = :l AND activo = 1
         ORDER BY orden, nombre
    """, l=lista)]


def canonica(lista: str, nombre: str | None) -> str | None:
    """El nombre tal como esta configurado (la comparacion no distingue mayusculas), o None si no esta activo."""
    if not nombre:
        return None
    filas = consultar("""
        SELECT nombre FROM items.config_opciones WHERE lista = :l AND nombre = :n AND activo = 1
    """, l=lista, n=nombre.strip())
    return filas[0]["nombre"] if filas else None
