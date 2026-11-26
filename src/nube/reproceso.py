# -*- coding: utf-8 -*-
"""Reproceso en el lago: corrige tablas de productos ya capturadas a partir de su evidencia en bronce.

No borra ni sobrescribe nada: deja la versión corregida junto a la original y un manifiesto.

    crudo/AAAA/MM/DD/productos_{sitio}_{ts}.csv        original (sin cambios)
    crudo/AAAA/MM/DD/productos_{sitio}_{ts}_r1.csv     versión 1, reconstruida con el extractor corregido
    reprocesos/reproceso_{ts}_r1.json                  motivo, origen, destino y cambios campo a campo

Conformidad carga las dos versiones (trazabilidad) y plata usa solo la última versión de cada archivo.
Si la reconstrucción no cambia nada frente a la última versión, no se escribe ninguna versión nueva.

Uso (sin --aplicar solo muestra lo que cambiaría):
    python -m src.nube.reproceso --sitios alkosto,ktronix --motivo "precios >= 10 M en notación científica"
    python -m src.nube.reproceso --sitios alkosto,ktronix --motivo "..." --aplicar
    python -m src.nube.reproceso ... --lago-local /lago        # ensayo sin Azure
"""
import argparse
import csv
import gzip
import io
import json
import logging
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.extraccion import reproceso
from src.extraccion.ejecutar import cargar_config, csv_capturas
from src.nube import lago

log = logging.getLogger("reproceso")

VERSION = re.compile(r"^(?P<base>.+/productos_[a-z]+_\d{8}_\d{6})(?:_r(?P<n>\d+))?\.csv$")


def leer_csv(contenido: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(contenido.decode("utf-8-sig")), delimiter=";"))


def versiones(destino: lago.Destino, sitio: str, fecha: str | None = None) -> dict[str, list[tuple[int, str]]]:
    """Tablas de productos del sitio -> [(versión, ruta)], de la original (0) a la última."""
    prefijo = f"{lago.ATERRIZAJE}/{sitio}/crudo" + (f"/{fecha.replace('-', '/')}" if fecha else "")
    grupos: dict[str, list[tuple[int, str]]] = {}
    for ruta in destino.listar(prefijo):
        m = VERSION.match(ruta)
        if m:
            grupos.setdefault(m["base"], []).append((int(m["n"] or 0), ruta))
    return {base: sorted(v) for base, v in sorted(grupos.items())}


def lector_evidencia(destino: lago.Destino):
    def leer(ruta_bronze: str) -> str | None:
        contenido = destino.bajar(lago.ruta_en_lago(ruta_bronze))
        return None if contenido is None else gzip.decompress(contenido).decode("utf-8")
    return leer


def reprocesar_sitio(destino: lago.Destino, sitio: str, fuente: dict, motivo: str, aplicar: bool,
                     fecha: str | None = None) -> list[dict]:
    """Reprocesa cada tabla de productos del sitio. Devuelve un resumen por tabla."""
    resumen = []
    for base, lista in versiones(destino, sitio, fecha).items():
        n_ultima, ultima = lista[-1]
        original = leer_csv(destino.bajar(lista[0][1]))
        registros = reproceso.reprocesar(original, lector_evidencia(destino), sitio, fuente)
        diferencias = reproceso.cambios(leer_csv(destino.bajar(ultima)), registros)
        fila = {"origen": lista[0][1], "ultima_version": n_ultima, "filas": len(registros),
                "filas_cambiadas": len({(d["ruta_bronze"], d["url"]) for d in diferencias}),
                "campos": dict(Counter(d["campo"] for d in diferencias))}
        if diferencias and aplicar:
            n = n_ultima + 1
            fila["destino"] = f"{base}_r{n}.csv"
            destino.subir(csv_capturas(registros).encode("utf-8-sig"), fila["destino"])
            manifiesto = {"fecha_reproceso_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "motivo": motivo, "version": n, "comparado_con": ultima, **fila, "cambios": diferencias}
            ts = base.rsplit("_", 2)[-2] + "_" + base.rsplit("_", 1)[-1]
            destino.subir(json.dumps(manifiesto, ensure_ascii=False, indent=1).encode("utf-8"),
                          f"{lago.ATERRIZAJE}/{sitio}/reprocesos/reproceso_{ts}_r{n}.json")
        resumen.append(fila)
    return resumen


def main(argv: list[str] | None = None) -> int:
    config = cargar_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sitios", required=True)
    ap.add_argument("--motivo", required=True, help="por qué se reprocesa (queda en el manifiesto)")
    ap.add_argument("--fecha", help="solo ese día (AAAA-MM-DD)")
    ap.add_argument("--aplicar", action="store_true", help="escribe las versiones nuevas; sin esto, solo informa")
    ap.add_argument("--lago-local", help="carpeta que reemplaza a ADLS (ensayo sin Azure)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("azure").setLevel(logging.WARNING)

    destino = lago.DestinoLocal(Path(args.lago_local)) if args.lago_local else lago.destino_desde_entorno()
    for sitio in [s.strip() for s in args.sitios.split(",") if s.strip()]:
        for fila in reprocesar_sitio(destino, sitio, config["fuentes"][sitio], args.motivo, args.aplicar, args.fecha):
            print(json.dumps({"sitio": sitio, **fila}, ensure_ascii=False))
    if not args.aplicar:
        print("Ensayo: no se escribió nada. Use --aplicar para guardar las versiones nuevas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
