# -*- coding: utf-8 -*-
"""Captura asistida de Éxito: Chrome visible, perfil propio y una persona presente (prueba, 12-nov-2026).

Desde el 12-nov-2026 Éxito responde a las fichas con un desafío de Cloudflare (`cf-mitigated: challenge`).
Este modo comprueba si un navegador completo, que ejecuta JavaScript y conserva la sesión, puede ver las
fichas y, si aparece una verificación, deja que la persona la resuelva a mano en la ventana.

Qué hace y qué no:
- Chrome instalado (`channel="chrome"`), visible, con un perfil exclusivo fuera de OneDrive
  (%LOCALAPPDATA%/TFM_MonitoreoPrecios/perfil_exito_asistido). Nunca el perfil personal. Las cookies
  quedan solo en ese perfil; no se leen, no se registran ni se suben.
- Una página a la vez, pausa mínima entre fichas, espera por elementos visibles y reintentos limitados.
- Si aparece una verificación, pausa con un aviso y sigue solo cuando la ficha es accesible. Si nadie la
  resuelve en `--espera-verificacion` segundos, termina la captura de Éxito (sin más peticiones) y deja
  el día como «sin observación por bloqueo».
- Sin ocultamiento, sin huellas falsas, sin proxies y sin resolución automática de CAPTCHA. El
  User-Agent de Chrome lleva además la identificación del proyecto.
- No forma parte de la corrida programada (src/nube/tarea.py nunca lo llama). Allí, el desafío detiene
  a Éxito con la primera respuesta y los demás sitios siguen.

Uso (desde la raíz del proyecto):
    .venv\\Scripts\\python -m src.extraccion.asistido --limite 1
    .venv\\Scripts\\python -m src.extraccion.asistido --url https://www.exito.com/<slug>/p
    .venv\\Scripts\\python -m src.extraccion.asistido --limite 20 --subir    # sube la corrida al lago
"""
import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
import uuid
from pathlib import Path

from src.extraccion import clasificacion
from src.extraccion.bronze import AlmacenBronze
from src.extraccion.cliente import ClienteSitio
from src.extraccion.ejecutar import (SIN_OBSERVACION, anexar_ejecucion, cargar_config, escribir_capturas,
                                     leer_objetivos, raiz_datos)
from src.extraccion.modelos import EstadoEjecucion, EstadoExtraccion, RegistroCaptura, RegistroEjecucion
from src.extraccion.sitios import exito
from src.extraccion.sitios.base import Contexto, Objetivo, ahora, registro

log = logging.getLogger("asistido")

SITIO = "exito"
METODO = "navegador_asistido"
PERFIL = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "TFM_MonitoreoPrecios" / "perfil_exito_asistido"

FICHA, DESAFIO, OTRA = "FICHA", "DESAFIO", "OTRA"
_TITULOS_DESAFIO = ("just a moment", "un momento", "attention required", "verifica", "verifying")


# --------------------------------------------------------------------------- reglas (sin navegador)

def estado_pagina(html: str, titulo: str = "", cf_mitigated: str | None = None) -> str:
    """FICHA si la página trae los datos del producto; DESAFIO si es una verificación de Cloudflare."""
    m = exito._NEXT_DATA.search(html or "")
    if m:
        try:
            datos = (json.loads(m.group(1)).get("props") or {}).get("pageProps", {}).get("data") or {}
            if datos.get("product"):
                return FICHA
        except json.JSONDecodeError:
            pass
    t = (titulo or "").strip().lower()
    if ((cf_mitigated or "").lower() == "challenge" or "challenges.cloudflare.com/cdn-cgi" in (html or "")
            or "cf-chl" in (html or "") or (t and any(t.startswith(x) for x in _TITULOS_DESAFIO))):
        return DESAFIO
    return OTRA


def contexto_ubicacion(html: str) -> str:
    """Región o código postal con que el sitio calculó el precio, si la página los trae."""
    partes = []
    for campo in ("regionId", "postalCode", "salesChannel"):
        m = re.search(rf'"{campo}"\s*:\s*"?([^",}}]*)"?', html or "")
        if m and m.group(1) not in ("", "null"):
            partes.append(f"{campo}={m.group(1)[:60]}")
    return "; ".join(partes) or "sin región ni código postal en la página"


def usuario_identificado(ua_chrome: str, ua_proyecto: str) -> str:
    return ua_chrome if ua_proyecto in ua_chrome else f"{ua_chrome} {ua_proyecto}"


# --------------------------------------------------------------------------- navegador

def avisar(mensaje: str) -> None:
    """Aviso visible en la consola (con campana), para la persona que acompaña la captura."""
    linea = "=" * 78
    print(f"\a\n{linea}\n  ATENCIÓN · {mensaje}\n{linea}\n", flush=True)


async def leer_estado(pagina, cf_mitigated: str | None = None) -> tuple[str, str]:
    try:
        html = await pagina.content()
        titulo = await pagina.title()
    except Exception:          # la página navega (por ejemplo, al superar la verificación)
        return OTRA, ""
    return estado_pagina(html, titulo, cf_mitigated), html


async def esperar(pagina, segundos: float, objetivo=(FICHA, DESAFIO), cf_mitigated: str | None = None,
                  cada: float = 2.0) -> tuple[str, str]:
    """Consulta la página cada `cada` segundos (no hace peticiones nuevas) hasta llegar a `objetivo`."""
    limite = time.monotonic() + segundos
    estado, html = await leer_estado(pagina, cf_mitigated)
    while estado not in objetivo and time.monotonic() < limite:
        await pagina.wait_for_timeout(int(cada * 1000))
        estado, html = await leer_estado(pagina)
    return estado, html


async def abrir_ficha(pagina, url: str, espera_verificacion: float, reintentos: int = 2,
                      pausa: float = 5.0) -> tuple[str, str, int | None, str]:
    """(estado, html, código HTTP, cómo se llegó). Ante una verificación espera a la persona; no recarga."""
    from playwright.async_api import TimeoutError as TiempoAgotado
    codigo, via = None, ""
    for intento in range(1, reintentos + 1):
        try:
            r = await pagina.goto(url, wait_until="domcontentloaded", timeout=60000)
        except TiempoAgotado:
            log.warning("Tiempo agotado al abrir %s (intento %d de %d)", url, intento, reintentos)
            await pagina.wait_for_timeout(int(pausa * 1000 * intento))
            continue
        codigo = r.status if r else None
        cf = r.headers.get("cf-mitigated") if r else None
        via = f"HTTP inicial {codigo}" + (f", cf-mitigated={cf}" if cf else "")
        estado, html = await esperar(pagina, 20, cf_mitigated=cf)
        if estado == DESAFIO:
            avisar(f"Éxito pide una verificación. Resuélvala en la ventana de Chrome; espero hasta "
                   f"{espera_verificacion:.0f} s. Si nadie interviene, la captura de Éxito termina.")
            estado, html = await esperar(pagina, espera_verificacion, objetivo=(FICHA,))
            if estado != FICHA:
                return DESAFIO, html, codigo, via
            print("  Verificación superada: la ficha es accesible. Continúo.", flush=True)
            via += ", verificación resuelta por la persona"
        elif estado == FICHA and cf:
            via += ", Chrome superó el desafío sin intervención"
        if estado == FICHA:
            try:   # el título del producto visible: la página terminó de pintarse
                await pagina.locator("h1").first.wait_for(state="visible", timeout=15000)
            except TiempoAgotado:
                pass
            return FICHA, await pagina.content(), codigo, via
        if codigo == 404:
            return OTRA, html, codigo, via
        log.warning("La página no trae la ficha (HTTP %s, intento %d de %d)", codigo, intento, reintentos)
        await pagina.wait_for_timeout(int(pausa * 1000 * intento))
    return OTRA, "", codigo, via


async def capturar(objetivos: list[Objetivo], ctx: Contexto, bronze: AlmacenBronze, comunes: dict, permite,
                   espera_verificacion: float, perfil: Path) -> tuple[list[RegistroCaptura], str]:
    from playwright.async_api import async_playwright
    registros: list[RegistroCaptura] = []
    mensaje = ""
    pausa = max(float(comunes["pausa_segundos"]), 3.0)
    perfil.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        contexto = await p.chromium.launch_persistent_context(
            str(perfil), channel="chrome", headless=False, locale="es-CO",
            viewport={"width": 1366, "height": 900})
        try:
            pagina = contexto.pages[0] if contexto.pages else await contexto.new_page()
            ua = usuario_identificado(await pagina.evaluate("navigator.userAgent"), comunes["user_agent"])
            await contexto.set_extra_http_headers({"User-Agent": ua})
            for i, o in enumerate(objetivos, 1):
                if not permite(o.url):
                    registros.append(registro(ctx, o.url, EstadoExtraccion.PROHIBIDO_ROBOTS, mensaje="robots.txt"))
                    continue
                log.info("[%d/%d] %s", i, len(objetivos), o.url)
                estado, html, codigo, via = await abrir_ficha(pagina, o.url, espera_verificacion)
                if estado == DESAFIO:
                    mensaje = (f"{SIN_OBSERVACION} (desafío de verificación sin resolver en "
                               f"{espera_verificacion:.0f} s, modo asistido)")
                    registros.append(registro(ctx, o.url, EstadoExtraccion.BLOQUEADO, mensaje=mensaje))
                    log.error(mensaje)
                    break          # sin más peticiones mientras siga el bloqueo
                nombre = o.clave.removesuffix("/p").rsplit("/", 1)[-1]
                ruta = bronze.guardar(nombre, html, "html") if html else None
                if estado == FICHA:
                    r = exito.parsear_ficha(html, pagina.url, ctx, ruta)
                    r.mensaje = f"{METODO}; {via}; {contexto_ubicacion(html)}"
                elif codigo == 404:
                    r = registro(ctx, o.url, EstadoExtraccion.NO_ENCONTRADO, ruta, mensaje="HTTP 404")
                else:
                    r = registro(ctx, o.url, EstadoExtraccion.ERROR_HTTP, ruta,
                                 mensaje=f"{METODO}: la página no trajo la ficha (HTTP {codigo})")
                registros.append(r)
                if i < len(objetivos):
                    await pagina.wait_for_timeout(int(pausa * 1000))
        finally:
            await contexto.close()
    return registros, mensaje


async def ejecutar(objetivos: list[Objetivo], config: dict, raiz: Path, espera_verificacion: float,
                   perfil: Path = PERFIL) -> tuple[list[RegistroCaptura], RegistroEjecucion]:
    fuente, comunes = config["fuentes"][SITIO], config["comunes"]
    inicio_utc, col = ahora()
    id_ejecucion = f"{col:%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:6]}"
    fecha = col.date().isoformat()
    t0 = time.monotonic()
    ctx = Contexto(id_ejecucion, SITIO, fuente["cadena"], METODO, str(fuente["vendedor_propio"]))
    bronze = AlmacenBronze(raiz, SITIO, fecha, id_ejecucion)
    ej = RegistroEjecucion(id_ejecucion=id_ejecucion, sitio=SITIO, modo="asistido", inicio=inicio_utc,
                           descubiertos=len(objetivos))
    registros: list[RegistroCaptura] = []
    try:
        async with ClienteSitio(fuente["sitio"], comunes["user_agent"], comunes["pausa_segundos"]) as cliente:
            await cliente.cargar_robots()        # solo robots.txt (responde 200 aunque las fichas pidan verificación)
            registros, ej.mensaje = await capturar(objetivos, ctx, bronze, comunes, cliente.permite,
                                                   espera_verificacion, perfil)
    except Exception as e:
        ej.mensaje = f"{type(e).__name__}: {e}"[:300]
        log.exception("Captura asistida fallida")
    for r in registros:
        clasificacion.clasificar(r)
    estados = [r.estado_extraccion for r in registros]
    ej.consultados = sum(s != EstadoExtraccion.PROHIBIDO_ROBOTS for s in estados)
    ej.ok = estados.count(EstadoExtraccion.OK)
    ej.sin_stock = estados.count(EstadoExtraccion.SIN_STOCK)
    ej.no_encontrados = estados.count(EstadoExtraccion.NO_ENCONTRADO)
    ej.bloqueados = estados.count(EstadoExtraccion.BLOQUEADO)
    ej.errores = sum(estados.count(s) for s in (EstadoExtraccion.ERROR_HTTP, EstadoExtraccion.ERROR_PARSEO,
                                                EstadoExtraccion.PROHIBIDO_ROBOTS))
    ej.registros, ej.en_alcance = len(registros), sum(1 for r in registros if r.en_alcance)
    if ej.ok + ej.sin_stock == 0:
        ej.estado = EstadoEjecucion.FALLIDA
        ej.mensaje = ej.mensaje or f"{SIN_OBSERVACION}: ninguna ficha accesible (modo asistido)"
    elif ej.errores or ej.bloqueados or ej.consultados < ej.descubiertos:
        ej.estado = EstadoEjecucion.PARCIAL
    else:
        ej.estado = EstadoEjecucion.EXITOSA
    ej.mensaje = ej.mensaje or f"{METODO}: {ej.ok + ej.sin_stock} fichas con datos"
    ej.fin, _ = ahora()
    ej.duracion_s = round(time.monotonic() - t0, 1)
    if registros:
        escribir_capturas(raiz, SITIO, fecha, id_ejecucion, registros)
    anexar_ejecucion(raiz, ej)
    return registros, ej


def main(argv: list[str] | None = None) -> int:
    config = cargar_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", action="append", help="ficha de Éxito (se puede repetir); por defecto, las del estado")
    ap.add_argument("--limite", type=int, default=1, help="máximo de fichas (por defecto 1, para probar)")
    ap.add_argument("--espera-verificacion", type=float, default=300,
                    help="segundos que espera a que una persona resuelva la verificación (por defecto 300)")
    ap.add_argument("--datos", help="carpeta raíz de datos (como en src.extraccion.ejecutar)")
    ap.add_argument("--perfil", default=str(PERFIL), help="perfil exclusivo de Chrome para este modo")
    ap.add_argument("--subir", action="store_true", help="sube la corrida al lago (sin el estado de fichas)")
    args = ap.parse_args(argv)
    for flujo in (sys.stdout, sys.stderr):
        flujo.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    raiz = raiz_datos(config, args.datos)
    if args.url:
        objetivos = [Objetivo(clave=u, url=u) for u in args.url]
    else:
        objetivos = leer_objetivos(raiz, SITIO) or []
        if not objetivos:
            ap.error(f"no hay fichas en {raiz / 'estado'}; use --url")
    objetivos = objetivos[:args.limite]
    registros, ej = asyncio.run(ejecutar(objetivos, config, raiz, args.espera_verificacion, Path(args.perfil)))

    print(f"\nÉxito (asistido) · {ej.estado.value} · {ej.ok} OK, {ej.sin_stock} sin stock, "
          f"{ej.bloqueados} bloqueadas, {ej.errores} con error · {ej.duracion_s:.0f} s\n  {ej.mensaje}")
    for r in registros:
        print(f"  {r.estado_extraccion.value:<10} {r.precio_venta or '':>10} {r.titulo or ''}\n"
              f"             {r.url}\n             {r.mensaje or ''}")
    if args.subir and registros:
        from src.nube import lago
        n = lago.subir_corrida(lago.destino_desde_entorno(), raiz, ej.id_ejecucion, con_estado=False)
        print(f"  Corrida {ej.id_ejecucion} subida al lago: {n} archivos")
    return 0 if ej.estado != EstadoEjecucion.FALLIDA else 1


if __name__ == "__main__":
    sys.exit(main())
