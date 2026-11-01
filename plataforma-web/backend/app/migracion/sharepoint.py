# -*- coding: utf-8 -*-
"""
Migracion del historico de la lista de SharePoint a items.solicitudes.

Como llegan los datos: el backend no tiene credenciales de Graph API, asi que
la extraccion la hace el navegador (que si tiene sesion autenticada contra
SharePoint) y empuja los registros crudos a POST /migracion/lote. Ver
scripts/extraer_sharepoint.js.

Lo que resuelve este modulo, por cada fila:

  Marca    (texto libre)  -> items.cat_marcas.id      ; si no casa -> marca_nueva_texto
  CLIENTE  (texto libre)  -> dbo.PQRS_ClientesSiesa.Id; el original SIEMPRE se
                             guarda en cliente_texto (solo ~50% casa, el resto
                             son personas y prospectos que no son clientes Siesa)
  Calibre  (choice)       -> items.cat_calibres.id
  Vendedor (people)       -> items.vendedores.id por correo
  Titulo   (texto libre)  -> items.cat_items_base.referencia usando el matcher
                             estructural. Lo que no resuelve queda en NULL con
                             el motivo, nunca se adivina.

Es idempotente: `sharepoint_item_id` tiene indice unico, y las filas ya
migradas se omiten.
"""
import re
from typing import Any

from sqlalchemy import text

from app.db.session import consultar, engine
from app.siesa.matcher import Catalogo, norm

# ItemenSistema de SharePoint -> estado nuestro
ESTADOS = {"Creado": "Creado", "Pendiente": "Pendiente"}


def _catalogo() -> Catalogo:
    """
    Arma el Catalogo del matcher a partir de las tablas ya cargadas en SQL,
    traduciendo al shape que espera (viene de las consultas de Siesa).
    """
    ext1 = [{"f117_descripcion": m["descripcion"], "f117_id": m["id"],
             "f117_ts": str(m["fecha_siesa"] or "")}
            for m in consultar("SELECT id, descripcion, fecha_siesa FROM items.cat_marcas")]
    ext2 = [{"f119_descripcion": c["descripcion"], "f119_id": c["id"]}
            for c in consultar("SELECT id, descripcion FROM items.cat_calibres")]
    items = [{"REFERENCIA": e["referencia"], "DESCRIPCION": e["descripcion"],
              "MARCA KOS": e["marca_desc"] or "", "CALIBRE": e["calibre_id"] or "",
              "SKU_SIESA": e["sku_siesa"]}
             for e in consultar("""
                SELECT x.sku_siesa, x.referencia, b.descripcion, x.marca_desc, x.calibre_id
                  FROM items.cat_extensiones_existentes x
                  JOIN items.cat_items_base b ON b.referencia = x.referencia
             """)]
    return Catalogo(ext1, ext2, items)


def _indices():
    clientes = {norm(c["Nombre"]): c["Id"]
                for c in consultar("SELECT Id, Nombre FROM dbo.PQRS_ClientesSiesa")}
    vendedores = {v["email"].lower(): v["id"]
                  for v in consultar("SELECT id, email FROM items.vendedores")}
    ya = {r["sharepoint_item_id"]
          for r in consultar("SELECT sharepoint_item_id FROM items.solicitudes "
                             "WHERE sharepoint_item_id IS NOT NULL")}
    return clientes, vendedores, ya


def _etapa(fila: dict) -> int:
    """
    Infiere hasta que etapa llego, con las columnas de SharePoint.

    Es una INFERENCIA, no un dato que la lista guarde: SharePoint no tiene
    tracking, solo estos flags sueltos. Se toma la etapa mas avanzada con
    evidencia; ante la duda se queda corta (etapa 1).
    """
    etapa = 1                                             # Solicitud de Diseño
    if fila.get("Aprobacion"):
        etapa = max(etapa, 2)                             # Aprobación de Diseño
    if ESTADOS.get(fila.get("ItemenSistema")) == "Creado":
        etapa = max(etapa, 3)                             # Creación de item
    if fila.get("PedidoUnoe") == "Montado":
        etapa = max(etapa, 4)                             # Digitación de Pedido
    if fila.get("Planchas") == "En Planta":
        etapa = max(etapa, 5)                             # Llegada de Planchas
    elif fila.get("Planchas") == "En Proceso":
        etapa = max(etapa, 6)                             # En producción
    return etapa


def _fecha(v):
    """SharePoint manda ISO con Z; SQL Server lo quiere sin zona."""
    if not v:
        return None
    return re.sub(r"Z$", "", str(v))


def migrar_lote(filas: list[dict[str, Any]]) -> dict:
    cat = _catalogo()
    clientes, vendedores, ya_migradas = _indices()

    insertadas = omitidas = 0
    sin_item_base = sin_marca = sin_cliente = sin_vendedor = 0

    with engine.begin() as conn:
        for f in filas:
            sp_id = f.get("Id")
            if sp_id is None or sp_id in ya_migradas:
                omitidas += 1
                continue

            titulo = (f.get("Title") or "").strip()
            marca_txt = (f.get("Marca") or "").strip()
            cliente_txt = (f.get("CLIENTE") or "").strip()

            # --- marca
            marca_id, _, _ = cat.buscar_marca(marca_txt)
            if not marca_id:
                sin_marca += 1

            # --- cliente: el texto original se conserva siempre
            cliente_id = clientes.get(norm(cliente_txt))
            if not cliente_id:
                sin_cliente += 1

            # --- calibre
            calibre_id = cat.buscar_calibre(f.get("Calibre") or "")

            # --- item base (matcher estructural; no adivina)
            ref, motivo, _ = cat.buscar_item(titulo, marca_txt, cliente_txt)
            if not ref:
                sin_item_base += 1

            # --- vendedor
            vend = f.get("Vendedor") or {}
            vend_email = (vend.get("EMail") or "").strip()
            vendedor_id = vendedores.get(vend_email.lower())
            if not vendedor_id:
                sin_vendedor += 1

            estado = ESTADOS.get(f.get("ItemenSistema") or "", "Pendiente")
            motivo_bloqueo = None
            if estado != "Creado":
                faltantes = []
                if not marca_id:
                    faltantes.append(f"marca '{marca_txt}' no existe en Ext1")
                if not ref:
                    faltantes.append(f"item base sin resolver ({motivo})")
                if faltantes:
                    estado = "Bloqueado"
                    motivo_bloqueo = "; ".join(faltantes)[:400]

            etapa = _etapa(f)
            tipos = f.get("TipoSolicitud")
            tipo_solicitud = ", ".join(tipos) if isinstance(tipos, list) else (tipos or None)

            nuevo = conn.execute(text("""
                INSERT INTO items.solicitudes
                    (sharepoint_item_id, titulo, marca_id, marca_nueva_texto,
                     cliente_id, cliente_texto, item_base_referencia, calibre_id,
                     tipo_material, cantidad, vendedor_id, vendedor_email, vendedor_nombre,
                     estado, motivo_bloqueo, pedido_unoe, op_entregada_diseno,
                     cab_plancha, planchas, fecha_planchas, tipo_solicitud,
                     aprobacion, disenador, creado_por, modificado_por,
                     fecha_creado, fecha_modificado, etapa_actual_id, origen)
                OUTPUT INSERTED.id
                VALUES
                    (:sp_id, :titulo, :marca_id, :marca_nueva,
                     :cliente_id, :cliente_texto, :ref, :calibre,
                     :material, :cantidad, :vend_id, :vend_email, :vend_nombre,
                     :estado, :motivo, :pedido, :op_fecha,
                     :cab, :planchas, :fplanchas, :tipo_sol,
                     :aprob, :disenador, :creado_por, :modif_por,
                     :fcreado, :fmodif, :etapa, 'migracion_sharepoint')
            """), {
                "sp_id": sp_id, "titulo": titulo or None,
                "marca_id": marca_id, "marca_nueva": None if marca_id else (marca_txt or None),
                "cliente_id": cliente_id, "cliente_texto": cliente_txt or None,
                "ref": ref, "calibre": calibre_id,
                "material": (f.get("TipodeMaterial") or "P1")[:20],
                "cantidad": int(f.get("Cantidad") or 0),
                "vend_id": vendedor_id,
                "vend_email": vend_email or "desconocido@koscolombia.com",
                "vend_nombre": vend.get("Title") or "Desconocido",
                "estado": estado, "motivo": motivo_bloqueo,
                "pedido": f.get("PedidoUnoe"),
                "op_fecha": _fecha(f.get("SOLICITUDENTREGADAADISE_x00d1_O")),
                "cab": f.get("CabPlancha"), "planchas": f.get("Planchas"),
                "fplanchas": _fecha(f.get("FechaPlanchas")),
                "tipo_sol": tipo_solicitud,
                "aprob": 1 if f.get("Aprobacion") else 0,
                "disenador": f.get("Dise_x00f1_ador"),
                "creado_por": (f.get("Author") or {}).get("Title"),
                "modif_por": (f.get("Editor") or {}).get("Title"),
                "fcreado": _fecha(f.get("Created")),
                "fmodif": _fecha(f.get("Modified")),
                "etapa": etapa,
            }).first()

            # Un evento de seguimiento que refleja el estado con el que llego.
            # Se marca como migrado para no confundirlo con un avance real.
            conn.execute(text("""
                INSERT INTO items.seguimiento
                    (solicitud_id, etapa_id, observacion, usuario_nombre, fecha)
                VALUES (:id, :etapa, :obs, :quien, :fecha)
            """), {
                "id": nuevo[0], "etapa": etapa,
                "obs": f"Migrado desde SharePoint (item {sp_id}). Estado al migrar: {estado}.",
                "quien": vend.get("Title") or "Migración",
                "fecha": _fecha(f.get("Modified")) or _fecha(f.get("Created")),
            })

            ya_migradas.add(sp_id)
            insertadas += 1

    return {"insertadas": insertadas, "omitidas": omitidas,
            "sin_item_base": sin_item_base, "sin_marca": sin_marca,
            "sin_cliente_siesa": sin_cliente, "sin_vendedor": sin_vendedor}
