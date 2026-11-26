# -*- coding: utf-8 -*-
"""Reproceso desde bronce: vuelve a extraer una corrida con las respuestas guardadas, sin pedir nada a los sitios.

Se usa cuando se corrige un extractor. Ejemplo: el 15-oct-2026 se corrigieron los precios de 10 millones o más
de Alkosto y Ktronix, que los microdatos publican en notación científica.

Cada fila de la tabla de productos original se reconstruye así:
  - si tiene evidencia (`ruta_bronze`) y su estado salió del parseo (OK, SIN_STOCK, NO_ENCONTRADO o
    ERROR_PARSEO, sin un error HTTP), se vuelve a parsear con el código actual;
  - si no (errores HTTP, bloqueos, robots), se conserva tal cual.
Se mantienen `id_ejecucion` y las fechas de captura originales; la clasificación (alcance) se recalcula.
Las respuestas de VTEX traen varios vendedores en un archivo: se parsean una vez y dan todas sus filas.
"""
from collections.abc import Callable

from src.extraccion import clasificacion
from src.extraccion.ejecutar import METODOS, parsear_respuesta
from src.extraccion.modelos import EstadoExtraccion, RegistroCaptura
from src.extraccion.sitios.base import Contexto

REPARSEABLES = {EstadoExtraccion.OK, EstadoExtraccion.SIN_STOCK, EstadoExtraccion.NO_ENCONTRADO,
                EstadoExtraccion.ERROR_PARSEO}
FECHAS = ("fecha_captura_utc", "fecha_captura_col")


def _reparseable(fila: dict) -> bool:
    return (bool(fila.get("ruta_bronze")) and EstadoExtraccion(fila["estado_extraccion"]) in REPARSEABLES
            and not (fila.get("mensaje") or "").startswith("HTTP "))


def _sin_vacios(fila: dict) -> dict:
    return {k: v for k, v in fila.items() if v not in ("", None)}


def reprocesar(filas: list[dict], leer_evidencia: Callable[[str], str | None], sitio: str,
               fuente: dict) -> list[RegistroCaptura]:
    """Filas del CSV original -> registros reconstruidos con el extractor actual (mismo orden)."""
    salida: list[RegistroCaptura] = []
    vistas: set[str] = set()
    por_respuesta: dict[str, list[dict]] = {}
    for fila in filas:
        if _reparseable(fila):
            por_respuesta.setdefault(fila["ruta_bronze"], []).append(fila)
    for fila in filas:
        ruta = fila.get("ruta_bronze")
        if not _reparseable(fila):
            salida.append(RegistroCaptura(**_sin_vacios(fila)))
            continue
        if ruta in vistas:           # otra fila de la misma respuesta (VTEX con varios vendedores)
            continue
        vistas.add(ruta)
        texto = leer_evidencia(ruta)
        if texto is None:
            raise FileNotFoundError(f"No está la evidencia {ruta} de {fila['url']}")
        ctx = Contexto(fila["id_ejecucion"], sitio, fuente["cadena"], METODOS[fuente["tipo"]],
                       str(fuente["vendedor_propio"]))
        # Cada fila conserva su momento de captura (en VTEX, cada vendedor tiene el suyo).
        originales = {_clave(f): f for f in por_respuesta[ruta]}
        for r in parsear_respuesta(fuente["tipo"], texto, fila["url"], ctx, ruta):
            previa = originales.get(_clave(r.model_dump(mode="json")), fila)
            r = RegistroCaptura(**{**r.model_dump(), **{k: previa[k] for k in FECHAS}})
            salida.append(clasificacion.clasificar(r))
    return salida


def _texto(valor) -> str:
    return "" if valor is None else str(valor)


def _clave(fila: dict) -> tuple:
    """Identifica una fila: la respuesta guardada y, dentro de ella, la oferta. Las fichas retiradas
    redirigen todas a la misma página, así que la URL sola no basta."""
    return tuple(_texto(fila.get(k)) for k in ("ruta_bronze", "url", "sku_tienda", "vendedor"))


def cambios(antes: list[dict], despues: list[RegistroCaptura]) -> list[dict]:
    """Diferencias campo a campo entre una versión del CSV y los registros reconstruidos."""
    previas = {}
    for f in antes:
        previas.setdefault(_clave(f), f)
    nuevas = [r.model_dump(mode="json") for r in despues]
    diferencias = []
    for f in nuevas:
        vieja = previas.pop(_clave(f), None)
        if vieja is None:
            diferencias.append({"url": f["url"], "ruta_bronze": _texto(f.get("ruta_bronze")), "campo": "(fila nueva)", "antes": "", "despues": f["sitio"]})
            continue
        for campo, valor in f.items():
            if _texto(valor) != _texto(vieja.get(campo)):
                diferencias.append({"url": f["url"], "ruta_bronze": _texto(f.get("ruta_bronze")), "campo": campo, "antes": _texto(vieja.get(campo)),
                                    "despues": _texto(valor)})
    for vieja in previas.values():
        diferencias.append({"url": vieja["url"], "ruta_bronze": vieja.get("ruta_bronze") or "",
                            "campo": "(fila eliminada)", "antes": vieja["sitio"], "despues": ""})
    return diferencias
