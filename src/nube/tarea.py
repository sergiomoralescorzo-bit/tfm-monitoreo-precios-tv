# -*- coding: utf-8 -*-
"""Punto de entrada del contenedor (Azure Container Apps Job).

    1. baja `estado/` del lago (fichas descubiertas, para el modo seguimiento);
    2. corre la extracción de los sitios en una carpeta de trabajo temporal;
    3. sube al lago cada sitio apenas termina (ver src/nube/lago.py); al final, lo que haya quedado.

Los sitios que ya tienen una ejecución EXITOSA o PARCIAL ese día no se vuelven a consultar, para que el
reintento automático de pl_orquestador_diario (hasta 3 intentos, cada 20 min) solo repita los que fallaron.
`--repetir` los consulta de nuevo (recuperación manual de todo el día).

Uso:
    python -m src.nube.tarea                     # modo según el día en Colombia: domingo = completo
    python -m src.nube.tarea --modo completo --sitios jumbo --limite 5
    python -m src.nube.tarea --repetir           # consulta también los sitios que ya terminaron hoy
    python -m src.nube.tarea --sin-lago          # solo extrae (prueba local del contenedor)
    python -m src.nube.tarea --lago-local /lago  # usa una carpeta como lago (ensayo sin Azure)

Variables de entorno (opcionales): TFM_ADLS_CUENTA (por defecto `sttfmwebscraping`),
TFM_ADLS_CONTENEDOR (por defecto `datalake-tfm`) y, para pruebas fuera de Azure, TFM_ADLS_CONEXION.
"""
import argparse
import asyncio
import logging
import sys
import tempfile
from pathlib import Path

from src.extraccion.ejecutar import cargar_config, ejecutar, imprimir_resumen
from src.extraccion.modelos import EstadoEjecucion
from src.extraccion.sitios.base import ahora
from src.nube import lago

log = logging.getLogger("tarea")


def modo_del_dia() -> str:
    _, col = ahora()
    return "completo" if col.weekday() == 6 else "seguimiento"


def main(argv: list[str] | None = None) -> int:
    config = cargar_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modo", choices=["completo", "seguimiento"], help="por defecto, según el día")
    ap.add_argument("--sitios", default=",".join(config["fuentes"]))
    ap.add_argument("--limite", type=int, help="máximo de fichas por sitio (para pruebas)")
    ap.add_argument("--sin-lago", action="store_true", help="no lee ni escribe en ADLS")
    ap.add_argument("--lago-local", help="carpeta que reemplaza a ADLS (ensayo sin Azure)")
    ap.add_argument("--datos", help="carpeta de trabajo local (por defecto, una temporal)")
    ap.add_argument("--repetir", action="store_true", help="consulta también los sitios que ya terminaron hoy")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("azure").setLevel(logging.WARNING)

    modo = args.modo or modo_del_dia()
    sitios = [s.strip() for s in args.sitios.split(",") if s.strip()]
    raiz = Path(args.datos or tempfile.mkdtemp(prefix="tfm_"))
    if args.sin_lago:
        destino = None
    elif args.lago_local:
        destino = lago.DestinoLocal(Path(args.lago_local))
    else:
        destino = lago.destino_desde_entorno()

    if destino and not args.repetir:
        hechos = lago.sitios_terminados(destino, sitios, ahora()[1].strftime("%Y%m%d"))
        for sitio, estado in hechos.items():
            log.info("[%s] ya tiene una ejecución %s hoy: no se repite (use --repetir para forzarla)", sitio, estado)
        sitios = [s for s in sitios if s not in hechos]
        if not sitios:
            log.info("Todos los sitios ya terminaron hoy: nada que hacer")
            return 0

    if destino:
        log.info("Estado bajado del lago: %d archivos", lago.bajar_estado(destino, raiz, sitios))
    subidos: set[str] = set()

    def subir_sitio(ej) -> None:
        """Sube un sitio apenas termina: si el contenedor se corta después (memoria, tiempo), no se pierde."""
        n = lago.subir_corrida(destino, raiz, ej.id_ejecucion, sitios=[ej.sitio])
        subidos.add(ej.sitio)
        log.info("[%s] subido al lago: %d archivos", ej.sitio, n)

    ejecuciones = asyncio.run(ejecutar(sitios, modo, args.limite, str(raiz), config,
                                       al_terminar=subir_sitio if destino else None))
    imprimir_resumen(ejecuciones)
    if destino and ejecuciones:
        id_ejecucion = ejecuciones[0].id_ejecucion
        pendientes = [e.sitio for e in ejecuciones if e.sitio not in subidos]
        n = lago.subir_corrida(destino, raiz, id_ejecucion, sitios=pendientes) if pendientes else 0
        log.info("Corrida %s en el lago (%d sitios al terminar; %d archivos al final)",
                 id_ejecucion, len(subidos), n)
    return 0 if all(e.estado != EstadoEjecucion.FALLIDA for e in ejecuciones) else 1


if __name__ == "__main__":
    sys.exit(main())
