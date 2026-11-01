# -*- coding: utf-8 -*-
"""
Paso 1 - SOLO LECTURA. No escribe nada en Siesa ni en el Excel.

Lee las filas "Pendiente" de ITEMS CREAR.xlsx, resuelve para cada una las tres claves
(item base, Ext1=marca, Ext2=calibre) y reparte el resultado en la carpeta salida/:

  plan_creacion.csv        lo unico que crear.py va a crear
  ya_existentes.csv        combinaciones que ya estan en Siesa (marcar "Creado" en SharePoint)
  marcas_faltantes.txt     marcas que hay que dar de alta en Ext1 primero
  items_base_faltantes.txt titulos sin item base en Siesa
  revision_manual.csv      consolidado de todo lo que NO se va a crear, con el motivo

El xlsx es una tabla conectada en vivo a SharePoint (INTRANETKOS): se lee, nunca se escribe.
"""
import csv
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import siesa_api
from catalogo import Catalogo, canon, clave_item, norm, revisar_material

BASE_DIR = Path(__file__).resolve().parent
XLSX = BASE_DIR / "ITEMS CREAR.xlsx"
SALIDA = BASE_DIR / "salida"
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

COLUMNAS = {"A": "titulo", "B": "marca", "C": "cliente", "D": "calibre",
            "E": "material", "F": "cantidad", "G": "vendedor", "H": "estado"}


def leer_xlsx(path=XLSX):
    """Lee el xlsx con la stdlib (no hace falta openpyxl y no se toca el archivo)."""
    z = zipfile.ZipFile(path)
    cadenas = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(NS + "si"):
            cadenas.append("".join(t.text or "" for t in si.iter(NS + "t")))
    filas = []
    for row in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter(NS + "row"):
        celdas = {}
        for c in row.findall(NS + "c"):
            col = re.match(r"[A-Z]+", c.get("r")).group()
            if col not in COLUMNAS:
                continue
            tipo, v = c.get("t"), c.find(NS + "v")
            if tipo == "s" and v is not None:
                valor = cadenas[int(v.text)]
            elif v is not None:
                valor = v.text
            else:
                valor = ""
            celdas[COLUMNAS[col]] = (valor or "").strip()
        filas.append((int(row.get("r")), celdas))
    return filas


def candidatos_parecidos(cat, titulo, marca, cliente, maximo=4):
    """
    Items base cercanos, SOLO como pista para el humano (nunca se asumen).
    Prioriza misma familia y misma linea (KX/DP/LDP), luego cercania de tamano.
    Si la familia no existe en el catalogo (p.ej. TAZON), cae a items del mismo tamano.
    """
    ruido = set(norm(marca).split()) | set(norm(cliente).split())
    tokens = [t for t in canon(titulo).split() if t not in ruido]
    clave, _ = clave_item(" ".join(tokens))
    if not clave:
        return []
    familia, linea, mods, tam = clave
    puntuados = []
    for ref, desc in cat.desc_por_ref.items():
        k, _ = clave_item(desc)
        if not k:
            continue
        misma_familia = k[0] == familia
        if not misma_familia and not (set(k[3]) & set(tam)):
            continue
        puntos = 8 if misma_familia else 0
        puntos += 4 if k[1] == linea else (2 if k[1] & linea else 0)
        puntos += 2 * len(set(k[3]) & set(tam))
        puntos += 1 if k[2] == mods else 0
        distancia = min((abs(a - b) for a in k[3] for b in tam), default=999)
        puntuados.append((-puntos, distancia, desc, ref))
    puntuados.sort()
    return [(ref, desc) for _, _, desc, ref in puntuados[:maximo]]


def main():
    SALIDA.mkdir(exist_ok=True)
    print("Consultando catalogos de Siesa...")
    cache = "--usar-cache" in sys.argv
    cat = Catalogo(siesa_api.consultar("ext1", usar_cache=cache),
                   siesa_api.consultar("ext2", usar_cache=cache),
                   siesa_api.consultar("items", usar_cache=cache))
    print("  Ext1 (marcas): %d | Ext2 (calibres): %d | items base: %d | SKUs: %d"
          % (len(cat.marcas), len(cat.calibres), len(cat.desc_por_ref),
             sum(cat.skus_por_ref.values())))

    pendientes = [(r, c) for r, c in leer_xlsx()[1:] if c.get("estado") == "Pendiente"]
    print("Filas 'Pendiente' en el Excel: %d" % len(pendientes))

    creadas_por_nosotros = set()
    log = SALIDA / "log_creacion.csv"
    if log.exists():
        with open(log, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter=";"):
                if r.get("codigo") == "0":
                    creadas_por_nosotros.add((r["referencia"], r["ext1_id"], r["ext2_id"]))
        print("Combinaciones ya creadas segun log_creacion.csv: %d" % len(creadas_por_nosotros))

    a_crear, ya_existen, bloqueadas = [], [], []
    sin_marca = defaultdict(list)
    sin_item = []
    vistos = {}

    for fila, c in pendientes:
        reg = {"fila": fila, "titulo": c["titulo"], "marca": c["marca"],
               "cliente": c["cliente"], "calibre": c["calibre"],
               "material": c["material"], "vendedor": c.get("vendedor", "")}

        ext1_id, marca_desc, candidatos = cat.buscar_marca(c["marca"])
        ext2_id = cat.buscar_calibre(c["calibre"])
        ref, motivo, ignorados = cat.buscar_item(c["titulo"], c["marca"], c["cliente"])

        reg.update({"referencia": ref or "", "ext1_id": ext1_id or "", "ext2_id": ext2_id or "",
                    "descripcion_item": cat.desc_por_ref.get(ref, ""),
                    "tokens_ignorados": " ".join(ignorados)})

        if ext1_id is None:
            sin_marca[c["marca"].strip()].append(reg)
            bloqueadas.append(dict(reg, motivo="marca no existe en Ext1"))
            if ref is None:
                sin_item.append((reg, motivo))
            continue
        if ext2_id is None:
            bloqueadas.append(dict(reg, motivo="calibre '%s' no existe en Ext2" % c["calibre"]))
            continue
        if ref is None:
            sin_item.append((reg, motivo))
            bloqueadas.append(dict(reg, motivo="item base: " + motivo))
            continue

        aviso = revisar_material(c["material"], ref, cat)
        if aviso:
            bloqueadas.append(dict(reg, motivo=aviso))
            continue

        # Ya creada por este proceso. Se consulta el log ANTES que la consulta de items
        # porque koscolombia_Items_odoo_crm no muestra items recien creados (sin costo aun).
        if (ref, ext1_id, ext2_id) in creadas_por_nosotros:
            ya_existen.append(dict(reg, sku_siesa="creado por este proceso"))
            continue

        sku = cat.sku_existente(ref, c["marca"], ext2_id)
        if sku:
            ya_existen.append(dict(reg, sku_siesa=";".join(str(s) for s in sku)))
            continue

        clave = (ref, ext1_id, ext2_id)
        if clave in vistos:
            bloqueadas.append(dict(reg, motivo="duplicado de la fila %d en el propio Excel" % vistos[clave]))
            continue
        vistos[clave] = fila

        reg["marca_desc"] = marca_desc
        reg["confianza"] = "ALTA"
        notas = []
        if len(candidatos) > 1:
            notas.append("marca duplicada en Ext1 (%s); se usa la mas reciente" % ",".join(candidatos))
            reg["confianza"] = "MEDIA"
        if ignorados:
            notas.append("palabras ignoradas del titulo: " + " ".join(ignorados))
            reg["confianza"] = "MEDIA"
        if motivo != "ok":
            notas.append(motivo)
            reg["confianza"] = "MEDIA"
        reg["notas"] = " | ".join(notas)
        a_crear.append(reg)

    # ---------------------------------------------------------------- salidas
    cols_plan = ["fila", "confianza", "referencia", "descripcion_item", "marca", "marca_desc",
                 "ext1_id", "calibre", "ext2_id", "material", "cliente", "vendedor", "notas"]
    escribir_csv(SALIDA / "plan_creacion.csv", cols_plan, a_crear)

    cols_ya = ["fila", "sku_siesa", "referencia", "descripcion_item", "marca", "calibre", "cliente"]
    escribir_csv(SALIDA / "ya_existentes.csv", cols_ya, ya_existen)
    # Mismo contenido, pensado para pasarlo a la lista de SharePoint: son las filas
    # cuyo "Item en Sistema" ya se puede mover de Pendiente a Creado.
    escribir_csv(SALIDA / "marcar_creado_en_sharepoint.csv", cols_ya, ya_existen)

    cols_rev = ["fila", "motivo", "titulo", "marca", "calibre", "material", "cliente",
                "referencia", "descripcion_item", "tokens_ignorados"]
    escribir_csv(SALIDA / "revision_manual.csv", cols_rev, bloqueadas)

    with open(SALIDA / "marcas_faltantes.txt", "w", encoding="utf-8") as f:
        f.write("MARCAS QUE NO EXISTEN EN LA EXTENSION 1 (MK) DE SIESA\n")
        f.write("Hay que crearlas primero; hasta entonces sus items no se pueden crear.\n")
        f.write("=" * 78 + "\n\n")
        for marca in sorted(sin_marca):
            regs = sin_marca[marca]
            f.write("* %s   (%d fila%s del Excel)\n" % (marca, len(regs), "" if len(regs) == 1 else "s"))
            for r in regs:
                f.write("    fila %-4d %-34s cliente: %s\n" % (r["fila"], r["titulo"], r["cliente"]))
            parecidas = cat.marcas_parecidas(marca)
            if parecidas:
                f.write("    ojo, ya existe algo parecido: " + " / ".join(parecidas) + "\n")
            f.write("\n")
        f.write("Total: %d marcas distintas, %d filas bloqueadas.\n"
                % (len(sin_marca), sum(len(v) for v in sin_marca.values())))

    with open(SALIDA / "items_base_faltantes.txt", "w", encoding="utf-8") as f:
        f.write("TITULOS SIN ITEM BASE EN SIESA\n")
        f.write("El item base (referencia) debe existir antes de poder crearle extensiones.\n")
        f.write("=" * 78 + "\n\n")
        for reg, motivo in sin_item:
            f.write("* fila %-4d %s\n" % (reg["fila"], reg["titulo"]))
            f.write("    cliente: %-32s marca: %s\n" % (reg["cliente"], reg["marca"]))
            f.write("    motivo:  %s\n" % motivo)
            cands = candidatos_parecidos(cat, reg["titulo"], reg["marca"], reg["cliente"])
            if cands:
                f.write("    items base parecidos que SI existen (no se asumio ninguno):\n")
                for ref, desc in cands:
                    f.write("        %-12s %s\n" % (ref, desc))
            f.write("\n")
        f.write("Total: %d filas.\n" % len(sin_item))

    # ---------------------------------------------------------------- resumen
    print("\nRESUMEN")
    print("  a crear ..................... %3d  -> salida/plan_creacion.csv" % len(a_crear))
    print("  ya existentes en Siesa ...... %3d  -> salida/ya_existentes.csv" % len(ya_existen))
    print("  bloqueadas .................. %3d  -> salida/revision_manual.csv" % len(bloqueadas))
    motivos = defaultdict(int)
    for b in bloqueadas:
        motivos[b["motivo"].split(":")[0].split("(")[0].strip()] += 1
    for m, n in sorted(motivos.items(), key=lambda x: -x[1]):
        print("      %-52s %3d" % (m[:52], n))
    print("\n  marcas distintas por crear en Ext1: %d -> salida/marcas_faltantes.txt" % len(sin_marca))
    print("  filas sin item base: %d -> salida/items_base_faltantes.txt" % len(sin_item))
    total = len(a_crear) + len(ya_existen) + len(bloqueadas)
    print("\n  control: %d + %d + %d = %d (pendientes leidas: %d)%s"
          % (len(a_crear), len(ya_existen), len(bloqueadas), total, len(pendientes),
             "" if total == len(pendientes) else "   <-- DESCUADRE"))


def escribir_csv(path, columnas, registros):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas, extrasaction="ignore", delimiter=";")
        w.writeheader()
        for r in sorted(registros, key=lambda x: x["fila"]):
            w.writerow(r)


if __name__ == "__main__":
    sys.exit(main())
