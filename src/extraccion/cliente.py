# -*- coding: utf-8 -*-
"""Cliente HTTP de un sitio: respeta robots.txt, una petición a la vez, pausa mínima y reintentos.

Política de captura responsable (Etapa 1, sección 2): si el sitio responde 403/429 de forma
repetida, se detiene la captura de ese sitio y se registra BLOQUEADO; no se intenta esquivarlo.
Un desafío de verificación (Cloudflare marca la respuesta con `cf-mitigated: challenge`) detiene
el sitio con la primera respuesta: reintentar no lo resuelve y solo suma peticiones (Éxito, 12-nov-2026).
"""
import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

from .robots import ReglasRobots

log = logging.getLogger(__name__)


class SitioBloqueado(Exception):
    """El sitio rechazó varias peticiones seguidas (403/429)."""


class DesafioVerificacion(SitioBloqueado):
    """El sitio pide una verificación de navegador (desafío de Cloudflare). Un cliente HTTP no la
    supera y no se intenta: la corrida programada omite el sitio (ver src/extraccion/asistido.py)."""


def es_desafio(estado: int, cabeceras) -> bool:
    """Respuesta de desafío de Cloudflare. Se decide por la cabecera, no solo por el código 403."""
    return estado in (403, 429, 503) and (cabeceras.get("cf-mitigated") or "").lower() == "challenge"


class ProhibidoPorRobots(Exception):
    """La URL está prohibida por el robots.txt del sitio."""


@dataclass
class Respuesta:
    url: str            # URL final, tras redirecciones
    estado: int
    texto: str
    contenido: bytes


class ClienteSitio:
    def __init__(self, base: str, user_agent: str, pausa: float = 1.5, reintentos: int = 3,
                 timeout: float = 30, max_bloqueos: int = 3, transporte=None):
        self.base = base.rstrip("/")
        self.user_agent = user_agent
        self.pausa = pausa
        self.reintentos = reintentos
        self.max_bloqueos = max_bloqueos
        self.robots: ReglasRobots | None = None
        self.peticiones = 0
        self._ultima = 0.0
        self._bloqueos_seguidos = 0
        self._lock = asyncio.Lock()
        self._http = httpx.AsyncClient(
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/json,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-CO,es;q=0.9",
            },
            follow_redirects=False, timeout=timeout, transport=transporte,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self._http.aclose()

    async def cargar_robots(self) -> None:
        r = await self._pedir(self.base + "/robots.txt", verificar_robots=False)
        self.robots = ReglasRobots(r.texto if r.estado == 200 else "", self.user_agent)

    def permite(self, url: str) -> bool:
        return self.robots is None or self.robots.permite(url)

    async def get(self, url: str) -> Respuesta:
        if url.startswith("/"):
            url = self.base + url
        return await self._pedir(url)

    async def _pedir(self, url: str, verificar_robots: bool = True) -> Respuesta:
        if verificar_robots and not self.permite(url):
            raise ProhibidoPorRobots(url)
        async with self._lock:
            ultimo_error: Exception | None = None
            for intento in range(1, self.reintentos + 1):
                espera = self.pausa - (time.monotonic() - self._ultima)
                if espera > 0:
                    await asyncio.sleep(espera)
                self._ultima = time.monotonic()
                self.peticiones += 1
                try:
                    r = await self._seguir(url, verificar_robots)
                except httpx.TransportError as e:
                    ultimo_error = e
                    log.warning("Error de red en %s (intento %d): %s", url, intento, e)
                    await asyncio.sleep(self.pausa * 2 ** intento)
                    continue
                if es_desafio(r.status_code, r.headers):
                    raise DesafioVerificacion(f"desafío de Cloudflare (HTTP {r.status_code}, cf-mitigated: challenge) en {url}")
                if r.status_code in (403, 429):
                    self._bloqueos_seguidos += 1
                    if self._bloqueos_seguidos >= self.max_bloqueos:
                        raise SitioBloqueado(f"{r.status_code} en {url}")
                    await asyncio.sleep(self.pausa * 4 * intento)
                    continue
                self._bloqueos_seguidos = 0
                if r.status_code >= 500:
                    ultimo_error = httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
                    await asyncio.sleep(self.pausa * 2 ** intento)
                    continue
                return Respuesta(str(r.url), r.status_code, r.text, r.content)
            if ultimo_error:
                raise ultimo_error
            raise SitioBloqueado(f"Rechazos repetidos en {url}")

    async def _seguir(self, url: str, verificar_robots: bool, saltos: int = 5) -> httpx.Response:
        """GET siguiendo redirecciones a mano: cada destino se valida contra robots.txt antes de pedirlo."""
        for _ in range(saltos):
            r = await self._http.get(url)
            if not r.is_redirect:
                return r
            url = str(r.url.join(r.headers["location"]))
            if verificar_robots and not self.permite(url):
                raise ProhibidoPorRobots(url)
        return r
