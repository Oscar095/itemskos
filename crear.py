# -*- coding: utf-8 -*-
"""
Paso 2 - EL UNICO SCRIPT QUE ESCRIBE EN SIESA.

Consume salida/plan_creacion.csv (generado por analizar.py) y crea los items-extension
via el conector API_v1_ItemsExtensiones.

    python crear.py --dry-run          imprime los JSON exactos, no envia nada
    python crear.py --fila 879         crea UNA sola fila (usar esto primero)
    python crear.py --limite 3         crea las 3 primeras
    python crear.py                    crea todo el plan

El conector responde "Importacion exitosa" tanto si inserto como si la combinacion
ya existia, asi que `codigo:0` no distingue una cosa de la otra. La confirmacion real
es volver a correr analizar.py: lo creado debe pasar de plan_creacion.csv a
ya_existentes.csv. Se corta automaticamente si fallan dos filas seguidas.
"""
import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

import siesa_api
from catalogo import Catalogo, norm

BASE_DIR = Path(__file__).resolve().parent
SALIDA = BASE_DIR / "salida"
PLAN = SALIDA / "plan_creacion.csv"
LOG = SALIDA / "log_creacion.csv"

# --- Parametros del conector -------------------------------------------------
# Ajustar aqui segun lo que responda el conector; quedan documentados en siesa_api.py
# una vez confirmado el contrato con la primera creacion real.
F_CIA = "1"                 # las 3 consultas devuelven f_id_cia=1 (el 7501 de la URL es la clave Connekta)
F_ACTUALIZA_REG = "0"        # numerico obligatorio; 0 = no sobreescribir si ya existe
IND_ESTADO = "1"            # 1 = activo
FORMATO_FECHA = "%Y%m%d"     # el conector arma un plano de ancho fijo: 8 posiciones
ENVIAR_F120_ID = False      # hipotesis: Siesa autoasigna f120_id al crear la extension


def construir_registro(fila):
    return {
        "F_CIA": F_CIA,
        "F_ACTUALIZA_REG": F_ACTUALIZA_REG,
        "f120_id": fila["referencia"] if ENVIAR_F120_ID else "",
        "f120_referencia": fila["referencia"],
        "f121_id_ext1_detalle": fila["ext1_id"],
        "f121_id_ext2_detalle": fila["ext2_id"],
        "f121_ind_estado": IND_ESTADO,
        "f121_fecha_inactivacion": "",
        "f121_fecha_creacion": date.today().strftime(FORMATO_FECHA),
        "f120_id_item_ext_generico": "",
        "f120_referencia_item_ext_gen": "",
        "f121_id_ext1_detalle_gen": "",
        "f121_id_ext2_detalle_gen": "",
    }


def construir_payload(filas):
    return {
        "Inicial": [{"F_CIA": F_CIA}],
        "Version": [construir_registro(f) for f in filas],
        "Final": [{"F_CIA": F_CIA}],
    }


def leer_plan():
    if not PLAN.exists():
        sys.exit("No existe %s. Corre primero: python analizar.py" % PLAN)
    with open(PLAN, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def verificar(cat, fila):
    """
    Busca el SKU en koscolombia_Items_odoo_crm.

    Ojo con el momento: `cat` se carga ANTES del lote, asi que refleja el estado
    previo. Sirve para detectar que la combinacion YA existia (el conector responde
    "exitosa" igual y no se distinguiria), no para confirmar la insercion.
    Para confirmar, volver a correr analizar.py despues del lote.
    """
    sku = cat.existentes.get((fila["referencia"], norm(fila["marca"]), fila["ext2_id"]))
    return ";".join(str(s) for s in sku) if sku else ""


def ya_creadas():
    """Combinaciones que un run anterior ya envio con exito, para no reprocesarlas."""
    if not LOG.exists():
        return set()
    hechas = set()
    with open(LOG, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r.get("codigo") == "0":
                hechas.add((r["referencia"], r["ext1_id"], r["ext2_id"]))
    return hechas


def registrar(registros):
    """
    Escribe en LOG. Los POST a Siesa ya se hicieron antes de llegar aqui, asi que
    un fallo ESCRIBIENDO el log (tipico: alguien tiene log_creacion.csv abierto en
    Excel) no debe perder el resultado. Si LOG esta bloqueado, cae a un archivo
    alterno con timestamp y avisa donde quedo, en vez de reventar.
    """
    cols = ["fecha", "fila", "referencia", "descripcion_item", "marca", "ext1_id",
            "calibre", "ext2_id", "http", "codigo", "mensaje", "sku_creado"]
    destino = LOG
    try:
        nuevo = not destino.exists()
        with open(destino, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", delimiter=";")
            if nuevo:
                w.writeheader()
            for r in registros:
                w.writerow(r)
    except PermissionError:
        destino = SALIDA / f"log_creacion_pendiente_merge_{date.today().isoformat()}.csv"
        with open(destino, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", delimiter=";")
            w.writeheader()
            for r in registros:
                w.writerow(r)
        print(f"\nAVISO: {LOG.name} esta bloqueado (¿abierto en Excel?). "
              f"Los resultados de este lote quedaron en {destino.name} — "
              f"cierra el Excel y fusionalo con log_creacion.csv antes de la proxima corrida.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="imprime los JSON, no envia nada")
    ap.add_argument("--fila", type=int, help="crear solo esa fila del Excel")
    ap.add_argument("--limite", type=int, help="crear solo las N primeras")
    ap.add_argument("--usar-cache", action="store_true",
                    help="reutiliza cache/items.json (la consulta de items es lenta)")
    args = ap.parse_args()

    filas = leer_plan()
    if args.fila:
        filas = [f for f in filas if int(f["fila"]) == args.fila]
        if not filas:
            sys.exit("La fila %d no esta en plan_creacion.csv" % args.fila)
    if args.limite:
        filas = filas[:args.limite]

    print("Filas a procesar: %d" % len(filas))
    for f in filas:
        print("  fila %-4s %-12s %-32s %-18s %s"
              % (f["fila"], f["referencia"], f["descripcion_item"], f["marca"], f["calibre"]))

    if args.dry_run:
        print("\n--- DRY RUN: JSON que se enviaria (uno por fila) ---")
        for f in filas:
            print("\nfila %s:" % f["fila"])
            print(json.dumps(construir_payload([f]), indent=2, ensure_ascii=False))
        return 0

    if not filas:
        return 0

    SALIDA.mkdir(exist_ok=True)
    hechas = ya_creadas()
    pendientes = [f for f in filas if (f["referencia"], f["ext1_id"], f["ext2_id"]) not in hechas]
    if len(pendientes) < len(filas):
        print("\nSe omiten %d fila(s) que un run anterior ya creo con exito (ver log_creacion.csv)."
              % (len(filas) - len(pendientes)))
    if not pendientes:
        return 0

    cat = Catalogo([], [], siesa_api.consultar("items", usar_cache=args.usar_cache))
    resultados, fallos_seguidos = [], 0
    for f in pendientes:
        http, cuerpo = siesa_api.importar(construir_payload([f]))
        codigo = cuerpo.get("codigo") if isinstance(cuerpo, dict) else None
        if isinstance(cuerpo, dict):
            mensaje = "%s %s" % (cuerpo.get("mensaje", ""), cuerpo.get("detalle", ""))
        else:
            mensaje = str(cuerpo)

        ok = http == 200 and codigo == 0
        sku = verificar(cat, f) if ok else ""
        print("\nfila %s -> HTTP %s codigo=%s  %s" % (f["fila"], http, codigo, "OK" if ok else "FALLO"))
        print("   %s" % mensaje.strip()[:400])
        if ok and sku:
            print("   OJO: esta combinacion YA existia antes del lote (SKU %s). El conector"
                  "\n   responde 'exitosa' igual, asi que no se distingue de una insercion." % sku)

        resultados.append(dict(f, fecha=date.today().isoformat(), http=http,
                               codigo=codigo, mensaje=mensaje.strip()[:400], sku_creado=sku))
        fallos_seguidos = 0 if ok else fallos_seguidos + 1
        if fallos_seguidos >= 2:
            print("\nDos fallos seguidos: se detiene el lote para no insistir a ciegas.")
            break

    registrar(resultados)
    creados = sum(1 for r in resultados if r["codigo"] == 0)
    print("\nAceptados por el conector: %d de %d. Log: %s" % (creados, len(resultados), LOG))
    print("Para confirmar contra Siesa, volver a correr:  python analizar.py")
    return 0 if creados == len(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
