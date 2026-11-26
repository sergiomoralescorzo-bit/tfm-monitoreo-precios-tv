# -*- coding: utf-8 -*-
"""Corrida de extracción de los cinco sitios.

Uso:
    python -m src.extraccion.ejecutar                       # modo completo, todos los sitios
    python -m src.extraccion.ejecutar --modo seguimiento    # solo fichas ya descubiertas
    python -m src.extraccion.ejecutar --sitios jumbo,exito --limite 20

Modos (Etapa 1, sección 5):
    completo     descubre las fichas de televisores (sitemap o listado) y captura todas.
    seguimiento  captura las fichas del último descubrimiento (si no hay, descubre).

Salidas, bajo la raíz de datos (config `almacenamiento.raiz_datos` o variable TFM_DATOS):
    bronze/{sitio}/fecha=AAAA-MM-DD/{id_ejecucion}/...       respuestas crudas (.gz)
    capturas/{sitio}/fecha=AAAA-MM-DD/{id_ejecucion}.csv     registros de captura (sección 4.1)
    ejecuciones/ejecuciones.csv                              registro de ejecuciones (sección 4.2)
    estado/objetivos_{sitio}.csv                             fichas descubiertas (para el seguimiento)
"""
import argparse
import asyncio
import csv
import io
import logging
import os
import sys
import time
import uuid
from contextlib import AsyncExitStack
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from src.extraccion import clasificacion, scrapling_exito, sitemap
from src.extraccion.bronze import AlmacenBronze
from src.extraccion.cliente import ClienteSitio, DesafioVerificacion, ProhibidoPorRobots, SitioBloqueado
from src.extraccion.modelos import EstadoEjecucion, EstadoExtraccion, RegistroCaptura, RegistroEjecucion
from src.extraccion.sitios import exito, sap_commerce, vtex
from src.extraccion.sitios.base import Contexto, Objetivo, ahora, registro

RAIZ_PROYECTO = Path(__file__).resolve().parents[2]
CONFIG = RAIZ_PROYECTO / "config" / "fuentes.yaml"
METODOS = {"sap_commerce": "http_html", "vtex": "http_json", "exito": "navegador+http_html"}


def usa_scrapling(fuente: dict) -> bool:
    """Motor alternativo de Éxito desde el 16-nov-2026 (`motor: scrapling` en fuentes.yaml)."""
    return fuente.get("motor") == "scrapling"


def rotar(objetivos: list, dia: int) -> list:
    """Empieza cada día en un punto distinto, para que un presupuesto de tiempo no deje siempre fuera
    las mismas fichas. El salto (paso dorado) recorre toda la lista en pocos días."""
    if not objetivos:
        return objetivos
    k = int(dia * 0.6180339887 * len(objetivos)) % len(objetivos)
    return objetivos[k:] + objetivos[:k]


def metodo(fuente: dict) -> str:
    return scrapling_exito.METODO if usa_scrapling(fuente) else METODOS[fuente["tipo"]]

log = logging.getLogger("extraccion")


def cargar_config(ruta: Path = CONFIG) -> dict:
    with open(ruta, encoding="utf-8") as f:
        return yaml.safe_load(f)


def raiz_datos(config: dict, argumento: str | None = None) -> Path:
    valor = argumento or os.environ.get("TFM_DATOS") or config["almacenamiento"]["raiz_datos"]
    ruta = Path(valor)
    return ruta if ruta.is_absolute() else RAIZ_PROYECTO / ruta


# --------------------------------------------------------------------------- estado

def guardar_objetivos(raiz: Path, sitio: str, objetivos: list[Objetivo]) -> None:
    ruta = raiz / "estado" / f"objetivos_{sitio}.csv"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["clave", "url"])
        w.writerows([o.clave, o.url] for o in objetivos)


def leer_objetivos(raiz: Path, sitio: str) -> list[Objetivo] | None:
    ruta = raiz / "estado" / f"objetivos_{sitio}.csv"
    if not ruta.exists():
        return None
    with open(ruta, encoding="utf-8") as f:
        return [Objetivo(clave=r["clave"], url=r["url"]) for r in csv.DictReader(f, delimiter=";")]


def csv_capturas(registros: list[RegistroCaptura]) -> str:
    """Tabla de productos de una corrida (separador `;`); se guarda en UTF-8 con BOM."""
    salida = io.StringIO()
    w = csv.DictWriter(salida, fieldnames=list(RegistroCaptura.model_fields), delimiter=";", lineterminator="\r\n")
    w.writeheader()
    for r in registros:
        w.writerow(r.model_dump(mode="json"))
    return salida.getvalue()


def escribir_capturas(raiz: Path, sitio: str, fecha: str, id_ejecucion: str,
                      registros: list[RegistroCaptura]) -> Path:
    ruta = raiz / "capturas" / sitio / f"fecha={fecha}" / f"{id_ejecucion}.csv"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(csv_capturas(registros), encoding="utf-8-sig", newline="")
    return ruta


def anexar_ejecucion(raiz: Path, e: RegistroEjecucion) -> None:
    ruta = raiz / "ejecuciones" / "ejecuciones.csv"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    nuevo = not ruta.exists()
    with open(ruta, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(RegistroEjecucion.model_fields), delimiter=";")
        if nuevo:
            w.writeheader()
        w.writerow(e.model_dump(mode="json"))


# Mensaje de la ejecución cuando un bloqueo deja el día sin datos del sitio. Los días bloqueados no
# tienen observaciones: no se reutilizan precios anteriores (oro solo guarda lo observado).
SIN_OBSERVACION = "Sin observación por bloqueo"


def mensaje_bloqueo(e: SitioBloqueado, ok: int, etapa: str = "") -> str:
    tipo = "desafío de verificación" if isinstance(e, DesafioVerificacion) else "bloqueo"
    previo = f"{SIN_OBSERVACION} ({tipo}{etapa})" if not ok else f"Sitio detenido por {tipo}{etapa}"
    return f"{previo}: {e}"


# --------------------------------------------------------------------------- un sitio

async def descubrir(clave: str, fuente: dict, cliente: ClienteSitio, comunes: dict,
                    bronze: AlmacenBronze) -> list[Objetivo]:
    d = fuente["descubrimiento"]
    if fuente["tipo"] == "exito":
        listados = [d["listado"]]
        if d.get("sitemap_listados"):
            try:
                urls, _ = await sitemap.urls_producto(cliente, d["sitemap_listados"], d["patron_listado"],
                                                      marca_hijos="category")
                listados += sorted({urlsplit(u).path for u in urls} - set(listados))
            except Exception as e:
                log.warning("[%s] no se pudieron leer las páginas por marca: %s", clave, e)
        guardar = lambda k, html: bronze.guardar(k, html, "html")  # noqa: E731
        if usa_scrapling(fuente):
            objetivos, paginas = await scrapling_exito.descubrir(
                cliente, listados, d["parametro_pagina"], d["max_paginas"], guardar)
        else:
            objetivos, paginas = await exito.descubrir(
                fuente["sitio"], listados, d["parametro_pagina"], d["max_paginas"],
                comunes["user_agent"], comunes["pausa_segundos"], cliente.permite, guardar)
        log.info("[%s] %d fichas en %d páginas de %d listados", clave, len(objetivos), paginas, len(listados))
        return objetivos
    urls, leidos = await sitemap.urls_producto(cliente, d["sitemap"], d["patron_url"])
    log.info("[%s] %d fichas de TV en %d archivos de sitemap", clave, len(urls), leidos)
    modulo = sap_commerce if fuente["tipo"] == "sap_commerce" else vtex
    return modulo.objetivos_desde_urls(urls)


def url_ficha(fuente: dict, o: Objetivo) -> str:
    if fuente["tipo"] == "vtex":
        return fuente["ficha"].format(slug=o.clave)
    return o.url or fuente["ficha"].format(ean=o.clave)


async def capturar(fuente: dict, o: Objetivo, cliente: ClienteSitio, ctx: Contexto,
                   bronze: AlmacenBronze) -> list[RegistroCaptura]:
    url = url_ficha(fuente, o)
    try:
        r = await cliente.get(url)
    except ProhibidoPorRobots as e:
        return [registro(ctx, o.url, EstadoExtraccion.PROHIBIDO_ROBOTS, mensaje=str(e)[:200])]
    except SitioBloqueado:
        raise
    except Exception as e:  # red, 5xx tras reintentos
        return [registro(ctx, o.url, EstadoExtraccion.ERROR_HTTP, mensaje=f"{type(e).__name__}: {e}"[:200])]
    ext = "json" if fuente["tipo"] == "vtex" else "html"
    nombre = o.clave.removesuffix("/p").rsplit("/", 1)[-1] if fuente["tipo"] == "exito" else o.clave
    ruta = bronze.guardar(nombre, r.contenido, ext)
    if r.estado == 404:
        return [registro(ctx, o.url, EstadoExtraccion.NO_ENCONTRADO, ruta, mensaje="HTTP 404")]
    if r.estado >= 400:
        return [registro(ctx, o.url, EstadoExtraccion.ERROR_HTTP, ruta, mensaje=f"HTTP {r.estado}")]
    # VTEX registra la URL de la ficha; SAP Commerce y Éxito, la URL final tras redirecciones.
    registros = parsear_respuesta(fuente["tipo"], r.texto, o.url if fuente["tipo"] == "vtex" else r.url, ctx, ruta)
    if getattr(cliente, "nota", None):            # trazabilidad del motor (Scrapling)
        for reg in registros:
            reg.mensaje = "; ".join(x for x in (cliente.nota, reg.mensaje) if x)
    return registros


def parsear_respuesta(tipo: str, texto: str, url: str, ctx: Contexto, ruta: str | None) -> list[RegistroCaptura]:
    """Respuesta guardada en bronce -> registros. La usan la captura y el reproceso (src/extraccion/reproceso.py)."""
    try:
        if tipo == "vtex":
            return vtex.parsear_producto(texto, url, ctx, ruta)
        if tipo == "sap_commerce":
            return [sap_commerce.parsear_ficha(texto, url, ctx, ruta)]
        return [exito.parsear_ficha(texto, url, ctx, ruta)]
    except Exception as e:
        log.exception("[%s] error de parseo en %s", ctx.clave_sitio, url)
        return [registro(ctx, url, EstadoExtraccion.ERROR_PARSEO, ruta, mensaje=f"{type(e).__name__}: {e}"[:200])]


async def ejecutar_sitio(clave: str, fuente: dict, comunes: dict, raiz: Path, id_ejecucion: str,
                         modo: str, limite: int | None) -> tuple[list[RegistroCaptura], RegistroEjecucion]:
    inicio_utc, inicio_col = ahora()
    fecha = inicio_col.date().isoformat()
    t0 = time.monotonic()
    ej = RegistroEjecucion(id_ejecucion=id_ejecucion, sitio=clave, modo=modo, inicio=inicio_utc)
    ctx = Contexto(id_ejecucion, clave, fuente["cadena"], metodo(fuente), str(fuente["vendedor_propio"]))
    bronze = AlmacenBronze(raiz, clave, fecha, id_ejecucion)
    registros: list[RegistroCaptura] = []
    try:
        async with ClienteSitio(fuente["sitio"], comunes["user_agent"], comunes["pausa_segundos"],
                                comunes["reintentos"], comunes["timeout_segundos"],
                                comunes["max_bloqueos_seguidos"]) as http, AsyncExitStack() as pila:
            await http.cargar_robots()
            cliente = http
            if usa_scrapling(fuente):
                cliente = await pila.enter_async_context(scrapling_exito.ClienteScrapling(
                    http, comunes["pausa_segundos"], headless=fuente.get("headless", True),
                    reciclar_cada=fuente.get("reciclar_cada", 0)))
            objetivos = leer_objetivos(raiz, clave) if modo == "seguimiento" else None
            if not objetivos:
                objetivos = await descubrir(clave, fuente, cliente, comunes, bronze)
                if limite is None:
                    guardar_objetivos(raiz, clave, objetivos)
            ej.descubiertos = len(objetivos)
            presupuesto = fuente.get("presupuesto_minutos")
            if presupuesto and limite is None:
                objetivos = rotar(objetivos, inicio_col.toordinal())
            if limite is not None:
                objetivos = objetivos[:limite]
            for i, o in enumerate(objetivos, 1):
                if presupuesto and time.monotonic() - t0 > presupuesto * 60:
                    ej.mensaje = (f"Presupuesto de {presupuesto} min agotado: {i - 1} de {len(objetivos)} "
                                  f"fichas consultadas")
                    log.warning("[%s] %s", clave, ej.mensaje)
                    break
                try:
                    registros += await capturar(fuente, o, cliente, ctx, bronze)
                except SitioBloqueado as e:
                    registros.append(registro(ctx, o.url, EstadoExtraccion.BLOQUEADO, mensaje=str(e)[:200]))
                    datos = sum(r.estado_extraccion in (EstadoExtraccion.OK, EstadoExtraccion.SIN_STOCK)
                                for r in registros)
                    ej.mensaje = mensaje_bloqueo(e, datos)
                    log.error("[%s] %s", clave, ej.mensaje)
                    break
                ej.consultados = i
                if i % 50 == 0:
                    log.info("[%s] %d/%d fichas", clave, i, len(objetivos))
            ej.mensaje = ej.mensaje or f"{cliente.peticiones} peticiones HTTP"
    except SitioBloqueado as e:
        ej.mensaje = mensaje_bloqueo(e, 0, " en el descubrimiento")
        log.error("[%s] %s", clave, ej.mensaje)
    except Exception as e:
        ej.mensaje = f"{type(e).__name__}: {e}"[:300]
        log.exception("[%s] corrida fallida", clave)

    for r in registros:
        clasificacion.clasificar(r)
    conteo = {s: sum(1 for r in registros if r.estado_extraccion == s) for s in EstadoExtraccion}
    ej.ok = conteo[EstadoExtraccion.OK]
    ej.sin_stock = conteo[EstadoExtraccion.SIN_STOCK]
    ej.no_encontrados = conteo[EstadoExtraccion.NO_ENCONTRADO]
    ej.bloqueados = conteo[EstadoExtraccion.BLOQUEADO]
    ej.errores = (conteo[EstadoExtraccion.ERROR_HTTP] + conteo[EstadoExtraccion.ERROR_PARSEO]
                  + conteo[EstadoExtraccion.PROHIBIDO_ROBOTS])
    ej.registros = len(registros)
    ej.en_alcance = sum(1 for r in registros if r.en_alcance)
    if ej.ok + ej.sin_stock == 0:
        ej.estado = EstadoEjecucion.FALLIDA
    elif ej.errores or ej.bloqueados or ej.consultados < ej.descubiertos and limite is None:
        ej.estado = EstadoEjecucion.PARCIAL
    else:
        ej.estado = EstadoEjecucion.EXITOSA
    ej.fin, _ = ahora()
    ej.duracion_s = round(time.monotonic() - t0, 1)
    if registros:
        escribir_capturas(raiz, clave, fecha, id_ejecucion, registros)
    anexar_ejecucion(raiz, ej)
    return registros, ej


# --------------------------------------------------------------------------- corrida

async def ejecutar(sitios: list[str], modo: str, limite: int | None, datos: str | None = None,
                   config: dict | None = None, al_terminar=None) -> list[RegistroEjecucion]:
    """`al_terminar(ej)`, si se da, se llama (en un hilo aparte) apenas termina cada sitio: la tarea del
    contenedor la usa para subir ese sitio al lago sin esperar a los demás."""
    config = config or cargar_config()
    raiz = raiz_datos(config, datos)
    _, col = ahora()
    id_ejecucion = f"{col:%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:6]}"
    log.info("Corrida %s · modo %s · sitios %s · datos en %s", id_ejecucion, modo, ",".join(sitios), raiz)
    async def con_aviso(s: str):
        regs, ej = await ejecutar_sitio(s, config["fuentes"][s], config["comunes"], raiz, id_ejecucion, modo, limite)
        if al_terminar:
            try:
                await asyncio.to_thread(al_terminar, ej)
            except Exception:
                log.exception("[%s] falló el aviso de fin de sitio", s)
        return regs, ej

    tareas = [con_aviso(s) for s in sitios]
    resultados = await asyncio.gather(*tareas)
    return [ej for _, ej in resultados]


def imprimir_resumen(ejecuciones: list[RegistroEjecucion]) -> None:
    print(f"\n{'sitio':<10}{'estado':<10}{'descub.':>8}{'consult.':>9}{'ok':>6}{'sin_st':>7}"
          f"{'no_enc':>7}{'err':>5}{'bloq':>5}{'alcance':>8}{'seg':>8}")
    for e in ejecuciones:
        print(f"{e.sitio:<10}{e.estado.value:<10}{e.descubiertos:>8}{e.consultados:>9}{e.ok:>6}"
              f"{e.sin_stock:>7}{e.no_encontrados:>7}{e.errores:>5}{e.bloqueados:>5}{e.en_alcance:>8}"
              f"{e.duracion_s:>8.0f}")
    for e in ejecuciones:
        if e.estado != EstadoEjecucion.EXITOSA:
            print(f"  {e.sitio}: {e.mensaje}")


def main(argv: list[str] | None = None) -> int:
    config = cargar_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modo", choices=["completo", "seguimiento"], default="completo")
    ap.add_argument("--sitios", default=",".join(config["fuentes"]),
                    help="sitios separados por coma (por defecto, todos)")
    ap.add_argument("--limite", type=int, help="máximo de fichas por sitio (para pruebas)")
    ap.add_argument("--datos", help="carpeta raíz de datos (reemplaza TFM_DATOS y la configuración)")
    args = ap.parse_args(argv)
    sitios = [s.strip() for s in args.sitios.split(",") if s.strip()]
    desconocidos = [s for s in sitios if s not in config["fuentes"]]
    if desconocidos:
        ap.error(f"sitios desconocidos: {desconocidos}")
    for flujo in (sys.stdout, sys.stderr):
        flujo.reconfigure(encoding="utf-8", errors="replace")   # consola de Windows (cp1252)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ejecuciones = asyncio.run(ejecutar(sitios, args.modo, args.limite, args.datos, config))
    imprimir_resumen(ejecuciones)
    return 0 if all(e.estado != EstadoEjecucion.FALLIDA for e in ejecuciones) else 1


if __name__ == "__main__":
    sys.exit(main())
