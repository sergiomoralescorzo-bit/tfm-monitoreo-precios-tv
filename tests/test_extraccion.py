# -*- coding: utf-8 -*-
"""Pruebas de la Etapa 2 con respuestas reales guardadas el 13-oct-2026 (tests/fixtures).

No dependen de la web en vivo: si un sitio cambia su estructura, se guarda una respuesta
nueva y estas pruebas muestran qué campo dejó de extraerse.
"""
import asyncio
import gzip
from pathlib import Path

import httpx
import pytest

from src.extraccion import clasificacion
from src.extraccion.cliente import ClienteSitio, DesafioVerificacion, ProhibidoPorRobots, SitioBloqueado
from src.extraccion.modelos import EstadoExtraccion
from src.extraccion.robots import ReglasRobots
from src.extraccion.sitemap import locs
from src.extraccion.sitios import exito, sap_commerce, vtex
from src.extraccion.sitios.base import Contexto, a_entero

FIX = Path(__file__).parent / "fixtures"


def leer(nombre: str) -> str:
    with gzip.open(FIX / nombre, "rt", encoding="utf-8") as f:
        return f.read()


def ctx(sitio: str, vendedor: str, metodo: str = "http_html") -> Contexto:
    return Contexto("prueba", sitio, sitio, metodo, vendedor)


# --------------------------------------------------------------------------- robots.txt

ROBOTS_EXITO = """
User-agent: *
Allow: /
Disallow: /s?
Disallow: /*?*facets=
Disallow: /*?*sort=
Allow: /*?page=
Disallow: /api/
"""

ROBOTS_OLIMPICA = """
User-agent: *
Disallow: /*?orderFormId=
Allow: /*.css

User-agent: *
Disallow: /*&
Disallow: /*%

User-agent: Googlebot
Allow: /*
"""


def test_robots_exito():
    r = ReglasRobots(ROBOTS_EXITO, "TFM-MonitoreoPrecios/0.2")
    assert r.permite("https://www.exito.com/tecnologia/televisores")
    assert r.permite("https://www.exito.com/tecnologia/televisores?page=3")
    assert r.permite("https://www.exito.com/televisor-tcl-50-3234406/p")
    assert not r.permite("https://www.exito.com/api/catalog_system/pub/products/search")
    assert not r.permite("https://www.exito.com/tecnologia/televisores?page=2&facets=brand")
    assert not r.permite("https://www.exito.com/s?q=tv")


def test_robots_olimpica_combina_grupos_y_prohibe_ampersand():
    r = ReglasRobots(ROBOTS_OLIMPICA, "TFM-MonitoreoPrecios/0.2")
    assert r.permite("https://www.olimpica.com/api/catalog_system/pub/products/search/tv-x/p")
    assert r.permite("https://www.olimpica.com/api/catalog_system/pub/products/search?fq=alternateIds_Ean:123")
    assert not r.permite("https://www.olimpica.com/api/catalog_system/pub/products/search?ft=tv&_from=0&_to=49")
    assert not r.permite("https://www.olimpica.com/x?orderFormId=1")


def test_robots_alkosto_comodin_inicial_y_fin_de_ruta():
    r = ReglasRobots("User-agent: *\nAllow: /\nDisallow: *?q=\nDisallow: /cart$\nDisallow: /search/\n", "x")
    assert r.permite("https://www.alkosto.com/p/7705946479714")
    assert r.permite("https://www.alkosto.com/cart/items")
    assert not r.permite("https://www.alkosto.com/cart")
    assert not r.permite("https://www.alkosto.com/tv?q=lg")
    assert not r.permite("https://www.alkosto.com/search/?text=tv")


# --------------------------------------------------------------------------- utilidades

@pytest.mark.parametrize("entrada,esperado", [
    ("1549900.0", 1549900), (1549900, 1549900), (1599900.0, 1599900), ("$1.549.900", 1549900),
    ("1.19999E+7", 11999900), ("3.99999E+7", 39999900), ("", None), (None, None),
])
def test_a_entero(entrada, esperado):
    assert a_entero(entrada) == esperado


def test_sitemap_locs():
    xml = "<urlset><url><loc>https://a.com/tv-x/p/123</loc></url><url><loc> https://a.com/b?x=1&amp;y=2 </loc></url></urlset>"
    assert locs(xml) == ["https://a.com/tv-x/p/123", "https://a.com/b?x=1&y=2"]


def test_objetivos_desde_urls():
    sap = sap_commerce.objetivos_desde_urls(["https://www.alkosto.com/tv-kalley-55/p/7705946479714", "https://x.com/otro"])
    assert [(o.clave, o.url) for o in sap] == [("7705946479714", "https://www.alkosto.com/tv-kalley-55/p/7705946479714")]
    vt = vtex.objetivos_desde_urls(["https://www.olimpica.com/televisor-caixun-43-c43vafw/p"])
    assert vt[0].clave == "televisor-caixun-43-c43vafw"


# --------------------------------------------------------------------------- Alkosto / Ktronix

def test_alkosto_ficha_con_stock():
    r = sap_commerce.parsear_ficha(leer("alkosto_ficha_ok.html.gz"), "https://www.alkosto.com/x/p/7705946479714",
                                   ctx("alkosto", "Alkosto"), "bronze/x.gz")
    assert r.estado_extraccion == EstadoExtraccion.OK
    assert r.ean_publicado == "7705946479714" and r.gtin14 == "07705946479714"
    assert r.precio_venta == 1549900 and r.precio_lista == 3599900
    assert r.marca == "KALLEY" and r.pulgadas == 55 and r.referencia == "55GQ405"
    assert r.es_vendedor_propio and r.disponible and r.completo
    assert r.ruta_bronze == "bronze/x.gz"


def test_alkosto_precio_desde_10_millones():
    """Los microdatos dicen 3.99999E+7; antes se leía 3.999.997. Debe salir el precio exacto de la ficha."""
    r = sap_commerce.parsear_ficha(leer("alkosto_ficha_precio_alto.html.gz"),
                                   "https://www.alkosto.com/x/p/6921732899530", ctx("alkosto", "Alkosto"), None)
    assert r.precio_venta == 39999900 and r.precio_lista == 79999900


def test_alkosto_ficha_sin_stock():
    r = sap_commerce.parsear_ficha(leer("alkosto_ficha_sin_stock.html.gz"), "u", ctx("alkosto", "Alkosto"), None)
    assert r.estado_extraccion == EstadoExtraccion.SIN_STOCK
    assert r.disponible is False and r.precio_venta == 5599900 and r.pulgadas == 75


def test_alkosto_pagina_sin_producto():
    r = sap_commerce.parsear_ficha("<html><h1>Página no encontrada</h1></html>", "u", ctx("alkosto", "Alkosto"), None)
    assert r.estado_extraccion == EstadoExtraccion.NO_ENCONTRADO


# --------------------------------------------------------------------------- Jumbo / Olímpica

def test_jumbo_producto_propio():
    [r] = vtex.parsear_producto(leer("jumbo_producto.json.gz"), "u", ctx("jumbo", "1", "http_json"), None)
    assert r.estado_extraccion == EstadoExtraccion.OK
    assert r.ean_publicado == "8806097027584" and r.vendedor == "Cencosud - Colombia" and r.es_vendedor_propio
    assert r.precio_venta == 1699900 and r.precio_lista == 3599900 and r.stock == 72
    assert r.referencia == "UN55U8000FKXZL" and r.pulgadas == 55
    assert "Televisor Samsung 55" in r.titulo and r.titulo.count("Televisor") == 1


def test_jumbo_dos_items_separa_marketplace_y_propio():
    regs = vtex.parsear_producto(leer("jumbo_producto_dos_items.json.gz"), "u", ctx("jumbo", "1", "http_json"), None)
    assert len(regs) == 2
    externo, propio = sorted(regs, key=lambda r: r.es_vendedor_propio)
    assert externo.vendedor == "Merpes" and externo.precio_venta == 659900
    assert propio.vendedor == "Cencosud - Colombia" and propio.estado_extraccion == EstadoExtraccion.SIN_STOCK
    assert clasificacion.clasificar(externo).motivo_exclusion == "VENDEDOR_EXTERNO"


def test_olimpica_propio_y_marketplace():
    [p] = vtex.parsear_producto(leer("olimpica_propio.json.gz"), "u", ctx("olimpica", "1", "http_json"), None)
    assert p.vendedor == "Olimpica" and p.es_vendedor_propio and p.marca == "CAIXUN" and p.pulgadas == 43
    assert clasificacion.clasificar(p).en_alcance
    [m] = vtex.parsear_producto(leer("olimpica_marketplace.json.gz"), "u", ctx("olimpica", "1", "http_json"), None)
    assert not m.es_vendedor_propio and m.vendedor == "Grupo Electro M"
    assert m.referencia == "65UQ801C0SB"      # especificación "Modelo"
    assert m.ean_publicado is None            # productReference 10004029 no es un GTIN válido


def test_vtex_respuesta_vacia():
    [r] = vtex.parsear_producto("[]", "u", ctx("jumbo", "1", "http_json"), None)
    assert r.estado_extraccion == EstadoExtraccion.NO_ENCONTRADO


# --------------------------------------------------------------------------- Éxito

def test_exito_enlaces_de_listado():
    urls = exito.enlaces_de_listado(leer("exito_listado.html.gz"), "https://www.exito.com")
    assert len(urls) >= 10 and len(urls) == len(set(urls))
    assert all(u.startswith("https://www.exito.com/") and u.endswith("/p") for u in urls)


def test_exito_ficha_propia():
    r = exito.parsear_ficha(leer("exito_ficha_propia.html.gz"), "https://www.exito.com/x/p", ctx("exito", "1"), None)
    assert r.estado_extraccion == EstadoExtraccion.OK
    assert r.ean_publicado == "6942351438313"     # skuData.AlternateIds.Ean (gtin13 trae el SKU interno)
    assert r.sku_tienda == "3822830"
    assert r.vendedor == "exito" and r.es_vendedor_propio
    assert r.precio_venta == 1999900 and r.precio_lista == 4099900   # oferta de Éxito, no la más barata del marketplace
    assert r.referencia == "65QD5SV" and r.marca == "HISENSE" and r.pulgadas == 65


def test_exito_ficha_marketplace():
    r = exito.parsear_ficha(leer("exito_ficha_marketplace.html.gz"), "u", ctx("exito", "1"), None)
    assert not r.es_vendedor_propio and r.ean_publicado == "8806095967806"
    assert clasificacion.clasificar(r).motivo_exclusion == "VENDEDOR_EXTERNO"


def test_exito_sin_next_data():
    r = exito.parsear_ficha("<html></html>", "u", ctx("exito", "1"), None)
    assert r.estado_extraccion == EstadoExtraccion.ERROR_PARSEO


# --------------------------------------------------------------------------- clasificación

@pytest.mark.parametrize("titulo,motivo", [
    ('TV KALLEY 55" Pulgadas 139 cm 55GQ405 4K-UHD QLED Smart TV Google', None),
    ("Televisor LG 55 pulgadas UHD + Barra de sonido", "COMBO"),
    ("Combo Televisor Samsung 50 pulgadas y soporte", "COMBO"),
    ("Soporte para TV de 32 a 70 pulgadas", "NO_ES_TELEVISOR"),
    ("TV Box Xiaomi Mi Box S 4K", "NO_ES_TELEVISOR"),
    ("Televisor Samsung 55 pulgadas reacondicionado", "NO_NUEVO"),
    ("Televisor Sony 32 pulgadas LCD HD", "TECNOLOGIA_DESCONTINUADA"),
])
def test_clasificacion_por_titulo(titulo, motivo):
    r = sap_commerce.parsear_ficha(leer("alkosto_ficha_ok.html.gz"), "u", ctx("alkosto", "Alkosto"), None)
    r.titulo = titulo
    assert clasificacion.clasificar(r).motivo_exclusion == motivo


# --------------------------------------------------------------------------- cliente HTTP (sin red)

def _cliente(manejador, robots: str = "User-agent: *\nDisallow: /search/\n") -> ClienteSitio:
    def despachar(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=robots)
        return manejador(req)
    return ClienteSitio("https://tienda.test", "TFM-prueba", pausa=0, reintentos=3, max_bloqueos=3,
                        transporte=httpx.MockTransport(despachar))


def test_cliente_no_sigue_redireccion_a_ruta_prohibida():
    pedidas = []

    def manejador(req):
        pedidas.append(req.url.path)
        return httpx.Response(302, headers={"location": "/search/?text=123"})

    async def correr():
        async with _cliente(manejador) as c:
            await c.cargar_robots()
            with pytest.raises(ProhibidoPorRobots):
                await c.get("/p/123")
            with pytest.raises(ProhibidoPorRobots):
                await c.get("/search/?text=tv")
    asyncio.run(correr())
    assert pedidas == ["/p/123"]       # la ruta prohibida nunca se pidió


def test_cliente_reintenta_5xx_y_se_detiene_ante_bloqueo():
    respuestas = iter([500, 200])

    async def correr():
        async with _cliente(lambda req: httpx.Response(next(respuestas), text="ok")) as c:
            await c.cargar_robots()
            assert (await c.get("/p/1")).estado == 200
        async with _cliente(lambda req: httpx.Response(403)) as c:
            await c.cargar_robots()
            with pytest.raises(SitioBloqueado):
                await c.get("/p/2")
    asyncio.run(correr())


def test_cliente_se_detiene_con_el_primer_desafio_de_cloudflare():
    # 12-nov-2026: Éxito responde 403 con cf-mitigated: challenge. Un solo intento, sin reintentos.
    pedidas = []

    def manejador(req):
        pedidas.append(req.url.path)
        return httpx.Response(403, headers={"cf-mitigated": "challenge"}, text="<html>Just a moment</html>")

    async def correr():
        async with _cliente(manejador) as c:
            await c.cargar_robots()
            with pytest.raises(DesafioVerificacion):
                await c.get("/p/1")
    asyncio.run(correr())
    assert pedidas == ["/p/1"]


def test_mensaje_de_bloqueo_sin_observacion():
    from src.extraccion.ejecutar import SIN_OBSERVACION, mensaje_bloqueo
    assert mensaje_bloqueo(DesafioVerificacion("x"), 0).startswith(f"{SIN_OBSERVACION} (desafío de verificación)")
    assert mensaje_bloqueo(SitioBloqueado("x"), 10).startswith("Sitio detenido por bloqueo")


# --------------------------------------------------------------------------- emparejamiento

from src.catalogo.emparejamiento import IndiceReferencias, clave_de, emparejar  # noqa: E402


def _indice() -> IndiceReferencias:
    i = IndiceReferencias()
    i.agregar(clave_de("HYUNDAI", 43, "HYLED4326QG"), "07707138077883")
    i.agregar(clave_de("LG", 65, "65UT7300PSA"), "08806091111111")
    i.agregar(clave_de("LG", 55, "55UT7300PSA"), "08806092222222")
    return i


def test_emparejar_por_ean_valido():
    assert emparejar("7707138077883", None, None, None, _indice()) == ("07707138077883", "EAN")


def test_emparejar_por_referencia_y_sufijo_regional():
    i = _indice()
    assert emparejar(None, "HYUNDAI", 43, "HYLED4326", i) == ("07707138077883", "REFERENCIA")
    assert emparejar("123", "LG", 65, "UT7300PSA", i) == ("08806091111111", "REFERENCIA")  # EAN inválido


def test_emparejar_exige_mismas_pulgadas():
    assert emparejar(None, "LG", 50, "50UT7300PSA", _indice()) == (None, "SIN_EMPAREJAR")


# --------------------------------------------------------------------------- informe

def test_informe_cuenta_coincidencias_entre_cadenas():
    import pandas as pd
    from src.extraccion.informe import construir

    base = dict(id_ejecucion="x", fecha_captura_col="2026-10-13T06:00:00-05:00", sku_tienda="1",
                titulo="Televisor LG 55 pulgadas 55UT7300", marca="LG", pulgadas=55.0, referencia="55UT7300",
                en_alcance=True, es_vendedor_propio=True, disponible=True, estado_extraccion="OK",
                motivo_exclusion=None, precio_venta=1000.0)
    filas = [
        {**base, "sitio": "alkosto", "url": "a", "ean_publicado": "8806091111111", "gtin14": "08806091111111"},
        {**base, "sitio": "ktronix", "url": "k", "ean_publicado": "8806091111111", "gtin14": "08806091111111"},
        {**base, "sitio": "jumbo", "url": "j", "ean_publicado": None, "gtin14": None},          # por referencia
        {**base, "sitio": "olimpica", "url": "o", "ean_publicado": "7700136724490", "gtin14": "07700136724490",
         "titulo": "Televisor Olimpo 43 pulgadas D8200S", "marca": "OLIMPO", "pulgadas": 43.0, "referencia": "D8200S"},
    ]
    maestro = pd.DataFrame({"gtin14": ["08806091111111"], "clave_referencia": ["LG|55|UT7300"]})
    texto = construir(pd.DataFrame(filas), maestro)
    assert "| sitio | EAN | REFERENCIA | en maestro | en ≥2 cadenas | emparejados % |" in texto
    assert "| jumbo | 0 | 1 | 1 | 1 | 100.0 |" in texto
    assert "| olimpica | 1 | 0 | 0 | 0 | 0.0 |" in texto
    assert "75.0 %" in texto          # 3 de 4 ofertas emparejadas; Olimpo solo está en Olímpica


def test_servicio_de_instalacion_no_es_televisor():
    assert clasificacion.es_accesorio("Instalación Tv hasta 55 Pulgadas")
    assert not clasificacion.es_accesorio("Televisor TCL 75 Inch 4K LED Google TV")


# --------------------------------------------------------------------------- modo asistido de Éxito (sin navegador)

def test_asistido_reconoce_ficha_y_desafio():
    from src.extraccion import asistido
    assert asistido.estado_pagina(leer("exito_ficha_propia.html.gz"), "Televisor") == asistido.FICHA
    desafio = '<html><head><title>Just a moment...</title></head><body><div id="cf-chl-widget"></div></body></html>'
    assert asistido.estado_pagina(desafio, "Just a moment...") == asistido.DESAFIO
    assert asistido.estado_pagina("<html></html>", "", cf_mitigated="challenge") == asistido.DESAFIO
    assert asistido.estado_pagina("<html><h1>Error</h1></html>", "exito.com") == asistido.OTRA


def test_asistido_ubicacion_e_identificacion():
    from src.extraccion import asistido
    assert asistido.contexto_ubicacion('{"regionId":"v2.ABC","postalCode":null}') == "regionId=v2.ABC"
    assert asistido.contexto_ubicacion("<html></html>").startswith("sin región")
    assert asistido.usuario_identificado("Mozilla/5.0 Chrome/142", "TFM/0.2") == "Mozilla/5.0 Chrome/142 TFM/0.2"


def test_la_corrida_programada_no_usa_el_modo_asistido():
    raiz = Path(__file__).resolve().parents[1] / "src"
    for modulo in ("nube/tarea.py", "extraccion/ejecutar.py"):
        assert "asistido" not in (raiz / modulo).read_text(encoding="utf-8")
