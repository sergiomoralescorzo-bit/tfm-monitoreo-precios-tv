# -*- coding: utf-8 -*-
"""Éxito con Scrapling (AsyncStealthySession), motor de captura desde el 16-nov-2026.

Desde el 12-nov-2026 Éxito responde al cliente HTTP del proyecto con un desafío de Cloudflare
(`cf-mitigated: challenge`). El grupo decidió el 16-nov-2026 usar Scrapling, que abre las páginas con un
Chromium modificado para no ser detectado como automatizado y, si aparece el desafío, lo resuelve
(`solve_cloudflare=True`).

`ClienteScrapling` tiene la misma interfaz que `ClienteSitio` (`get`, `permite`, `peticiones`), así que
`ejecutar.py` lo usa sin cambiar la captura de fichas, el parseo, Bronze ni el registro de ejecuciones.
Se activa con `motor: scrapling` en la fuente de `config/fuentes.yaml`.

Qué se conserva:
- robots.txt se lee con el cliente HTTP (responde 200) y se respeta: Éxito prohíbe /api/, facetas y
  ordenamientos. Cada URL se valida antes de pedirla.
- Una página a la vez, con pausa mínima entre páginas (`pausa_segundos`, al menos 3 s).
- Si después de la resolución automática la página sigue siendo un desafío, se lanza
  `DesafioVerificacion`: Éxito se detiene sin más peticiones («Sin observación por bloqueo»).

Trazabilidad: `metodo=scrapling_stealth`; el mensaje de cada ficha anota la versión de Scrapling, el HTTP
y lo que Scrapling informó sobre Cloudflare.

Uso directo (desde la raíz del proyecto), equivalente a `python -m src.extraccion.ejecutar --sitios exito`:
    .venv\\Scripts\\python -m src.extraccion.scrapling_exito --limite 5
    .venv\\Scripts\\python -m src.extraccion.scrapling_exito --modo seguimiento --visible
"""
import argparse
import asyncio
import logging
import re
import sys
import time

from src.extraccion.cliente import ClienteSitio, DesafioVerificacion, ProhibidoPorRobots, Respuesta
from src.extraccion.sitios import exito
from src.extraccion.sitios.base import Objetivo

log = logging.getLogger("scrapling_exito")

METODO = "scrapling_stealth"
ESPERA_FICHA = "script#__NEXT_DATA__"
ESPERA_LISTADO = "a[href$='/p']"
_XML = re.compile(rb"^\s*(<\?xml|<urlset|<sitemapindex)")


# --------------------------------------------------------------------------- reglas (sin navegador)

class _EventosScrapling(logging.Handler):
    """Guarda lo que Scrapling informa sobre Cloudflare durante una petición."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.mensajes: list[str] = []

    def emit(self, rec: logging.LogRecord) -> None:
        texto = rec.getMessage()
        if "cloudflare" in texto.lower() or "turnstile" in texto.lower():
            self.mensajes.append(texto)

    def tomar(self) -> list[str]:
        salida, self.mensajes = self.mensajes, []
        return salida


def resumen_desafio(mensajes: list[str]) -> str:
    """'sin desafío', 'desafío resuelto por Scrapling' o los mensajes crudos si no se reconocen."""
    if not mensajes:
        return "sin aviso de Cloudflare"
    texto = " | ".join(mensajes).lower()
    if "no cloudflare challenge" in texto:
        return "sin desafío de Cloudflare"
    if "solved" in texto or "bypassed" in texto:
        return "desafío de Cloudflare resuelto por Scrapling"
    return "Cloudflare: " + " | ".join(mensajes)[:160]


def version_scrapling() -> str:
    try:
        import scrapling
        return scrapling.__version__
    except Exception:
        return "?"


def cuerpo_y_texto(body, html_renderizado: str) -> tuple[str, bytes]:
    """XML (sitemaps): la respuesta tal cual. HTML: el DOM renderizado, que trae el listado del cliente."""
    crudo = bytes(body) if isinstance(body, (bytes, bytearray)) else str(body or "").encode("utf-8")
    if _XML.match(crudo):
        return crudo.decode("utf-8", errors="replace"), crudo
    return html_renderizado, html_renderizado.encode("utf-8")


# --------------------------------------------------------------------------- cliente

class ClienteScrapling:
    """Misma interfaz que ClienteSitio; las peticiones salen por un navegador de Scrapling."""

    def __init__(self, http: ClienteSitio, pausa: float = 3.0, headless: bool = True, timeout_s: float = 90,
                 sesion=None, reciclar_cada: int = 0, fabrica=None):
        self.http = http                 # robots.txt y la base del sitio
        self.base = http.base
        self.pausa = max(float(pausa), 3.0)
        self.headless = headless
        self.timeout_s = timeout_s
        self.peticiones = 0
        self.nota = ""                   # lo ocurrido en la última petición, para el registro
        self.version = version_scrapling()
        self._sesion = sesion            # inyectable en pruebas
        self._propia = sesion is None
        # Cerrar y abrir el navegador cada `reciclar_cada` peticiones libera la memoria que Chromium acumula.
        # El 18-nov-2026 el contenedor (2 GiB) se quedó sin memoria a los 60 min y Azure lo terminó.
        self.reciclar_cada = int(reciclar_cada or 0)
        self.reciclajes = 0
        self._desde_apertura = 0
        self._fabrica = fabrica or self._sesion_scrapling
        self._lock = asyncio.Lock()
        self._ultima = 0.0
        self._eventos = _EventosScrapling()

    def _sesion_scrapling(self):
        from scrapling.fetchers import AsyncStealthySession
        return AsyncStealthySession(
            headless=self.headless, solve_cloudflare=True, timeout=int(self.timeout_s * 1000),
            locale="es-CO", timezone_id="America/Bogota", retries=2, retry_delay=5,
            wait_selector_state="attached")

    async def _abrir(self) -> None:
        self._sesion = self._fabrica()
        await self._sesion.__aenter__()
        self._desde_apertura = 0

    async def _reciclar(self) -> None:
        """Cierra el navegador y abre otro (solo si la sesión es propia)."""
        try:
            await self._sesion.__aexit__(None, None, None)
        except Exception as e:
            log.warning("No se pudo cerrar la sesión de Scrapling (%s); se abre otra", type(e).__name__)
        await self._abrir()
        self.reciclajes += 1
        log.info("Sesión de Scrapling reciclada (%d) tras %d peticiones", self.reciclajes, self.peticiones)

    async def __aenter__(self):
        logging.getLogger("scrapling").addHandler(self._eventos)
        if self._sesion is None:
            await self._abrir()
        return self

    async def __aexit__(self, *exc):
        try:
            if self._propia and self._sesion is not None:
                await self._sesion.__aexit__(*exc)
        finally:
            logging.getLogger("scrapling").removeHandler(self._eventos)

    def permite(self, url: str) -> bool:
        return self.http.permite(url)

    async def get(self, url: str, espera: str | None = ESPERA_FICHA) -> Respuesta:
        if url.startswith("/"):
            url = self.base + url
        if not self.permite(url):
            raise ProhibidoPorRobots(url)
        async with self._lock:
            falta = self.pausa - (time.monotonic() - self._ultima)
            if falta > 0:
                await asyncio.sleep(falta)
            if self._propia and self.reciclar_cada and self._desde_apertura >= self.reciclar_cada:
                await self._reciclar()
            self.peticiones += 1
            self._desde_apertura += 1
            self._eventos.tomar()
            try:
                opciones = {"wait_selector": espera} if espera and not url.endswith(".xml") else {}
                r = await self._sesion.fetch(url, **opciones)
            finally:
                self._ultima = time.monotonic()
        html = r.html_content or ""
        cf = (r.headers or {}).get("cf-mitigated")
        titulo = r.css("title::text").get() or ""
        self.nota = f"{METODO}; scrapling {self.version}; HTTP {r.status}; {resumen_desafio(self._eventos.tomar())}"
        from src.extraccion.asistido import DESAFIO, estado_pagina   # aquí: asistido importa ejecutar
        texto, contenido = cuerpo_y_texto(r.body, html)
        # Un sitemap que llega como XML no es un desafío (en Azure llegó tras un 307 y se tomaba por uno).
        if not _XML.match(contenido) and estado_pagina(html, titulo, cf) == DESAFIO:
            raise DesafioVerificacion(f"desafío de Cloudflare sin resolver por Scrapling (HTTP {r.status}) en {url}")
        return Respuesta(str(r.url or url), int(r.status), texto, contenido)


# --------------------------------------------------------------------------- descubrimiento

async def descubrir(cliente: ClienteScrapling, listados: list[str], parametro: str, max_paginas: int,
                    guardar) -> tuple[list[Objetivo], int]:
    """Igual que exito.descubrir (?page=1..N de cada listado), pero con el navegador de Scrapling."""
    urls: list[str] = []
    vistos: set[str] = set()
    paginas = 0
    for listado in listados:
        sin_novedad = 0
        nombre = listado.rstrip("/").rsplit("/", 1)[-1]
        for n in range(1, max_paginas + 1):
            url = cliente.base + listado + ("" if n == 1 else f"?{parametro}={n}")
            if not cliente.permite(url):
                log.warning("robots.txt prohíbe %s", url)
                break
            try:
                r = await cliente.get(url, espera=ESPERA_LISTADO)
            except DesafioVerificacion:
                raise
            except Exception as e:
                log.info("%s: página %d sin respuesta (%s)", nombre, n, type(e).__name__)
                break
            enlaces = exito.enlaces_de_listado(r.texto, cliente.base)
            if not enlaces:
                log.info("%s: página %d sin productos", nombre, n)
                break
            guardar(f"listado_{nombre}_p{n}", r.texto)
            paginas += 1
            nuevos = [u for u in enlaces if u not in vistos]
            vistos.update(nuevos)
            urls += nuevos
            sin_novedad = sin_novedad + 1 if not nuevos else 0
            if sin_novedad >= 2:
                break
        log.info("%s: %d fichas acumuladas", nombre, len(urls))
    return [Objetivo(clave=u, url=u) for u in urls], paginas


# --------------------------------------------------------------------------- uso directo

def main(argv: list[str] | None = None) -> int:
    from src.extraccion.ejecutar import cargar_config, ejecutar, imprimir_resumen
    from src.extraccion.modelos import EstadoEjecucion

    config = cargar_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modo", choices=["completo", "seguimiento"], default="completo")
    ap.add_argument("--limite", type=int, help="máximo de fichas (para pruebas)")
    ap.add_argument("--datos", help="carpeta raíz de datos (como en src.extraccion.ejecutar)")
    ap.add_argument("--visible", action="store_true", help="muestra la ventana del navegador")
    args = ap.parse_args(argv)
    for flujo in (sys.stdout, sys.stderr):
        flujo.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    config["fuentes"]["exito"]["motor"] = "scrapling"
    if args.visible:
        config["fuentes"]["exito"]["headless"] = False
    ejecuciones = asyncio.run(ejecutar(["exito"], args.modo, args.limite, args.datos, config))
    imprimir_resumen(ejecuciones)
    return 0 if all(e.estado != EstadoEjecucion.FALLIDA for e in ejecuciones) else 1


if __name__ == "__main__":
    sys.exit(main())
