# -*- coding: utf-8 -*-
"""Alkosto y Ktronix (SAP Commerce): ficha HTML con microdatos schema.org."""
import re

from bs4 import BeautifulSoup

from src.extraccion.modelos import EstadoExtraccion, RegistroCaptura
from src.extraccion.sitios.base import Contexto, Objetivo, a_entero, registro

_EAN_URL = re.compile(r"/p/(\d{8,14})$")


def objetivos_desde_urls(urls: list[str]) -> list[Objetivo]:
    salida = []
    for u in urls:
        m = _EAN_URL.search(u)
        if m:
            salida.append(Objetivo(clave=m.group(1), url=u))
    return salida


def _meta(nodo, prop: str) -> str | None:
    if nodo is None:
        return None
    t = nodo.find(attrs={"itemprop": prop})
    if t is None:
        return None
    return t.get("content") or t.get("href") or t.get_text(" ", strip=True) or None


def _precio_analitica(html: str, sku: str | None) -> int | None:
    """Precio de venta exacto del objeto de analítica. Los microdatos (`itemprop="price"`) lo publican en
    notación científica desde 10 millones (`3.99999E+7`), con solo 6 cifras significativas."""
    if not sku:
        return None
    m = re.search(r"id:\s*'%s',\s*price:\s*'(\d+)'" % re.escape(sku), html)
    return int(m.group(1)) if m else None


def _precio_anterior(html: str, sku: str | None) -> int | None:
    """Precio antes del descuento. Está en el objeto de analítica de la ficha (`previousPrice`)."""
    if sku:
        m = re.search(r"id:\s*'%s',\s*price:\s*'\d+',\s*previousPrice\s*:\s*'(\d+)'" % re.escape(sku), html)
        if m:
            return int(m.group(1))
    m = re.search(r'baseprice_cop_string:\s*"([\d.]+)"', html)
    return a_entero(m.group(1)) if m else None


def parsear_ficha(html: str, url: str, ctx: Contexto, ruta_bronze: str | None) -> RegistroCaptura:
    s = BeautifulSoup(html, "lxml")
    producto = s.find(attrs={"itemtype": re.compile(r"schema.org/Product$")})
    oferta = s.find(attrs={"itemprop": "offers"})
    titulo_tag = s.find("h1", attrs={"itemprop": "name"}) or s.find("h1")
    precio = a_entero(_meta(oferta, "price"))
    if oferta is None or precio is None or titulo_tag is None:
        # Las fichas retiradas siguen en el sitemap y redirigen a la categoría o al inicio.
        mensaje = ("Redirige a una página que no es ficha (producto retirado)" if "/p/" not in url
                   else "La página no tiene microdatos de producto/oferta")
        return registro(ctx, url, EstadoExtraccion.NO_ENCONTRADO, ruta_bronze, mensaje=mensaje)
    sku = _meta(s, "sku")
    precio = _precio_analitica(html, sku) or precio
    marca_nodo = s.find(attrs={"itemprop": "brand"})
    disponibilidad = _meta(oferta, "availability") or ""
    disponible = disponibilidad.endswith("InStock")
    vendedor = _meta(oferta.find(attrs={"itemprop": "seller"}), "name") if oferta else None
    lista = _precio_anterior(html, sku)
    return registro(
        ctx, url, EstadoExtraccion.OK if disponible else EstadoExtraccion.SIN_STOCK, ruta_bronze,
        sku_tienda=sku, ean_publicado=sku, titulo=titulo_tag.get_text(" ", strip=True),
        marca=_meta(marca_nodo, "name") if producto or marca_nodo else None,
        vendedor=vendedor, es_vendedor_propio=(vendedor or "").strip().lower() == ctx.vendedor_propio.lower(),
        precio_venta=precio, precio_lista=lista if lista and lista > precio else None,
        disponible=disponible,
    )
