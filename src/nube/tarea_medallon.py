# -*- coding: utf-8 -*-
"""Punto de entrada del job de medallón (Azure Container Apps Job `caj-tfm-medallon`, opción B de la Etapa 3).

Spark corre en modo local dentro del contenedor, con el mismo código de `src/medallon`:

    1. baja del lago lo que Spark lee: de `bronce/aterrizaje`, solo crudo, ejecuciones, maestro y revisión
       (no la evidencia de capturas/); las tablas Delta de `bronce/conformidad` (carga incremental) y solo
       el `_delta_log` de plata y oro, que se sobrescriben completas en cada corrida;
    2. ejecuta `src/medallon/semanal.py` sobre esa copia local;
    3. sube los archivos nuevos o modificados de conformidad, plata y oro: primero los datos y al final
       `_delta_log`, para que nadie lea una versión que apunte a archivos que todavía no están en el lago;
    4. arma el resumen diario y las alertas (src/servicios/), guarda los mensajes en
       `oro/servicios/avisos/` y, si los datos son de hoy y existe TFM_URL_AVISOS (Logic App
       la-tfm-avisos), los envía. Una falla aquí no hace fallar el medallón: queda en el resumen.

No se usa `abfss://` directo porque el conector de Hadoop 3.3.4 (Spark 3.4) solo pide el token de la
identidad administrada al IMDS de las máquinas virtuales, y Container Apps la expone por IDENTITY_ENDPOINT.
La copia se hace con el SDK de Python y DefaultAzureCredential, igual que la captura (src/nube/lago.py).

Uso:
    python -m src.nube.tarea_medallon                    # contra el lago (identidad administrada o az login)
    python -m src.nube.tarea_medallon --lago-local /lago # una carpeta como lago (ensayo sin Azure)
    python -m src.nube.tarea_medallon --sin-avisos       # sin resumen ni alertas (reprocesos)
"""
import argparse
import json
import logging
import os
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.nube import lago

log = logging.getLogger("tarea_medallon")

SALIDAS = ["bronce/conformidad", "plata", "oro"]
RESUMENES = "plata/control/medallon"
AVISOS = "oro/servicios/avisos"
SUSCRIPCIONES = f"{lago.ATERRIZAJE}/suscripciones/suscripciones.yaml"
COLOMBIA = timezone(timedelta(hours=-5))


def entradas(sitios: list[str]) -> list[str]:
    """Carpetas de la zona de aterrizaje que lee el medallón."""
    a = lago.ATERRIZAJE
    return ([f"{a}/{s}/{t}" for s in sitios for t in ("crudo", "ejecuciones")]
            + [f"{a}/maestro", f"{a}/revision", f"{a}/suscripciones"])


def es_checksum(ruta: str) -> bool:
    """Archivos `.nombre.crc` que crea el sistema de archivos local de Hadoop; no van al lago."""
    nombre = ruta.rsplit("/", 1)[-1]
    return nombre.startswith(".") and nombre.endswith(".crc")


def huella(raiz: Path) -> dict[str, int]:
    """Archivos de salida en la copia local -> fecha de modificación (ns)."""
    return {p.relative_to(raiz).as_posix(): p.stat().st_mtime_ns
            for prefijo in SALIDAS if (raiz / prefijo).exists()
            for p in (raiz / prefijo).rglob("*") if p.is_file()}


def bajar(destino: lago.Destino, raiz: Path, sitios: list[str]) -> tuple[int, int]:
    """Copia al disco local lo que Spark necesita leer. Devuelve (archivos, bytes)."""
    remotos = {}
    for prefijo in entradas(sitios) + ["bronce/conformidad"]:
        remotos |= destino.listar(prefijo)
    for prefijo in SALIDAS[1:]:
        remotos |= {r: n for r, n in destino.listar(prefijo).items() if "/_delta_log/" in r}
    for remota in sorted(remotos):
        ruta = raiz / remota
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(destino.bajar(remota))
    return len(remotos), sum(remotos.values())


def subir(destino: lago.Destino, raiz: Path, antes: dict[str, int]) -> tuple[int, int]:
    """Sube las salidas nuevas o modificadas; `_delta_log` al final y en orden de versión."""
    cambios = [r for r, t in huella(raiz).items() if antes.get(r) != t and not es_checksum(r)]
    cambios.sort(key=lambda r: ("/_delta_log/" in r, r))
    total = 0
    for i, remota in enumerate(cambios, 1):
        contenido = (raiz / remota).read_bytes()
        destino.subir(contenido, remota)
        total += len(contenido)
        if i % 500 == 0:
            log.info("%d/%d archivos subidos", i, len(cambios))
    return len(cambios), total


def sesion_spark():
    """Spark 3.4 local con Delta 2.4 (los jar vienen en la imagen, ver medallon.Dockerfile)."""
    os.environ.setdefault("PYSPARK_SUBMIT_ARGS",
                          f"--driver-memory {os.environ.get('TFM_SPARK_MEMORIA', '3g')} pyspark-shell")
    from pyspark.sql import SparkSession
    spark = (SparkSession.builder.master("local[*]").appName("tfm-medallon")
             .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
             .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
             .config("spark.sql.shuffle.partitions", "8")
             .config("spark.ui.enabled", "false")
             .getOrCreate())
    spark.sparkContext.setLogLevel("WARN")
    return spark


def enviar(url: str, cuerpo: dict, intentos: int = 3) -> int:
    """POST a la Logic App de avisos. Devuelve el código HTTP."""
    datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
    for i in range(1, intentos + 1):
        try:
            req = urllib.request.Request(url, data=datos, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status
        except Exception as e:
            if i == intentos:
                raise
            log.warning("Envío de avisos falló (%s); reintento %d", type(e).__name__, i)
            time.sleep(10 * i)
    return 0


def avisos_del_dia(destino: lago.Destino, raiz: Path, spark, hoy: str | None = None) -> dict:
    """Resumen diario y alertas (fase 5). Guarda los mensajes en el lago y los envía si son de hoy."""
    from src.medallon.detector import parametros
    from src.servicios import avisos, datos_dia

    datos = datos_dia.leer(spark, raiz.as_posix())
    salida = avisos.armar(datos, avisos.leer_suscripciones(raiz / SUSCRIPCIONES), parametros())
    destino.subir(json.dumps({"datos": datos, "salida": salida}, ensure_ascii=False, indent=1, default=str)
                  .encode("utf-8"), f"{AVISOS}/avisos_{datos['fecha_key']}.json")
    hoy = hoy or datetime.now(COLOMBIA).date().isoformat()
    r = {"fecha_datos": datos["fecha"], "mensajes": len(salida["mensajes"]), "eventos": len(datos["eventos"])}
    url = os.environ.get("TFM_URL_AVISOS")
    if datos["fecha"] != hoy:
        r["envio"] = f"no se envía: los datos son del {datos['fecha']}, no de hoy ({hoy})"
    elif not url:
        r["envio"] = "no se envía: falta TFM_URL_AVISOS"
    else:
        r["envio"] = f"HTTP {enviar(url, salida)}"
    log.info("Avisos: %s", r)
    return r


def ejecutar(destino: lago.Destino, raiz: Path, sitios: list[str], spark, con_avisos: bool = True) -> dict:
    """Ciclo completo: bajar, procesar con Spark y subir. Devuelve el resumen de la corrida."""
    from src.medallon import semanal

    resumen = {"inicio_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sitios": sitios}
    t0 = time.monotonic()
    archivos, bytes_ = bajar(destino, raiz, sitios)
    resumen["bajada"] = {"archivos": archivos, "bytes": bytes_, "_segundos": round(time.monotonic() - t0)}
    log.info("Bajados del lago: %d archivos (%.1f MB)", archivos, bytes_ / 1e6)

    antes = huella(raiz)
    t0 = time.monotonic()
    resumen["medallon"] = semanal.ejecutar(spark, raiz.as_posix(), sitios)
    resumen["medallon"]["_segundos"] = round(time.monotonic() - t0)

    t0 = time.monotonic()
    archivos, bytes_ = subir(destino, raiz, antes)
    resumen["subida"] = {"archivos": archivos, "bytes": bytes_, "_segundos": round(time.monotonic() - t0)}
    log.info("Subidos al lago: %d archivos (%.1f MB)", archivos, bytes_ / 1e6)

    if con_avisos:
        try:
            resumen["avisos"] = avisos_del_dia(destino, raiz, spark)
        except Exception as e:
            log.exception("Falló el armado o el envío de los avisos")
            resumen["avisos"] = {"error": f"{type(e).__name__}: {e}"[:300]}

    resumen["fin_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    marca = resumen["inicio_utc"][:19].replace("-", "").replace(":", "").replace("T", "_")
    destino.subir(json.dumps(resumen, ensure_ascii=False, indent=1).encode("utf-8"),
                  f"{RESUMENES}/medallon_{marca}.json")
    return resumen


def main(argv: list[str] | None = None) -> int:
    from src.medallon.rutas import SITIOS

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sitios", default=",".join(SITIOS))
    ap.add_argument("--lago-local", help="carpeta que reemplaza a ADLS (ensayo sin Azure)")
    ap.add_argument("--datos", help="carpeta de trabajo local (por defecto, una temporal)")
    ap.add_argument("--sin-avisos", action="store_true", help="no arma ni envía el resumen y las alertas")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("azure").setLevel(logging.WARNING)

    sitios = [s.strip() for s in args.sitios.split(",") if s.strip()]
    destino = lago.DestinoLocal(Path(args.lago_local)) if args.lago_local else lago.destino_desde_entorno()
    raiz = Path(args.datos or tempfile.mkdtemp(prefix="tfm_medallon_"))
    spark = sesion_spark()
    try:
        resumen = ejecutar(destino, raiz, sitios, spark, con_avisos=not args.sin_avisos)
    finally:
        spark.stop()
    print(json.dumps(resumen, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
