# -*- coding: utf-8 -*-
"""Grupo Éxito: listado renderizado con Playwright y ficha leída de __NEXT_DATA__ (sin navegador).

robots.txt de Éxito prohíbe /api/, /s?, facetas y ordenamientos, y permite /*?page=. El
navegador solo abre páginas del listado de categoría; las fichas llegan renderizadas desde el
servidor y se descargan con el mismo cliente HTTP que los demás sitios.
"""
import json
import logging
import re
from urllib.parse import urljoin

from src.extraccion.modelos import EstadoExtraccion, RegistroCaptura
from src.extraccion.sitios.base import Contexto, Objetivo, a_entero, registro

log = logging.getLogger(__name__)

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def enlaces_de_listado(html: str, base: str) -> list[str]:
    """URLs de fichas (`.../p`) que aparecen en el HTML renderizado de una página del listado."""
    vistos, salida = set(), []
    for href in re.findall(r'href="(/[^"?#]+/p)"', html):
        u = urljoin(base, href)
        if u not in vistos:
            vistos.add(u)
            salida.append(u)
    return salida


async def descubrir(base: str, listados: list[str], parametro: str, max_paginas: int, user_agent: str,
                    pausa: float, permite, guardar) -> tuple[list[Objetivo], int]:
    """Recorre ?page=1..N de cada listado hasta que una página no aporte fichas nuevas.

    Se recorren el listado general y las páginas por marca: el orden del listado cambia entre
    páginas (no se puede fijar porque robots.txt prohíbe `sort=`) y algunas fichas solo
    aparecen en una de las dos vías. `permite(url)` valida robots.txt y `guardar(clave, html)`
    deja cada página en Bronze.
    """
    from playwright.async_api import async_playwright

    urls: list[str] = []
    vistos: set[str] = set()
    paginas = 0
    async with async_playwright() as p:
        navegador = await p.chromium.launch()
        pagina = await navegador.new_page(
            # Navegador estándar más la identificación del proyecto.
            user_agent=f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                       f"Chrome/{navegador.version} Safari/537.36 {user_agent}",
            viewport={"width": 1366, "height": 900},
        )
        # El navegador no descarga imágenes, fuentes ni videos: menos carga para el sitio.
        await pagina.route(re.compile(r"\.(png|jpe?g|webp|gif|svg|woff2?|mp4)(\?|$)"), lambda r: r.abort())
        for listado in listados:
            sin_novedad = 0
            nombre = listado.rstrip("/").rsplit("/", 1)[-1]
            for n in range(1, max_paginas + 1):
                url = base + listado + ("" if n == 1 else f"?{parametro}={n}")
                if not permite(url):
                    log.warning("robots.txt prohíbe %s", url)
                    break
                try:
                    await pagina.goto(url, wait_until="domcontentloaded", timeout=60000)
                    await pagina.wait_for_selector("a[href$='/p']", timeout=20000)
                except Exception:
                    log.info("%s: página %d sin productos", nombre, n)
                    break
                await pagina.wait_for_timeout(1500)
                html = await pagina.content()
                guardar(f"listado_{nombre}_p{n}", html)
                paginas += 1
                nuevos = [u for u in enlaces_de_listado(html, base) if u not in vistos]
                vistos.update(nuevos)
                urls += nuevos
                sin_novedad = sin_novedad + 1 if not nuevos else 0
                if sin_novedad >= 2:
                    break
                await pagina.wait_for_timeout(int(pausa * 1000))
            log.info("%s: %d fichas acumuladas", nombre, len(urls))
        await navegador.close()
    return [Objetivo(clave=u, url=u) for u in urls], paginas


def parsear_ficha(html: str, url: str, ctx: Contexto, ruta_bronze: str | None) -> RegistroCaptura:
    m = _NEXT_DATA.search(html)
    if not m:
        return registro(ctx, url, EstadoExtraccion.ERROR_PARSEO, ruta_bronze, mensaje="Sin __NEXT_DATA__")
    try:
        datos = (json.loads(m.group(1)).get("props") or {}).get("pageProps", {}).get("data") or {}
    except json.JSONDecodeError as e:
        return registro(ctx, url, EstadoExtraccion.ERROR_PARSEO, ruta_bronze, mensaje=str(e)[:200])
    producto = datos.get("product")
    sku_data = datos.get("skuData") or {}
    if not producto:
        return registro(ctx, url, EstadoExtraccion.NO_ENCONTRADO, ruta_bronze, mensaje="Ficha sin producto")

    vendedores = producto.get("sellers") or []
    propio = next((v for v in vendedores if str(v.get("sellerId")) == ctx.vendedor_propio
                   and (v.get("commertialOffer") or {}).get("Price")), None)
    vendedor = propio or next((v for v in vendedores if v.get("sellerDefault")), None) \
        or (vendedores[0] if vendedores else {})
    oferta = vendedor.get("commertialOffer") or {}
    precio = a_entero(oferta.get("Price"))
    stock = oferta.get("AvailableQuantity")
    disponible = bool(precio) and (stock or 0) > 0
    lista = a_entero(oferta.get("ListPrice")) or a_entero(oferta.get("PriceWithoutDiscount"))

    referencia = None
    for prop in producto.get("properties") or []:
        if (prop.get("name") or "").lower() == "referencia" and prop.get("values"):
            referencia = str(prop["values"][0]).strip() or None
    slug = producto.get("slug")
    return registro(
        ctx, urljoin(url, f"/{slug}/p") if slug else url,
        EstadoExtraccion.OK if disponible else EstadoExtraccion.SIN_STOCK, ruta_bronze,
        sku_tienda=str(producto.get("sku") or sku_data.get("Id") or ""),
        ean_publicado=(sku_data.get("AlternateIds") or {}).get("Ean") or None,
        # product.name es el nombre del SKU, que en el marketplace a veces es solo el EAN.
        titulo=sku_data.get("ProductName") or (producto.get("isVariantOf") or {}).get("name")
        or producto.get("name"),
        marca=(producto.get("brand") or {}).get("name") or sku_data.get("BrandName"),
        referencia=referencia,
        vendedor=vendedor.get("sellerName"), es_vendedor_propio=propio is not None,
        precio_venta=precio or None,
        precio_lista=lista if lista and precio and lista > precio else None,
        disponible=disponible, stock=stock,
    )
