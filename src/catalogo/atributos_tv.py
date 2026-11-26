# -*- coding: utf-8 -*-
"""Extracción de atributos de televisores: marca, pulgadas, referencia, tecnología, resolución.

Se aplica igual a las descripciones del maestro ("TV LG 55\\ 55QNED80SRA 4KUHD") y a los
títulos de las tiendas ('Televisor LG 55" Pulgadas QNED 55QNED80SRA'), para que ambos
lados produzcan la misma clave de emparejamiento alternativo (marca + referencia).
"""
import re
import unicodedata

MARCAS = {
    "SAMSUNG": ["samsung", "sams"],
    "LG": ["lg"],
    "SONY": ["sony"],
    "TCL": ["tcl"],
    "HISENSE": ["hisense"],
    "CHALLENGER": ["challenger", "challeng", "challen", "chall"],
    "KALLEY": ["kalley"],
    "HYUNDAI": ["hyundai", "hyunda"],
    "PANASONIC": ["panasonic", "panaso"],
    "PHILIPS": ["philips", "phil"],
    "SHARP": ["sharp"],
    "AOC": ["aoc"],
    "CAIXUN": ["caixun"],
    "XIAOMI": ["xiaomi"],
    "OLIMPO": ["olimpo"],
    # 21-nov-2026: marcas propias o de distribuidor que venden las cadenas y no están en el maestro.
    "FINLANDEK": ["finlandek"],
    "COMPAQ": ["compaq"],
}

# Tokens que describen características y no son referencia (se comparan sin guiones).
_NO_REFERENCIA = re.compile(
    r"(qd)?(mini)?(ld|led|qled|oled|qned)?(\d?k)?(uhd|fhd|hd)?(in|int)?(t2)?(\d?k)?(smart)?"
    r"|\d+(hz|mm|pulg|pulgadas)?|\d+([.,]\d+)?cm[a-z]*|smart|google|roku|webos|vidaa|tizen|bt|gtv|usb|hdmi",
    re.IGNORECASE,
)
# Prefijos de familia que algunas tiendas anteponen a la referencia (UN55..., KDL-32...).
_PREFIJOS = ("UN", "XBR", "KDL", "KD", "QN")
# Sufijos de características pegados al final de la referencia ("47LN5400FHD", "49ES630FHDInt").
_SUFIJO_CARACTERISTICAS = re.compile(r"(3D)?(\dK)?(UHD|FHD|HD)?(IN|INT)?(T2)?$")


def sin_tildes(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c))


def limpiar_descripcion(texto) -> str:
    if texto is None or (isinstance(texto, float) and texto != texto):
        return ""
    return re.sub(r"\s+", " ", str(texto)).strip().strip('"').strip()


def marca(texto: str, marca_maestro: str | None = None) -> str | None:
    if isinstance(marca_maestro, str):
        m = marca_maestro.upper().strip()
        for nombre in MARCAS:
            if m.startswith(nombre):
                return nombre
    bajo = sin_tildes(limpiar_descripcion(texto).lower())
    for nombre, alias in MARCAS.items():
        for a in alias:
            if re.search(rf"(?<![a-z]){a}", bajo):
                return nombre
    return None


def pulgadas(texto: str) -> int | None:
    t = limpiar_descripcion(texto)
    for patron in (
        r"(\d{2,3})(?:[.,]\d)?\s*(?:\\|\"|”|''|pulgadas|pulg\b|inch(?:es)?\b|in\b)",   # 55\  55"  55 Pulgadas
        r"^(?:tv|kv|televisor)\s*(?:led\s*)?(\d{2,3})(?!\d)",           # Tv40 101cm
    ):
        m = re.search(patron, t, re.IGNORECASE)
        if m and 15 <= int(m.group(1)) <= 120:
            return int(m.group(1))
    return None


def pulgadas_desde_referencia(ref: str | None) -> int | None:
    """'UN50CU8200KXZL' -> 50; 'QN77S90C' -> 77. Solo si la referencia empieza así."""
    if not isinstance(ref, str):
        return None
    r = re.sub(r"[^A-Za-z0-9]", "", ref).upper()
    for p in _PREFIJOS:
        if r.startswith(p) and r[len(p):len(p) + 2].isdigit():
            r = r[len(p):]
            break
    m = re.match(r"^(\d{2})[A-Z]", r)
    return int(m.group(1)) if m and 19 <= int(m.group(1)) <= 98 else None


def _es_caracteristica(tok: str) -> bool:
    return bool(_NO_REFERENCIA.fullmatch(re.sub(r"[^A-Za-z0-9.,]", "", tok)))


def referencia(texto: str) -> str | None:
    """Referencia del fabricante tal como aparece en el texto.

    Se prefiere el token alfanumérico más largo; si no hay, un número de 3 a 5 cifras
    que no sean las pulgadas (Hyundai usa referencias como '5802').
    """
    t = limpiar_descripcion(texto).replace("\\", " ")
    pulg = pulgadas(texto)
    tokens = [tok.strip(".-\"'") for tok in re.split(r"[\s|/,()+]+", t)]
    alfanum = [tok for tok in tokens
               if len(tok) >= 3 and re.search(r"\d", tok) and re.search(r"[A-Za-z]", tok)
               and not _es_caracteristica(tok)]
    if alfanum:
        return max(alfanum, key=len)
    numeros = [tok for tok in tokens if re.fullmatch(r"\d{3,5}", tok) and tok != str(pulg)]
    return numeros[-1] if numeros else None


def referencia_normalizada(ref: str | None, pulg: int | None = None, marca_: str | None = None) -> str | None:
    """Mayúsculas, solo alfanuméricos, sin marca, prefijo de familia, pulgadas ni sufijos.

    '75TG4770' y 'TG4770' -> 'TG4770';  'UN55AU7000' y '55AU7000' -> 'AU7000';
    'LG43LF510TFHD' -> 'LF510T'.
    """
    if not isinstance(ref, str) or not ref:
        return None
    r = re.sub(r"[^A-Za-z0-9]", "", ref).upper()
    if isinstance(marca_, str):
        for alias in sorted(MARCAS.get(marca_, []), key=len, reverse=True):
            if r.startswith(alias.upper()) and r[len(alias):len(alias) + 1].isdigit():
                r = r[len(alias):]
                break
    for p in _PREFIJOS:
        if r.startswith(p) and len(r) > len(p) + 4 and r[len(p)].isdigit():
            r = r[len(p):]
            break
    if pulg and r.startswith(str(pulg)) and len(r) > len(str(pulg)) + 2:
        r = r[len(str(pulg)):]
    elif pulg is None and re.match(r"^\d{2}[A-Z]", r):
        r = r[2:]
    sin_sufijo = _SUFIJO_CARACTERISTICAS.sub("", r)
    if len(sin_sufijo) >= 3:
        r = sin_sufijo
    return r or None


def tecnologia(texto: str) -> str | None:
    t = sin_tildes(limpiar_descripcion(texto).lower())
    for patron, valor in (
        (r"oled", "OLED"), (r"qned", "QNED"), (r"mini\s*-?\s*le?d|miniled", "Mini LED"),
        (r"nano", "NanoCell"), (r"qled", "QLED"), (r"led", "LED"),
        (r"crystal", "LED"),   # Samsung Crystal UHD es un panel LED
    ):
        if re.search(patron, t):
            return valor
    return None


def resolucion(texto: str) -> str | None:
    t = limpiar_descripcion(texto).upper()
    if re.search(r"8K", t):
        return "8K"
    if re.search(r"4K|UHD", t):
        return "4K"
    if re.search(r"FHD|FULL\s*HD", t):
        return "FHD"
    if re.search(r"\bHD", t):
        return "HD"
    return None


def es_combo(texto: str) -> bool:
    """TV vendido con otro producto (barra de sonido, control...): precio no comparable."""
    return "+" in str(texto) or bool(re.search(r"\bcombo\b", str(texto), re.IGNORECASE))


def es_no_nuevo(texto: str) -> bool:
    return bool(re.search(r"demo|exhibici|reacond|refurb|usado|open\s*box|segunda",
                          sin_tildes(str(texto)), re.IGNORECASE))


def clave_referencia(marca_: str | None, pulg: int | None, ref_norm: str | None) -> str | None:
    """Clave de emparejamiento alternativo: marca + pulgadas + referencia normalizada.

    Las pulgadas son necesarias porque los fabricantes repiten la referencia de la serie
    en todos los tamaños (LG 43UT7300 y 65UT7300 -> 'UT7300').
    """
    if not isinstance(marca_, str) or not isinstance(ref_norm, str) or not pulg:
        return None
    return f"{marca_}|{pulg}|{ref_norm}"
