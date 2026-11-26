# -*- coding: utf-8 -*-
"""Extracción de atributos (modelo, capacidad, color) desde descripciones de iPhone.

Se usa tanto para el maestro interno como para los títulos publicados por cada tienda,
de modo que ambos lados del emparejamiento produzcan la misma clave.
"""
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

RUTA_COLORES = Path(__file__).resolve().parents[2] / "config" / "colores.yaml"


@lru_cache(maxsize=1)
def _colores():
    with open(RUTA_COLORES, encoding="utf-8") as f:
        return yaml.safe_load(f)


def sin_tildes(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c))


def limpiar_descripcion(texto) -> str:
    """Colapsa espacios y elimina comillas/espacios de relleno del maestro."""
    if texto is None:
        return ""
    return re.sub(r"\s+", " ", str(texto)).strip().strip('"').strip()


# Modelo: número (4-18) o nombre (SE, X, XR, XS, Air, Duo) seguido de la variante.
_RE_MODELO = re.compile(
    r"iphone\s*(?P<gen>\d{1,2}|se|xr|xs|x|air|duo)(?P<suf>e|s|c)?"
    r"(?P<resto>.*)",
    re.IGNORECASE,
)
_RE_CAPACIDAD = re.compile(r"(\d{1,4})\s*(gb|tb)", re.IGNORECASE)
_RE_CAPACIDAD_SIN_UNIDAD = re.compile(r"(?<!\d)(64|128|256|512)(?!\d)")


def _variante(resto: str, gen: str) -> str:
    r = resto.lower().replace(" ", "")
    if gen == "xs" and r.startswith("max"):
        return "Max"
    if "promax" in r[:8]:
        return "Pro Max"
    if r.startswith("pro"):
        return "Pro"
    if r.startswith("plus") or r.startswith("+"):
        return "Plus"
    if r.startswith("mini"):
        return "mini"
    return ""


def modelo(texto: str) -> str | None:
    """'iPhone 17 Pro Max', 'iPhone 16e', 'iPhone SE', 'iPhone Air'... o None."""
    t = sin_tildes(limpiar_descripcion(texto))
    m = _RE_MODELO.search(t)
    if not m:
        return None
    gen = m.group("gen").lower()
    suf = (m.group("suf") or "").lower()
    nombre_gen = {"se": "SE", "xr": "XR", "xs": "XS", "x": "X", "air": "Air", "duo": "Duo"}.get(gen, gen)
    base = f"iPhone {nombre_gen}{suf.upper() if suf in ('s', 'c') else suf}"
    var = _variante(m.group("resto"), gen)
    return f"{base} {var}".strip()


def capacidad_gb(texto: str) -> int | None:
    t = limpiar_descripcion(texto)
    # Se descartan cifras de RAM ("8GB Ram/256GB"): se toma la mayor capacidad encontrada.
    valores = [int(n) * (1024 if u.lower() == "tb" else 1) for n, u in _RE_CAPACIDAD.findall(t)]
    if not valores:
        valores = [int(n) for n in _RE_CAPACIDAD_SIN_UNIDAD.findall(t)]
    return max(valores) if valores else None


def color(texto: str) -> str | None:
    t = limpiar_descripcion(texto)
    cfg = _colores()
    # 1) Abreviatura después de la barra invertida: "iPhone 15 128GB \Az"
    m = re.search(r"\\\s*([A-Za-z]+)", t)
    if m:
        cod = re.sub(r"(?i)demo$", "", m.group(1))
        if cod in cfg["abreviaturas"]:
            return cfg["abreviaturas"][cod]
    # 2) (PRODUCT)RED / RED
    if re.search(r"\bred\b|product\W*red", t, re.IGNORECASE):
        return "rojo"
    # 3) Palabra completa en español/inglés
    bajo = sin_tildes(t.lower())
    for palabra, valor in cfg["palabras"].items():
        if re.search(rf"{palabra}", bajo):
            return valor
    # 4) Abreviatura suelta al final: "iPhone 17 Pro 256GB Az (Demo)"
    sin_demo = re.sub(r"\(?\s*demo\s*\)?", "", t, flags=re.IGNORECASE).strip()
    ultimo = re.split(r"[\s\d]+", sin_demo)[-1] if sin_demo else ""
    ultimo = re.sub(r"(?i)^gb", "", ultimo)
    return cfg["abreviaturas"].get(ultimo)


def es_demo(texto: str) -> bool:
    return bool(re.search(r"demo", str(texto), re.IGNORECASE))


def es_reacondicionado(texto: str) -> bool:
    return bool(re.search(r"refurb|refu\b|reacond|usado|exhibici|open\s*box", sin_tildes(str(texto)), re.IGNORECASE))


def clave_atributos(mod: str | None, cap: int | None, col: str | None) -> str | None:
    """Clave de emparejamiento alternativo cuando la tienda no publica el EAN."""
    if not isinstance(mod, str) or not cap:
        return None
    return f"{mod.lower()}|{cap}|{col if isinstance(col, str) else '?'}"
