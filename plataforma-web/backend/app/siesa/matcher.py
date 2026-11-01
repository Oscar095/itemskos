# -*- coding: utf-8 -*-
"""
Normalizacion y emparejamiento contra los catalogos de Siesa.

El emparejamiento de item base es ESTRUCTURAL, no difuso, a proposito:
difflib propone "CONT KX 4 Oz" para "CONTENEDOR KX 14 OZ" con 0.96 de similitud,
cuando el item base correcto sencillamente no existe. Aqui una fila solo se empareja
si (familia, linea, modificadores, tamanos) coinciden EXACTAMENTE. Si no, va a revision.
"""
import difflib
import re
import unicodedata
from collections import defaultdict

# Palabras que no aportan al identificador del item
RELLENO = {"OZ", "UND", "UNDS", "U", "X", "DE", "Y"}
# Lineas de producto (kraft exterior / doble pared / libre de plastico)
LINEAS = {"KX", "DP", "LDP"}


def sin_acentos(texto):
    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()


def canon(texto):
    """Canoniza una descripcion de item: mayusculas, sinonimos y separadores unificados."""
    t = sin_acentos(texto).upper()
    t = re.sub(r"LIBRE\s+DE\s+PLASTICO", " LDP ", t)
    t = re.sub(r"\bCONTENEDOR(ES)?\b", "CONT", t)
    t = re.sub(r"\bTAZON(ES)?\b", "CONT", t)  # regla del negocio: todo "Tazon" es "Cont" (confirmado 2026-09-03)
    t = re.sub(r"\bONZAS?\b|\bONZ\b", "OZ", t)
    t = re.sub(r"(\d)[.,](\d{3})\b", r"\1\2", t)   # 1.650 -> 1650
    t = re.sub(r"(\d)\s*OZ\b", r"\1 OZ", t)        # 9OZ / 7Oz -> 9 OZ
    t = re.sub(r"[^A-Z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def norm(texto):
    """Normalizacion simple para marcas y calibres (sin sinonimos de producto)."""
    t = sin_acentos(texto).upper()
    t = re.sub(r"[^A-Z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def clave_item(descripcion):
    """Convierte una descripcion en la tupla comparable (familia, linea, mods, tamanos)."""
    tokens = canon(descripcion).split()
    if not tokens:
        return None, []
    familia = tokens[0]
    linea, mods, numeros = set(), set(), []
    for tok in tokens[1:]:
        if tok.isdigit():
            numeros.append(int(tok))
        elif tok in LINEAS:
            linea.add(tok)
        elif tok not in RELLENO:
            mods.add(tok)
    return (familia, frozenset(linea), frozenset(mods), tuple(sorted(numeros))), tokens


class Catalogo:
    """Indices sobre las tres consultas GET de Siesa."""

    def __init__(self, filas_ext1, filas_ext2, filas_items):
        # --- Ext1: marca. Hay codigos duplicados para el mismo nombre;
        #     decision acordada: usar el de f117_ts mas reciente.
        self.marcas = defaultdict(list)
        for f in filas_ext1:
            self.marcas[norm(f["f117_descripcion"])].append(
                (f["f117_id"].strip(), f["f117_descripcion"].strip(), f["f117_ts"])
            )
        for k in self.marcas:
            self.marcas[k].sort(key=lambda x: x[2], reverse=True)

        # --- Ext2: calibre
        self.calibres = {norm(f["f119_descripcion"]): f["f119_id"].strip() for f in filas_ext2}

        # --- Items: 164 referencias base + los SKUs ya creados
        self.desc_por_ref, self.skus_por_ref = {}, defaultdict(int)
        self.existentes = defaultdict(list)
        for f in filas_items:
            ref = f["REFERENCIA"].strip()
            self.desc_por_ref[ref] = f["DESCRIPCION"].strip()
            self.skus_por_ref[ref] += 1
            self.existentes[(ref, norm(f["MARCA KOS"]), f["CALIBRE"].strip())].append(f["SKU_SIESA"])

        # Indice de items base por clave estructural
        self.por_clave = defaultdict(list)
        self.vocabulario = set()
        for ref, desc in self.desc_por_ref.items():
            clave, tokens = clave_item(desc)
            if clave:
                self.por_clave[clave].append(ref)
            self.vocabulario.update(t for t in tokens if not t.isdigit())

    # ------------------------------------------------------------------ marca
    def buscar_marca(self, nombre):
        """Devuelve (id_elegido, descripcion, candidatos). id_elegido=None si no existe."""
        cands = self.marcas.get(norm(nombre), [])
        if not cands:
            return None, None, []
        return cands[0][0], cands[0][1], [c[0] for c in cands]

    def marcas_parecidas(self, nombre, maximo=3):
        """
        Sugerencias de marca casi identica, solo informativas (nunca se asumen).
        Sirve para cazar variantes tipograficas: "DE LOLITA CAFE" vs "D LOLITA CAFE".
        """
        n = norm(nombre)
        if len(n) < 3:
            return []
        tok_n = set(n.split())
        puntuadas = []
        for clave, cands in self.marcas.items():
            # "-" (marca comodin 9999) normaliza a cadena vacia y seria "parecida" a todo
            if clave == n or len(clave) < 3:
                continue
            ratio = difflib.SequenceMatcher(None, n, clave).ratio()
            tok_c = set(clave.split())
            comunes = tok_n & tok_c
            jaccard = len(comunes) / len(tok_n | tok_c)
            if ratio >= 0.80 or (len(comunes) >= 2 and jaccard >= 0.5):
                puntuadas.append((-max(ratio, jaccard), cands[0][1] + " (" + cands[0][0] + ")"))
        puntuadas.sort()
        return [t for _, t in puntuadas[:maximo]]

    # --------------------------------------------------------------- calibre
    def buscar_calibre(self, nombre):
        return self.calibres.get(norm(nombre))

    # ------------------------------------------------------------- item base
    def buscar_item(self, titulo, marca, cliente):
        """
        Resuelve el item base. Devuelve (referencia, motivo, ignorados).
        referencia=None cuando no hay coincidencia exacta -> revision manual.
        """
        # 1. Quitar del titulo las palabras que provienen de Marca y CLIENTE
        ruido = set(norm(marca).split()) | set(norm(cliente).split())
        tokens = [t for t in canon(titulo).split() if t not in ruido]
        if not tokens:
            return None, "titulo vacio tras quitar marca/cliente", []

        # 2. Descartar palabras que no existen en ningun item base (campanas, textos
        #    comerciales). Los numeros nunca se descartan: son el tamano.
        limpios, ignorados = [], []
        for tok in tokens:
            if tok.isdigit() or tok in self.vocabulario:
                limpios.append(tok)
            else:
                ignorados.append(tok)
        if not limpios:
            return None, "ninguna palabra del titulo existe en el catalogo", ignorados
        # La familia (primera palabra) debe sobrevivir: si se descarto, no sabemos que producto es
        if limpios[0] != tokens[0]:
            return None, "familia desconocida: " + tokens[0], ignorados

        clave, _ = clave_item(" ".join(limpios))
        refs = self.por_clave.get(clave, [])
        if not refs:
            return None, "sin item base con esa combinacion familia/linea/tamano", ignorados
        if len(refs) == 1:
            return refs[0], "ok", ignorados

        # 3. Desempate de descripciones colisionantes (p.ej. "VASO 7 OZ" vs "VASO 7 oz"):
        #    se prefiere el prefijo KPT y, entre ellos, el de mas SKUs creados.
        elegido = sorted(refs, key=lambda r: (not r.startswith("KPT"), -self.skus_por_ref[r]))[0]
        return elegido, "desempate entre " + ", ".join(refs), ignorados

    # ------------------------------------------------------------ duplicados
    def sku_existente(self, referencia, marca, calibre_id):
        return self.existentes.get((referencia, norm(marca), calibre_id))


# Coherencia entre "Tipo de Material" del Excel y la linea del item base.
# Solo "Bio Natura" es bloqueante: es una linea distinta de producto, no un acabado.
def revisar_material(material, referencia, catalogo):
    if not referencia:
        return None
    clave, _ = clave_item(catalogo.desc_por_ref[referencia])
    linea = clave[1]
    mat = norm(material)
    if mat == "BIO NATURA" and "LDP" not in linea:
        return "material Bio Natura pero el item base no es LIBRE DE PLASTICO"
    if mat in ("P1", "P2") and "LDP" in linea:
        return "material P1/P2 pero el item base es LIBRE DE PLASTICO"
    return None
