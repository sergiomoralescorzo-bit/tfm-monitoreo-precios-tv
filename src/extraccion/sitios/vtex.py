# -*- coding: utf-8 -*-
"""Jumbo y Olímpica (VTEX): API pública de catálogo consultada por ruta, sin parámetros."""
import json
import re

from src.catalogo import gtin
from src.extraccion.modelos import EstadoExtraccion, RegistroCaptura
from src.extraccion.sitios.base import Contexto, Objetivo, a_entero, registro

_SLUG = re.compile(r"\.com/(.+)/p$")


def objetivos_desde_urls(urls: list[str]) -> list[Objetivo]:
    salida = []
    for u in urls:
        m = _SLUG.search(u)
        if m:
            salida.append(Objetivo(clave=m.group(1), url=u))
    return salida


def _oferta(item: dict, vendedor_propio: str) -> tuple[dict | None, bool]:
    """Oferta del vendedor propio si tiene precio; si no, la del vendedor por defecto (marketplace)."""
    vendedores = item.get("sellers") or []
    for v in vendedores:
        if str(v.get("sellerId")) == vendedor_propio and (v.get("commertialOffer") or {}).get("Price"):
            return v, True
    for v in vendedores:
        if v.get("sellerDefault") and str(v.get("sellerId")) != vendedor_propio:
            return v, False
    return (vendedores[0], str(vendedores[0].get("sellerId")) == vendedor_propio) if vendedores else (None, False)


def _especificacion(producto: dict, nombre: str) -> str | None:
    valores = producto.get(nombre)
    if isinstance(valores, list) and valores:
        return str(valores[0]).strip() or None
    return None


def _ean(item: dict, producto: dict) -> str | None:
    """EAN del ítem; si falta, el de la especificación "EAN" o `productReference` (Olímpica).

    Se exige un GTIN de 12 a 14 dígitos válido: los códigos internos de 8 dígitos pueden
    pasar el dígito de control por casualidad (p. ej. 10004029).
    """
    for candidato in (item.get("ean"), _especificacion(producto, "EAN"), producto.get("productReference")):
        c = gtin.limpiar(candidato)
        if 12 <= len(c) <= 14 and gtin.es_valido(c):
            return c
    return None


def parsear_producto(texto: str, url: str, ctx: Contexto, ruta_bronze: str | None) -> list[RegistroCaptura]:
    """Un registro por SKU (item) del producto."""
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError as e:
        return [registro(ctx, url, EstadoExtraccion.ERROR_PARSEO, ruta_bronze, mensaje=str(e)[:200])]
    if not datos:
        return [registro(ctx, url, EstadoExtraccion.NO_ENCONTRADO, ruta_bronze,
                         mensaje="La API no devolvió el producto")]
    salida = []
    for producto in datos:
        url_ficha = producto.get("link") or url
        for item in producto.get("items") or []:
            vendedor, propio = _oferta(item, ctx.vendedor_propio)
            oferta = (vendedor or {}).get("commertialOffer") or {}
            precio = a_entero(oferta.get("Price"))
            stock = oferta.get("AvailableQuantity")
            disponible = bool(oferta.get("IsAvailable")) and bool(precio) and (stock or 0) > 0
            lista = a_entero(oferta.get("ListPrice")) or a_entero(oferta.get("PriceWithoutDiscount"))
            salida.append(registro(
                ctx, url_ficha, EstadoExtraccion.OK if disponible else EstadoExtraccion.SIN_STOCK, ruta_bronze,
                sku_tienda=str(item.get("itemId")), ean_publicado=_ean(item, producto),
                # nameComplete repite el nombre del producto y el del ítem; productName es el título visible.
                titulo=producto.get("productName") or item.get("nameComplete"),
                marca=producto.get("brand"), referencia=_especificacion(producto, "Modelo"),
                vendedor=(vendedor or {}).get("sellerName"), es_vendedor_propio=propio,
                precio_venta=precio or None,
                precio_lista=lista if lista and precio and lista > precio else None,
                disponible=disponible, stock=stock,
            ))
    return salida or [registro(ctx, url, EstadoExtraccion.ERROR_PARSEO, ruta_bronze, mensaje="Producto sin items")]
