# -*- coding: utf-8 -*-
"""
Endpoints de catalogo: lo que alimenta los <select> del formulario.

Todos leen de la cache local en el esquema `items` (o de dbo.PQRS_ClientesSiesa
para clientes): la consulta de items en Siesa tarda ~350s. La excepcion son
las marcas, cuya consulta tarda segundos y se refresca sola (ver /marcas).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth.seguridad import requiere
from app.db.session import consultar
from app.siesa import marcas as marcas_siesa

router = APIRouter(prefix="/catalogos", tags=["catalogos"])


@router.get("/estado")
def estado():
    """Cuantas filas tiene cada catalogo y cuando se refresco por ultima vez."""
    filas = consultar("""
        SELECT 'marcas' AS catalogo, COUNT(1) AS filas, MAX(actualizado) AS actualizado
          FROM items.cat_marcas
        UNION ALL
        SELECT 'calibres', COUNT(1), MAX(actualizado) FROM items.cat_calibres
        UNION ALL
        SELECT 'items_base', COUNT(1), MAX(actualizado) FROM items.cat_items_base
        UNION ALL
        SELECT 'extensiones', COUNT(1), MAX(actualizado) FROM items.cat_extensiones_existentes
        UNION ALL
        SELECT 'solicitudes', COUNT(1), MAX(fecha_creado) FROM items.solicitudes
        UNION ALL
        SELECT 'clientes (PQRS)', COUNT(1), MAX(ActualizadoAt) FROM dbo.PQRS_ClientesSiesa
    """)
    return {"catalogos": filas}


@router.get("/clientes")
def clientes(q: str = Query("", description="filtro por nombre"), limite: int = 20):
    """
    Selector de cliente. Lee dbo.PQRS_ClientesSiesa, la tabla que PQRS ya
    mantiene sincronizada con Siesa — por eso no se duplica aqui.
    """
    return consultar(
        """
        SELECT TOP (:limite) Id AS id, Nombre AS nombre
          FROM dbo.PQRS_ClientesSiesa
         WHERE (:q = '' OR Nombre LIKE '%' + :q + '%')
         ORDER BY Nombre
        """,
        q=q, limite=limite,
    )


@router.get("/marcas")
def marcas(q: str = Query("", description="filtro por descripcion o codigo"), limite: int = 30):
    """
    Marcas disponibles en Ext1. A diferencia de los demas catalogos, este se
    refresca contra Siesa cada pocos minutos (ver app.siesa.marcas): las marcas
    se crean a diario y una cache vieja lleva a crearlas duplicadas.
    """
    marcas_siesa.refrescar()
    q = " ".join(q.split())
    return consultar(
        """
        SELECT TOP (:limite) id, descripcion, fecha_siesa
          FROM items.cat_marcas
         WHERE (:q = '' OR descripcion LIKE '%' + :q + '%' OR id = :q)
         ORDER BY CASE WHEN descripcion = :q OR id = :q THEN 0
                       WHEN descripcion LIKE :q + '%' THEN 1 ELSE 2 END,
                  descripcion, fecha_siesa DESC
        """,
        q=q, limite=limite,
    )


class MarcaNueva(BaseModel):
    descripcion: str
    usuario: Optional[str] = None  # ignorado: se usa el de la sesion


@router.get("/marcas/vista-previa")
def marca_vista_previa(descripcion: str, _=Depends(requiere("marcas", "crear"))):
    """Codigo que tomaria la marca y si ya hay otra con el mismo nombre. No crea nada."""
    try:
        return marcas_siesa.vista_previa(descripcion)
    except RuntimeError as exc:
        raise HTTPException(502, f"No se pudo consultar Ext1 en Siesa: {exc}")


@router.post("/marcas", status_code=201)
def crear_marca(m: MarcaNueva, usuario: dict = Depends(requiere("marcas", "crear"))):
    """Crea la marca en Siesa (Ext1) con el siguiente consecutivo."""
    try:
        # Queda auditada a nombre de quien inicio sesion, no de lo que mande el navegador.
        return marcas_siesa.crear(m.descripcion, usuario["nombre"])
    except marcas_siesa.ErrorMarca as exc:
        raise HTTPException(400, str(exc))


@router.get("/items-base")
def items_base(q: str = Query("", description="filtro por descripcion o referencia"), limite: int = 20):
    return consultar(
        """
        SELECT TOP (:limite) referencia, descripcion
          FROM items.cat_items_base
         WHERE (:q = '' OR descripcion LIKE '%' + :q + '%' OR referencia LIKE '%' + :q + '%')
         ORDER BY descripcion
        """,
        q=q, limite=limite,
    )


@router.get("/calibres")
def calibres():
    # Son 14 y no cambian casi nunca: se devuelven todos, sin filtro.
    return consultar("SELECT id, descripcion FROM items.cat_calibres ORDER BY descripcion")


@router.get("/vendedores")
def vendedores(incluir_inactivos: bool = False):
    """
    Vendedores extraidos del historico de SharePoint. Por defecto solo los
    activos: los dados de baja se conservan para no romper el historico de
    solicitudes viejas, pero no deben ofrecerse al crear una nueva.
    """
    return consultar(
        """
        SELECT id, nombre, email, activo, ultima_actividad
          FROM items.vendedores
         WHERE (:todos = 1 OR activo = 1)
         ORDER BY activo DESC, nombre
        """,
        todos=1 if incluir_inactivos else 0,
    )


@router.get("/comerciales")
def comerciales():
    """
    Vendedores que se pueden elegir en una solicitud NUEVA: usuarios activos con
    cargo Comercial (su `vendedor_id` lo liga sincronizar_vendedor). El
    historico de vendedores sigue en /vendedores para filtrar el seguimiento.
    """
    return consultar("""
        SELECT u.vendedor_id AS id, u.id AS usuario_id, u.nombre, u.email
          FROM items.usuarios u
         WHERE u.activo = 1 AND u.cargo = 'Comercial' AND u.vendedor_id IS NOT NULL
         ORDER BY u.nombre
    """)


@router.get("/etapas")
def etapas():
    return consultar("SELECT id, nombre, orden FROM items.etapas ORDER BY orden")
