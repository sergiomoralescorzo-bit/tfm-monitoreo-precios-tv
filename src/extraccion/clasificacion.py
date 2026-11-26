# -*- coding: utf-8 -*-
"""Exclusiones previas al emparejamiento (Etapa 1, sección 6).

No se borra nada: cada registro queda marcado con `en_alcance` y, si no lo está, con el motivo.
La capa Silver filtra con esas marcas.
"""
import re

from src.catalogo import atributos_tv
from src.extraccion.modelos import EstadoExtraccion, RegistroCaptura

_ACCESORIO = re.compile(
    r"\b(soporte|base para|mueble|rack|control remoto|antena|cable|protector|forro|"
    r"tv ?box|stick|chromecast|fire ?tv|decodificador|convertidor|proyector|monitor|"
    r"parlante|barra de sonido|teatro en casa|limpiador|kit de limpieza|garant[ií]a|"
    r"instalaci[oó]n|servicio)\b",
    re.IGNORECASE,
)
_ES_TELEVISOR = re.compile(r"^\s*(tv|televisor|televisión|smart\s*tv)\b", re.IGNORECASE)
_TECNOLOGIA_DESCONTINUADA = re.compile(r"\b(crt|plasma|dlp)\b|\blcd\b(?!.*\bled\b)", re.IGNORECASE)


def es_accesorio(titulo: str) -> bool:
    """Accesorio o producto que no es un televisor ("Soporte para TV", "TV Box", "Monitor...")."""
    t = atributos_tv.sin_tildes(titulo or "")
    if _ES_TELEVISOR.search(t) and not re.search(r"^\s*tv ?box", t, re.IGNORECASE):
        return False
    return bool(_ACCESORIO.search(t)) or not re.search(r"\b(tv|televisor|smart\s*tv)\b", t, re.IGNORECASE)


def clasificar(r: RegistroCaptura) -> RegistroCaptura:
    if r.estado_extraccion not in (EstadoExtraccion.OK, EstadoExtraccion.SIN_STOCK):
        motivo = "SIN_DATOS"
    elif not r.titulo:
        motivo = "SIN_TITULO"
    elif atributos_tv.es_combo(r.titulo):
        motivo = "COMBO"
    elif es_accesorio(r.titulo):
        motivo = "NO_ES_TELEVISOR"
    elif atributos_tv.es_no_nuevo(r.titulo):
        motivo = "NO_NUEVO"
    elif _TECNOLOGIA_DESCONTINUADA.search(r.titulo):
        motivo = "TECNOLOGIA_DESCONTINUADA"
    elif not r.es_vendedor_propio:
        motivo = "VENDEDOR_EXTERNO"
    elif not r.precio_venta:
        motivo = "PRECIO_CERO"
    else:
        motivo = None
    r.en_alcance = motivo is None
    r.motivo_exclusion = motivo
    return r
