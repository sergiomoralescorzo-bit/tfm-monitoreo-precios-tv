# -*- coding: utf-8 -*-
"""Cliente de Éxito con Scrapling, con una sesión falsa (sin navegador ni red)."""
import asyncio
import json
import logging

import pytest

from src.extraccion import scrapling_exito as se
from src.extraccion.cliente import DesafioVerificacion, ProhibidoPorRobots
from src.extraccion.ejecutar import cargar_config, metodo, usa_scrapling
from src.extraccion.robots import ReglasRobots

FICHA = ('<html><head><title>TV</title></head><body><h1>TV</h1><script id="__NEXT_DATA__" type="application/json">'
         + json.dumps({"props": {"pageProps": {"data": {"product": {"sku": "1"}}}}}) + "</script></body></html>")
DESAFIO = '<html><head><title>Just a moment...</title></head><body><div id="cf-chl-widget"></div></body></html>'
LISTADO = '<html><body><a href="/tv-a/p">a</a><a href="/tv-b/p">b</a></body></html>'


class _Sel:
    def __init__(self, valor):
        self.valor = valor

    def get(self):
        return self.valor


class _Resp:
    def __init__(self, url, html, status=200, body=None, titulo=""):
        self.url, self.html_content, self.status = url, html, status
        self.body = body if body is not None else html.encode()
        self.headers = {}
        self._titulo = titulo

    def css(self, _):
        return _Sel(self._titulo)


class _Sesion:
    def __init__(self, paginas):
        logging.getLogger("scrapling").setLevel(logging.INFO)   # Scrapling lo deja así al importarse
        self.paginas, self.pedidas = paginas, []

    async def fetch(self, url, **kw):
        self.pedidas.append((url, kw))
        logging.getLogger("scrapling").info("No Cloudflare challenge found.")
        return self.paginas[url]


class _Http:
    base = "https://www.exito.com"

    def __init__(self, robots=""):
        self.robots = ReglasRobots(robots, "*")

    def permite(self, url):
        return self.robots.permite(url)


def _cliente(paginas, robots=""):
    return se.ClienteScrapling(_Http(robots), pausa=0, sesion=_Sesion(paginas))


async def _get(cliente, url, **kw):
    async with cliente:
        cliente._ultima = 0
        cliente.pausa = 0
        return await cliente.get(url, **kw)


def test_resumen_desafio():
    assert se.resumen_desafio([]) == "sin aviso de Cloudflare"
    assert se.resumen_desafio(["No Cloudflare challenge found."]) == "sin desafío de Cloudflare"
    assert se.resumen_desafio(["Cloudflare captcha is solved"]) == "desafío de Cloudflare resuelto por Scrapling"
    assert se.resumen_desafio(["Cloudflare page detected"]).startswith("Cloudflare: ")


def test_cuerpo_y_texto_xml_crudo_html_renderizado():
    xml = b'<?xml version="1.0"?><sitemapindex><sitemap><loc>https://x/a.xml</loc></sitemap></sitemapindex>'
    assert se.cuerpo_y_texto(xml, "<html>visor</html>") == (xml.decode(), xml)
    assert se.cuerpo_y_texto(b"<html>crudo</html>", "<html>dom</html>")[0] == "<html>dom</html>"


def test_get_ficha_devuelve_respuesta_y_nota():
    url = "https://www.exito.com/tv-a/p"
    c = _cliente({url: _Resp(url, FICHA, titulo="TV")})
    r = asyncio.run(_get(c, "/tv-a/p"))
    assert r.estado == 200 and "__NEXT_DATA__" in r.texto
    assert c._sesion.pedidas[0][1] == {"wait_selector": se.ESPERA_FICHA}
    assert c.nota.startswith("scrapling_stealth; scrapling ") and "sin desafío de Cloudflare" in c.nota


def test_get_desafio_sin_resolver_lanza_desafio():
    url = "https://www.exito.com/tv-a/p"
    c = _cliente({url: _Resp(url, DESAFIO, status=403, titulo="Just a moment...")})
    with pytest.raises(DesafioVerificacion):
        asyncio.run(_get(c, url))


def test_get_respeta_robots():
    c = _cliente({}, robots="User-agent: *\nDisallow: /api/\n")
    with pytest.raises(ProhibidoPorRobots):
        asyncio.run(_get(c, "/api/catalog_system/pub/products/search"))
    assert c._sesion.pedidas == []


def test_descubrir_recorre_paginas_hasta_que_no_hay_productos():
    base = "https://www.exito.com/tecnologia/televisores"
    vacio = "<html><body>sin productos</body></html>"
    c = _cliente({base: _Resp(base, LISTADO), base + "?page=2": _Resp(base, vacio)})
    guardados = []

    async def correr():
        async with c:
            c.pausa = 0
            return await se.descubrir(c, ["/tecnologia/televisores"], "page", 10, lambda k, h: guardados.append(k))
    objetivos, paginas = asyncio.run(correr())
    assert [o.url for o in objetivos] == ["https://www.exito.com/tv-a/p", "https://www.exito.com/tv-b/p"]
    assert paginas == 1 and guardados == ["listado_televisores_p1"]


def test_config_activa_scrapling_solo_en_exito():
    fuentes = cargar_config()["fuentes"]
    assert usa_scrapling(fuentes["exito"]) and metodo(fuentes["exito"]) == "scrapling_stealth"
    assert not any(usa_scrapling(f) for k, f in fuentes.items() if k != "exito")


def test_rotar_cambia_el_inicio_y_conserva_todo():
    from src.extraccion.ejecutar import rotar
    lista = list(range(531))
    inicios = {rotar(lista, d)[0] for d in range(740000, 740010)}
    assert len(inicios) == 10
    assert sorted(rotar(lista, 740001)) == lista
    assert rotar([], 1) == []


def test_presupuesto_configurado_solo_en_exito():
    fuentes = cargar_config()["fuentes"]
    assert fuentes["exito"]["presupuesto_minutos"] == 110
    assert not any(f.get("presupuesto_minutos") for k, f in fuentes.items() if k != "exito")


def test_sitemap_xml_no_es_desafio_aunque_el_dom_lo_parezca():
    url = "https://www.exito.com/sitemap/sitemap.xml"
    xml = b'<?xml version="1.0"?><sitemapindex><sitemap><loc>https://www.exito.com/sitemap/category-0.xml</loc></sitemap></sitemapindex>'
    c = _cliente({url: _Resp(url, DESAFIO, body=xml, titulo="Just a moment...")})
    r = asyncio.run(_get(c, url))
    assert "<sitemapindex" in r.texto and r.contenido == xml


def test_desafio_con_cuerpo_html_se_sigue_detectando():
    url = "https://www.exito.com/sitemap/sitemap.xml"
    c = _cliente({url: _Resp(url, DESAFIO, status=403, titulo="Just a moment...")})
    with pytest.raises(DesafioVerificacion):
        asyncio.run(_get(c, url))


class _SesionContada(_Sesion):
    abiertas = 0
    cerradas = 0

    async def __aenter__(self):
        _SesionContada.abiertas += 1
        return self

    async def __aexit__(self, *exc):
        _SesionContada.cerradas += 1


def test_recicla_la_sesion_cada_n_peticiones():
    _SesionContada.abiertas = _SesionContada.cerradas = 0
    paginas = {f"https://www.exito.com/tv-{i}/p": se_resp for i, se_resp in
               ((i, _Resp(f"https://www.exito.com/tv-{i}/p", FICHA, titulo="TV")) for i in range(5))}
    cliente = se.ClienteScrapling(_Http(), pausa=0, reciclar_cada=2, fabrica=lambda: _SesionContada(paginas))

    async def correr():
        async with cliente:
            for i in range(5):
                cliente._ultima = 0
                cliente.pausa = 0
                await cliente.get(f"https://www.exito.com/tv-{i}/p")

    asyncio.run(correr())
    assert cliente.peticiones == 5
    assert cliente.reciclajes == 2                 # antes de la 3.ª y de la 5.ª petición
    assert (_SesionContada.abiertas, _SesionContada.cerradas) == (3, 3)


def test_sesion_inyectada_no_se_recicla():
    paginas = {"https://www.exito.com/tv-a/p": _Resp("https://www.exito.com/tv-a/p", FICHA)}
    cliente = se.ClienteScrapling(_Http(), pausa=0, sesion=_Sesion(paginas), reciclar_cada=1)

    async def correr():
        async with cliente:
            for _ in range(3):
                cliente._ultima = 0
                cliente.pausa = 0
                await cliente.get("https://www.exito.com/tv-a/p")

    asyncio.run(correr())
    assert cliente.reciclajes == 0


def test_config_exito_recicla():
    assert cargar_config()["fuentes"]["exito"]["reciclar_cada"] > 0
