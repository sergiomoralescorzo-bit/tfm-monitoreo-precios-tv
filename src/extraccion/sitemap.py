# -*- coding: utf-8 -*-
"""Lectura de sitemaps XML (índices y listas de URL)."""
import re

from .cliente import ClienteSitio

_LOC = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.S)


def locs(xml: str) -> list[str]:
    return [u.replace("&amp;", "&") for u in _LOC.findall(xml)]


async def urls_producto(cliente: ClienteSitio, ruta: str, patron_url: str,
                        marca_hijos: str = "/product-") -> tuple[list[str], int]:
    """Devuelve las URL que cumplen `patron_url` y el número de archivos de sitemap leídos.

    Si `ruta` es un índice, solo se abren los sitemaps hijos cuyo nombre contiene `marca_hijos`.
    """
    regex = re.compile(patron_url)
    r = await cliente.get(ruta)
    encontrados = locs(r.texto)
    leidos = 1
    if "<sitemapindex" in r.texto:
        urls: list[str] = []
        for hijo in encontrados:
            if marca_hijos in hijo:
                urls += locs((await cliente.get(hijo)).texto)
                leidos += 1
        encontrados = urls
    vistos, salida = set(), []
    for u in encontrados:
        if regex.search(u) and u not in vistos:
            vistos.add(u)
            salida.append(u)
    return salida, leidos
