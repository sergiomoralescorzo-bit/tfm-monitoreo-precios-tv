# -*- coding: utf-8 -*-
"""Piezas comunes a los extractores: contexto de la corrida, objetivos y construcción de registros."""
import re
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from src.catalogo import atributos_tv, gtin
from src.extraccion.modelos import EstadoExtraccion, RegistroCaptura

ZONA_COL = ZoneInfo("America/Bogota")


@dataclass
class Contexto:
    """Datos fijos de una corrida en un sitio."""
    id_ejecucion: str
    clave_sitio: str
    cadena: str
    metodo: str
    vendedor_propio: str


@dataclass
class Objetivo:
    """Ficha a capturar: `clave` es el EAN (SAP), el slug (VTEX) o la URL (Éxito)."""
    clave: str
    url: str
    extra: dict = field(default_factory=dict)


def ahora() -> tuple[datetime, datetime]:
    utc = datetime.now(ZoneInfo("UTC"))
    return utc, utc.astimezone(ZONA_COL)


def a_entero(valor) -> int | None:
    """'1549900.0', 1549900, '$1.549.900', '1.19999E+7' -> entero. Devuelve None si no hay número."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return int(round(valor))
    texto = str(valor).strip()
    if re.fullmatch(r"\d+(\.\d+)?([eE][+-]?\d+)?", texto):   # incluye notación científica (Alkosto ≥ 10 M)
        return int(round(float(texto)))
    digitos = re.sub(r"[^\d]", "", texto.split(",")[0])
    return int(digitos) if digitos else None


def registro(ctx: Contexto, url: str, estado: EstadoExtraccion, ruta_bronze: str | None = None,
             **campos) -> RegistroCaptura:
    """Construye el registro y completa marca, pulgadas, referencia y GTIN-14 desde el título."""
    utc, col = ahora()
    titulo = campos.get("titulo")
    if titulo:
        titulo = atributos_tv.limpiar_descripcion(titulo)
        campos["titulo"] = titulo
        campos["marca"] = atributos_tv.marca(titulo, campos.get("marca"))
        campos.setdefault("pulgadas", atributos_tv.pulgadas(titulo))
        if not campos.get("referencia"):
            campos["referencia"] = atributos_tv.referencia(titulo)
        if campos.get("pulgadas") is None:
            campos["pulgadas"] = atributos_tv.pulgadas_desde_referencia(campos.get("referencia"))
    ean = campos.get("ean_publicado")
    if ean:
        campos["gtin14"] = gtin.a_gtin14(ean)
    return RegistroCaptura(
        id_ejecucion=ctx.id_ejecucion, fecha_captura_utc=utc, fecha_captura_col=col,
        cadena=ctx.cadena, sitio=ctx.clave_sitio, url=url, estado_extraccion=estado,
        metodo=ctx.metodo, ruta_bronze=ruta_bronze, **campos,
    )
