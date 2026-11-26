# -*- coding: utf-8 -*-
"""Reproceso desde bronce (src/extraccion/reproceso.py y src/nube/reproceso.py) sobre una carpeta que imita al lago."""
import csv
import io
import json
from pathlib import Path

from src.extraccion.ejecutar import cargar_config, csv_capturas
from src.extraccion.modelos import EstadoExtraccion, RegistroCaptura
from src.nube import lago
from src.nube import reproceso

FIXTURES = Path(__file__).parent / "fixtures"
ID = "20261014T195952_c2e165"
EVIDENCIA = f"bronze/alkosto/fecha=2026-10-14/{ID}/00282_6921732899530.html.gz"
URL = "https://www.alkosto.com/tv-tcl-115-pulgadas-2921-cm-115c7k-4k-uhd-qd-mini-led/p/6921732899530"
CRUDO = f"{lago.ATERRIZAJE}/alkosto/crudo/2026/10/14/productos_alkosto_20261014_195952"
FECHA_UTC, FECHA_COL = "2026-10-15T01:09:39.123456Z", "2026-10-14T20:09:39.123456-05:00"


def fila(**campos) -> RegistroCaptura:
    base = dict(id_ejecucion=ID, fecha_captura_utc=FECHA_UTC, fecha_captura_col=FECHA_COL, cadena="Alkosto/Ktronix",
                sitio="alkosto", url=URL, metodo="http_html")
    return RegistroCaptura(**{**base, **campos})


def lago_con_error(raiz: Path) -> lago.DestinoLocal:
    """Corrida del 14-oct con el error: 3.999.997 en lugar de 39.999.900; más una fila con error HTTP."""
    destino = lago.DestinoLocal(raiz)
    destino.subir((FIXTURES / "alkosto_ficha_precio_alto.html.gz").read_bytes(), lago.ruta_en_lago(EVIDENCIA))
    filas = [fila(estado_extraccion=EstadoExtraccion.OK, ruta_bronze=EVIDENCIA, sku_tienda="6921732899530",
                  ean_publicado="6921732899530", titulo="TV TCL 115\" Pulgadas", marca="TCL", precio_venta=3999997,
                  precio_lista=79999900, disponible=True, vendedor="Alkosto", es_vendedor_propio=True),
             fila(estado_extraccion=EstadoExtraccion.ERROR_HTTP, url="https://www.alkosto.com/otro/p/1", mensaje="HTTP 503")]
    destino.subir(csv_capturas(filas).encode("utf-8-sig"), f"{CRUDO}.csv")
    return destino


def leer(destino, ruta) -> list[dict]:
    return list(csv.DictReader(io.StringIO(destino.bajar(ruta).decode("utf-8-sig")), delimiter=";"))


def test_reproceso_corrige_sin_tocar_el_original(tmp_path):
    destino = lago_con_error(tmp_path)
    original = destino.bajar(f"{CRUDO}.csv")
    fuente = cargar_config()["fuentes"]["alkosto"]

    ensayo = reproceso.reprocesar_sitio(destino, "alkosto", fuente, "prueba", aplicar=False)
    assert ensayo[0]["filas_cambiadas"] == 1 and "destino" not in ensayo[0]
    assert not destino.listar(f"{lago.ATERRIZAJE}/alkosto/reprocesos")

    hecho = reproceso.reprocesar_sitio(destino, "alkosto", fuente, "prueba", aplicar=True)
    assert hecho[0]["destino"] == f"{CRUDO}_r1.csv"
    assert destino.bajar(f"{CRUDO}.csv") == original                       # el original no cambia
    nuevo = leer(destino, f"{CRUDO}_r1.csv")
    tv, error = nuevo
    assert (tv["precio_venta"], tv["precio_lista"]) == ("39999900", "79999900")
    assert (tv["fecha_captura_utc"], tv["id_ejecucion"]) == (FECHA_UTC, ID)  # se conserva el momento de la captura
    assert tv["en_alcance"] == "True" and tv["ruta_bronze"] == EVIDENCIA
    assert (error["estado_extraccion"], error["mensaje"]) == ("ERROR_HTTP", "HTTP 503")

    manifiesto = json.loads(destino.bajar(f"{lago.ATERRIZAJE}/alkosto/reprocesos/reproceso_20261014_195952_r1.json"))
    assert manifiesto["motivo"] == "prueba" and manifiesto["origen"] == f"{CRUDO}.csv"
    assert {"url": URL, "ruta_bronze": EVIDENCIA, "campo": "precio_venta",
            "antes": "3999997", "despues": "39999900"} in manifiesto["cambios"]
    assert all(c["url"] == URL for c in manifiesto["cambios"])          # la fila con error HTTP no cambia

    # Repetirlo no crea otra versión: ya no hay diferencias con la última.
    otra = reproceso.reprocesar_sitio(destino, "alkosto", fuente, "prueba", aplicar=True)
    assert otra[0]["filas_cambiadas"] == 0 and "destino" not in otra[0]
    assert sorted(v for v, _ in reproceso.versiones(destino, "alkosto")[CRUDO]) == [0, 1]
